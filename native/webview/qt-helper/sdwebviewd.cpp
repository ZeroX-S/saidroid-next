// Host-only WebView bridge: Qt/WPE stay outside the ART/bionic process.
#include <QGuiApplication>
#include <QQmlEngine>
#include <QQmlContext>
#include <QQmlComponent>
#include <QQuickItem>
#include <QQuickWindow>
#include <QQuickRenderControl>
#include <QOpenGLContext>
#include <QOpenGLFunctions>
#include <QOffscreenSurface>
#include <QOpenGLFramebufferObject>
#include <QSocketNotifier>
#include <QTimer>
#include <QElapsedTimer>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDebug>
#include <QFileInfo>
#include <QLibrary>
#include <memory>
#include <unistd.h>
#include <fcntl.h>
#include <sys/prctl.h>
#include <sys/uio.h>
#include <signal.h>
#include <errno.h>
#define __WPE_H_INSIDE__
#define WPE_EXPORT
#include "include/wpe-input.h"
#undef WPE_EXPORT
#undef __WPE_H_INSIDE__
#include "include/webview-geometry.h"

static void logMessage(QtMsgType, const QMessageLogContext &, const QString &message)
{ fprintf(stderr, "%s\n", message.toUtf8().constData()); fflush(stderr); }

#include "webkit-boundary.h"
#include "webkit-ime.h"

static constexpr int maxFrameBytes = 2160 * 4096 * 4;
static constexpr int maxQueuedBytes = maxFrameBytes + 15 * 1024 * 1024;

class WebHost : public QObject {
    Q_OBJECT
    QQuickRenderControl control;
    QQuickWindow window;
    QOpenGLContext context;
    QOffscreenSurface surface;
    std::unique_ptr<QOpenGLFramebufferObject> fbo;
    QQmlEngine engine;
    std::unique_ptr<WebBoundary> boundary;
    std::unique_ptr<WebIme> ime;
    QQuickItem *root = nullptr;
    QSocketNotifier input, output;
    QTimer renderTimer, watchdog;
    QByteArray incoming, outgoing;
    int width, height;
    bool renderPending = true, frameDirty = true, awaitingAck = false, initialized = false, configured = false, terminationHooked = false, active = true;
    quint64 serial = 0, renders = 0, sentFrames = 0;
    QElapsedTimer lifetime;
    bool touchActive=false;
    int touchX=0,touchY=0;

    void packet(QJsonObject object, const QByteArray &payload = QByteArray()) {
        const QByteArray json = QJsonDocument(object).toJson(QJsonDocument::Compact);
        quint32 length = quint32(json.size());
        char header[4] = { char(length >> 24), char(length >> 16), char(length >> 8), char(length) };
        outgoing.append(header, 4); outgoing.append(json); outgoing.append(payload);
        // At most one frame is outstanding; control events also have a hard cap.
        if (outgoing.size() > maxQueuedBytes) { qCritical("SDWEBHOST=output_overflow"); QCoreApplication::exit(11); return; }
        flush();
    }
    void flush() {
        while (!outgoing.isEmpty()) {
            struct iovec buffer = { const_cast<char *>(outgoing.constData()), size_t(outgoing.size()) };
            ssize_t size = ::writev(STDOUT_FILENO, &buffer, 1);
            if (size > 0) outgoing.remove(0, int(size));
            else if (size < 0 && errno == EINTR) continue;
            else if (size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
            else { QCoreApplication::exit(12); return; }
        }
        output.setEnabled(!outgoing.isEmpty());
    }
    void dispatch(QJsonObject object) {
        const QString op = object.value("op").toString();
        if(ime&&ime->command(object))return;
        if(boundary&&boundary->command(object))return;
        if (op == "stats") {
            packet(QJsonObject{{"event","stats"},{"frames",double(sentFrames)},{"renders",double(renders)},
                {"elapsed_ms",double(lifetime.elapsed())}});return;
        }
        if (op == "quit") { QCoreApplication::quit(); return; }
        if (op == "frame_ack") {
            if (object.value("seq").toDouble() != double(serial)) return;
            awaitingAck = false; watchdog.stop();
            if (active && (renderPending || frameDirty) && !renderTimer.isActive()) renderTimer.start(0);
            return;
        }
        if (op == "resize") {
            const int w = object.value("width").toInt(), h = object.value("height").toInt();
            if (w < 1 || h < 1 || w > 2160 || h > 4096 || qint64(w) * h * 4 > maxFrameBytes) {
                packet(QJsonObject{{"event","error"},{"message","invalid viewport"}}); return;
            }
            if (w != width || h != height) {
                width = w; height = h;
                context.makeCurrent(&surface);
                window.setGeometry(0,0,w,h); window.contentItem()->setSize(QSizeF(w,h));
                root->setSize(QSizeF(w,h));
                fbo.reset(new QOpenGLFramebufferObject(QSize(w,h),QOpenGLFramebufferObject::CombinedDepthStencil));
                window.setRenderTarget(fbo.get()); frameDirty = true;
            }
            schedule(); return;
        }
        if (op == "settings") {
            // Use the plugin's exported opaque accessor. No Qt object layout is
            // copied across the boundary; all WebKit operations use public C APIs.
            using Getter = void *(*)(const void *);
            using SettingsGetter = void *(*)(void *);
            using ObjectSet = void (*)(void *,const char *,...);
            static Getter getter = reinterpret_cast<Getter>(QLibrary::resolve("/usr/lib64/libqtwpe.so","_ZNK9WPEQtView7webViewEv"));
            static SettingsGetter settingsGetter = reinterpret_cast<SettingsGetter>(QLibrary::resolve("/usr/lib64/libWPEWebKit-2.0.so.1","webkit_web_view_get_settings"));
            static ObjectSet objectSet = reinterpret_cast<ObjectSet>(QLibrary::resolve("/usr/lib64/libgobject-2.0.so.0","g_object_set"));
            QObject *web = root->findChild<QObject *>("web");
            void *view = getter && web ? getter(web) : nullptr;
            void *settings = view && settingsGetter ? settingsGetter(view) : nullptr;
            if (!settings || !objectSet) {
                configured = false;
                packet(QJsonObject{{"event","error"},{"message","WebKit settings ABI unavailable"}}); return;
            }
            if(!boundary){
                boundary.reset(new WebBoundary(view,[this](QJsonObject event){packet(event);},[this](QJsonObject command){QVariant argument=command.toVariantMap();QMetaObject::invokeMethod(root,"command",Q_ARG(QVariant,argument));},this));
                if(!boundary->initialize()){packet(QJsonObject{{"event","error"},{"message","WebKit navigation/script/cookie ABI unavailable"}});boundary.reset();return;}
            }
            if(!ime){
                ime.reset(new WebIme(view,[this](QJsonObject event){packet(event);}));
                if(!ime->initialize()){packet(QJsonObject{{"event","error"},{"message","WebKit input method ABI unavailable"}});ime.reset();return;}
            }
            if (!terminationHooked) {
                using Connect = unsigned long (*)(void *,const char *,void (*)(),void *,void *,int);
                static Connect hook = reinterpret_cast<Connect>(QLibrary::resolve("/usr/lib64/libgobject-2.0.so.0","g_signal_connect_data"));
                if (!hook) { packet(QJsonObject{{"event","error"},{"message","termination hook unavailable"}});return; }
                hook(view,"web-process-terminated",reinterpret_cast<void (*)()>(+[](void *,int reason,void *data) {
                    auto *host=static_cast<WebHost *>(data);
                    host->packet(QJsonObject{{"event","error"},{"message",QString("web process terminated: %1").arg(reason)}});
                    QCoreApplication::exit(19);
                }),this,nullptr,0);
                terminationHooked=true;
            }
            const qreal scale=object.value("deviceScale").toDouble(1.0);
            if (scale<0.5 || scale>4.0 || !QMetaObject::invokeMethod(web,"setDeviceScaleFactor",Q_ARG(qreal,scale))) {
                packet(QJsonObject{{"event","error"},{"message","device scale API unavailable"}});return;
            }
            const QByteArray ua = object.value("userAgent").toString().toUtf8();
            objectSet(settings,"enable-javascript",int(object.value("javascript").toBool()),
                "auto-load-images",int(object.value("images").toBool(true)),
                "enable-html5-local-storage",int(object.value("storage").toBool()),
                "javascript-can-open-windows-automatically",int(object.value("javascriptWindows").toBool()),
                "user-agent",ua.isEmpty() ? nullptr : ua.constData(),nullptr);
            configured = true;
            packet(QJsonObject{{"event","settings"},{"javascript",object.value("javascript").toBool()}}); return;
        }
        if (op == "load" && !configured) {
            packet(QJsonObject{{"event","error"},{"message","settings required before load"}}); return;
        }
        if (op == "visibility") {
            active=object.value("active").toBool();
            using Visibility = void (*)(void *,bool);
            static Visibility setVisible=reinterpret_cast<Visibility>(QLibrary::resolve("/usr/lib64/libqtwpe.so","_ZN9WPEQtView16setWebKitVisibleEb"));
            QObject *web=root->findChild<QObject *>("web");
            if (!setVisible || !web) {packet(QJsonObject{{"event","error"},{"message","visibility ABI unavailable"}});return;}
            setVisible(web,active);
            if(active)schedule();else renderTimer.stop();
            packet(QJsonObject{{"event","visibility"},{"active",active}});return;
        }
        if (op == "touch") {
            // The Android View has already performed hit testing. Feed its
            // host viewport pixels to libwpe once; WPEQtView's Qt touch adapter would
            // divide by DPR before WebKit divides again (measured at DPR 2.625).
            using Getter=void *(*)(const void *);
            using GetObject=void *(*)(void *);
            using Dispatch=void (*)(void *,const struct wpe_input_touch_event *);
            static Getter getView=reinterpret_cast<Getter>(QLibrary::resolve("/usr/lib64/libqtwpe.so","_ZNK9WPEQtView7webViewEv"));
            static GetObject getBackend=reinterpret_cast<GetObject>(QLibrary::resolve("/usr/lib64/libWPEWebKit-2.0.so.1","webkit_web_view_get_backend"));
            static GetObject getWpeBackend=reinterpret_cast<GetObject>(QLibrary::resolve("/usr/lib64/libWPEWebKit-2.0.so.1","webkit_web_view_backend_get_wpe_backend"));
            static Dispatch dispatchTouch=reinterpret_cast<Dispatch>(QLibrary::resolve("/usr/lib64/libwpe-1.0.so.1","wpe_view_backend_dispatch_touch_event"));
            QObject *web=root->findChild<QObject *>("web");
            void *view=getView&&web?getView(web):nullptr;
            void *viewBackend=view&&getBackend?getBackend(view):nullptr;
            void *backend=viewBackend&&getWpeBackend?getWpeBackend(viewBackend):nullptr;
            if (!backend||!dispatchTouch) {packet(QJsonObject{{"event","error"},{"message","WPE input API unavailable"}});return;}
            const int action=object.value("action").toInt();
            if (action<0||action>3) return;
            if (action==0) touchActive=true;
            if (!touchActive) return;
            if (action==0||action==2) {
                touchX=qRound(sd_webview_coordinate(object.value("x").toDouble(),object.value("viewWidth").toInt(),width));
                touchY=qRound(sd_webview_coordinate(object.value("y").toDouble(),object.value("viewHeight").toInt(),height));
            }
            const uint32_t time=uint32_t(object.value("time").toDouble(lifetime.elapsed()));
            const auto type=action==0?wpe_input_touch_event_type_down:
                (action==2?wpe_input_touch_event_type_motion:wpe_input_touch_event_type_up);
            struct wpe_input_touch_event_raw point={type,time,0,touchX,touchY};
            struct wpe_input_touch_event event={&point,1,type,0,time,0};
            dispatchTouch(backend,&event);
            if(action==1||action==3)touchActive=false;
            if(action!=2)packet(QJsonObject{{"event","touch"},{"action",action},{"accepted",true}});
            return;
        }
        QVariant argument = object.toVariantMap();
        if (!QMetaObject::invokeMethod(root,"command",Q_ARG(QVariant,argument))) {
            packet(QJsonObject{{"event","error"},{"message","command dispatch unavailable"}});
        }
    }
    void readCommands() {
        char buffer[16384];
        for (;;) {
            ssize_t count = ::read(STDIN_FILENO,buffer,sizeof(buffer));
            if (count > 0) incoming.append(buffer,int(count));
            else if (count == 0) { QCoreApplication::quit(); return; }
            else if (errno == EINTR) continue;
            else if (errno == EAGAIN || errno == EWOULDBLOCK) break;
            else { QCoreApplication::exit(13); return; }
            if (incoming.size() > 4 * 1024 * 1024) { QCoreApplication::exit(14); return; }
        }
        for (;;) {
            if (incoming.size() < 4) return;
            const auto *p = reinterpret_cast<const unsigned char *>(incoming.constData());
            quint32 length = (quint32(p[0]) << 24) | (quint32(p[1]) << 16) | (quint32(p[2]) << 8) | p[3];
            if (length == 0 || length > 4 * 1024 * 1024 - 4) { QCoreApplication::exit(15); return; }
            if (incoming.size() < int(length)+4) return;
            QJsonParseError error;
            const auto doc = QJsonDocument::fromJson(incoming.mid(4,int(length)),&error);
            incoming.remove(0,int(length)+4);
            if (error.error != QJsonParseError::NoError || !doc.isObject()) { QCoreApplication::exit(16); return; }
            dispatch(doc.object());
        }
    }
    void schedule() {
        renderPending = true;
        if (initialized && active && !renderTimer.isActive()) renderTimer.start(16);
    }
    void render() {
        if (!initialized || !active) return;
        if (renderPending) {
            renderPending = false;
            context.makeCurrent(&surface);
            control.polishItems(); control.sync();
            // WPE texture import can temporarily switch the current surface.
            context.makeCurrent(&surface); fbo->bind(); control.render();
            context.functions()->glFlush();
            // RenderControl never swaps a visible window. Complete the embedder
            // handshake explicitly so WPE releases and acknowledges its images.
            QMetaObject::invokeMethod(&window,"frameSwapped",Qt::DirectConnection);
            ++renders; frameDirty = true;
        }
        if (frameDirty && !awaitingAck) {
            context.makeCurrent(&surface);
            QImage image = fbo->toImage().convertToFormat(QImage::Format_RGBA8888);
            if (image.isNull() || image.bytesPerLine() != width*4) { QCoreApplication::exit(17); return; }
            ++serial; ++sentFrames; awaitingAck = true; frameDirty = false;
            packet(QJsonObject{{"event","frame"},{"seq",double(serial)},{"width",width},{"height",height},
                   {"bytes",width*height*4},{"format","rgba8888"}},
                   QByteArray(reinterpret_cast<const char *>(image.constBits()),width*height*4));
            watchdog.start(15000); // A stalled/dead consumer cannot pin a renderer forever.
        }
    }
public:
    WebHost(int w, int h) : window(&control), input(STDIN_FILENO,QSocketNotifier::Read),
        output(STDOUT_FILENO,QSocketNotifier::Write), width(w), height(h) {
        lifetime.start();
        output.setEnabled(false);
        fcntl(STDIN_FILENO,F_SETFL,fcntl(STDIN_FILENO,F_GETFL)|O_NONBLOCK);
        fcntl(STDOUT_FILENO,F_SETFL,fcntl(STDOUT_FILENO,F_GETFL)|O_NONBLOCK);
        connect(&input,&QSocketNotifier::activated,this,[this](int){readCommands();});
        connect(&output,&QSocketNotifier::activated,this,[this](int){flush();});
        renderTimer.setSingleShot(true);
        connect(&renderTimer,&QTimer::timeout,this,[this]{render();});
        watchdog.setSingleShot(true);
        connect(&watchdog,&QTimer::timeout,this,[]{qCritical("SDWEBHOST=consumer_timeout");QCoreApplication::exit(18);});
        connect(&control,&QQuickRenderControl::renderRequested,this,[this]{schedule();});
        connect(&control,&QQuickRenderControl::sceneChanged,this,[this]{schedule();});
    }
    bool start(const QString &scene) {
        window.setGeometry(0,0,width,height);
        window.contentItem()->setSize(QSizeF(width,height));
        QSurfaceFormat format; format.setRenderableType(QSurfaceFormat::OpenGLES);format.setVersion(2,0);
        format.setDepthBufferSize(24);format.setStencilBufferSize(8);
        context.setFormat(format);
        if (!context.create()) return false;
        surface.setFormat(context.format());surface.create();
        if (!surface.isValid() || !context.makeCurrent(&surface)) return false;
        fbo.reset(new QOpenGLFramebufferObject(QSize(width,height),QOpenGLFramebufferObject::CombinedDepthStencil));
        if (!fbo->isValid()) return false;
        engine.rootContext()->setContextProperty("bridge",this);
        QQmlComponent component(&engine,QUrl::fromLocalFile(scene));
        if (component.isError()) {qCritical()<<component.errors();return false;}
        root=qobject_cast<QQuickItem *>(component.create());
        if (!root) {qCritical()<<component.errors();return false;}
        root->setParentItem(window.contentItem());root->setSize(QSizeF(width,height));
        control.initialize(&context);window.setRenderTarget(fbo.get());initialized=true;
        packet(QJsonObject{{"event","ready"},{"protocol",1},{"visible_windows",0}});
        schedule(); return true;
    }
    ~WebHost() override {
        renderTimer.stop();watchdog.stop();
        ime.reset();boundary.reset();context.makeCurrent(&surface);delete root;root=nullptr;control.invalidate();fbo.reset();
        qWarning("SDWEBHOST=closed|frames=%llu|renders=%llu|elapsed_ms=%lld",(unsigned long long)sentFrames,(unsigned long long)renders,(long long)lifetime.elapsed());
    }
public slots:
    void event(const QString &json) {
        const auto doc=QJsonDocument::fromJson(json.toUtf8());
        if (doc.isObject()) {
            if(boundary&&doc.object().value("event").toString()=="history"){boundary->history();return;}
            if(boundary&&doc.object().value("event").toString()=="load"&&doc.object().value("status").toInt()==2){boundary->loaded(doc.object());return;}
            if(boundary&&(doc.object().value("event").toString()=="title"||doc.object().value("event").toString()=="url"))boundary->history();
            packet(doc.object());
        }
    }
};

int main(int argc,char **argv) {
    signal(SIGPIPE,SIG_IGN);
    prctl(PR_SET_PDEATHSIG,SIGTERM);
    qInstallMessageHandler(logMessage);
    QGuiApplication app(argc,argv);
    if (argc != 4) return 2;
    bool okW=false,okH=false;int w=QString::fromLocal8Bit(argv[2]).toInt(&okW),h=QString::fromLocal8Bit(argv[3]).toInt(&okH);
    if (!okW||!okH||w<1||h<1||w>2160||h>4096||qint64(w)*h*4>maxFrameBytes) return 2;
    WebHost host(w,h);
    if (!host.start(QString::fromLocal8Bit(argv[1]))) return 3;
    return app.exec();
}
#include "sdwebviewd.moc"
