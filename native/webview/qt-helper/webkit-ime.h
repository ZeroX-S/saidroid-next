// Android InputConnection <-> public WPE WebKitInputMethodContext boundary.
// No script-based DOM value assignment or synthetic success callbacks.
#pragma once
#include <glib-object.h>
#include <QJsonObject>
#include <QString>
#include <functional>

// Public vfunc prefix from WPE WebKit 2.50 WebKitInputMethodContext.h.in.
// The complete class/instance allocation sizes are queried from its real GType;
// no private fields, reserved slots or instance layout are accessed.
// Public API declaration copyright: (C) 2012 Igalia S.L., LGPL-2.0-or-later.
struct SdImeClass {
    GObjectClass parent;
    void (*preedit_started)(void*);
    void (*preedit_changed)(void*);
    void (*preedit_finished)(void*);
    void (*committed)(void*,const char*);
    void (*delete_surrounding)(void*,int,guint);
    void (*set_enable_preedit)(void*,gboolean);
    void (*get_preedit)(void*,gchar**,GList**,guint*);
    gboolean (*filter_key_event)(void*,gpointer);
    void (*notify_focus_in)(void*);
    void (*notify_focus_out)(void*);
    void (*notify_cursor_area)(void*,int,int,int,int);
    void (*notify_surrounding)(void*,const gchar*,guint,guint,guint);
    void (*reset)(void*);
};

class WebIme {
    void *view=nullptr,*context=nullptr,*backend=nullptr;
    std::function<void(QJsonObject)> send;
    QString surrounding,preedit;
    int cursor=0,anchor=0,preeditCursor=0;
    int x=0,y=0,w=0,h=0;
    bool focused=false,enabled=true;
    unsigned epoch=0;
    static GQuark ownerKey(){static GQuark key=g_quark_from_static_string("saildroid-web-ime-owner");return key;}
    static WebIme *owner(void *c){return static_cast<WebIme*>(g_object_get_qdata(G_OBJECT(c),ownerKey()));}
    static void initializeClass(gpointer klass,gpointer){
        auto *c=static_cast<SdImeClass*>(klass);
        c->set_enable_preedit=+[](void *o,gboolean b){if(auto *s=owner(o))s->enabled=b;};
        c->get_preedit=+[](void *o,gchar **text,GList **underlines,guint *position){
            auto *s=owner(o);QByteArray bytes=s?s->preedit.toUtf8():QByteArray();
            if(text)*text=g_strdup(bytes.constData());
            if(underlines)*underlines=nullptr;
            if(position)*position=s?guint(s->preedit.left(s->preeditCursor).toUcs4().size()):0;
        };
        c->filter_key_event=+[](void*,gpointer)->gboolean{return FALSE;};
        c->notify_focus_in=+[](void *o){if(auto *s=owner(o)){s->focused=true;++s->epoch;s->surrounding.clear();s->cursor=s->anchor=0;s->report();}};
        c->notify_focus_out=+[](void *o){if(auto *s=owner(o)){s->focused=false;s->clearPreedit();s->surrounding.clear();s->cursor=s->anchor=0;s->report();}};
        c->notify_cursor_area=+[](void *o,int x,int y,int w,int h){if(auto *s=owner(o)){s->x=x;s->y=y;s->w=w;s->h=h;s->report();}};
        c->notify_surrounding=+[](void *o,const gchar *text,guint length,guint cursor,guint selection){
            if(auto *s=owner(o)){
                if(length>65536){s->surrounding.clear();s->cursor=s->anchor=0;}
                else{s->surrounding=QString::fromUtf8(text,int(length));s->cursor=QString::fromUtf8(text,int(qMin(cursor,length))).size();s->anchor=QString::fromUtf8(text,int(qMin(selection,length))).size();}
                s->report();
            }
        };
        c->reset=+[](void *o){if(auto *s=owner(o)){s->clearPreedit();s->report();}};
    }
    void report(){
        if(!context)return;
        auto purpose=SdWebApi::web<int(*)(void*)>("webkit_input_method_context_get_input_purpose");
        auto hints=SdWebApi::web<int(*)(void*)>("webkit_input_method_context_get_input_hints");
        send(QJsonObject{{"event","editor"},{"active",focused},{"epoch",int(epoch)},
            {"purpose",purpose?purpose(context):0},{"hints",hints?hints(context):0},
            {"text",surrounding},{"cursor",cursor},{"anchor",anchor},
            {"x",x},{"y",y},{"width",w},{"height",h}});
    }
    void clearPreedit(){
        if(preedit.isEmpty())return;
        preedit.clear();preeditCursor=0;
        g_signal_emit_by_name(context,"preedit-changed");g_signal_emit_by_name(context,"preedit-finished");
    }
    bool key(quint32 symbol,bool pressed,quint32 modifiers=0){
        auto dispatch=SdWebApi::web<void(*)(void*,const wpe_input_keyboard_event*)>("wpe_view_backend_dispatch_keyboard_event");
        // libwpe is distinct from WebKit; resolve the function from its owner.
        if(!dispatch)dispatch=reinterpret_cast<decltype(dispatch)>(QLibrary::resolve("/usr/lib64/libwpe-1.0.so.1","wpe_view_backend_dispatch_keyboard_event"));
        if(!dispatch||!backend)return false;
        wpe_input_keyboard_event event={0,symbol,0,pressed,modifiers};dispatch(backend,&event);return true;
    }
    void stroke(quint32 symbol,quint32 modifiers=0){key(symbol,true,modifiers);key(symbol,false,modifiers);}
public:
    WebIme(void *v,std::function<void(QJsonObject)> output):view(v),send(std::move(output)){}
    bool initialize(){
        auto type=SdWebApi::web<GType(*)()>("webkit_input_method_context_get_type");
        auto set=SdWebApi::web<void(*)(void*,void*)>("webkit_web_view_set_input_method_context");
        auto viewBackend=SdWebApi::web<void*(*)(void*)>("webkit_web_view_get_backend");
        auto wpeBackend=SdWebApi::web<void*(*)(void*)>("webkit_web_view_backend_get_wpe_backend");
        if(!type||!set||!viewBackend||!wpeBackend)return false;
        GType base=type();GTypeQuery query;g_type_query(base,&query);
        if(query.class_size<sizeof(SdImeClass)||query.class_size>65535||query.instance_size>65535)return false;
        static GType derived=0;
        if(!derived){GTypeInfo info={guint16(query.class_size),nullptr,nullptr,initializeClass,nullptr,nullptr,guint16(query.instance_size),0,nullptr,nullptr};derived=g_type_register_static(base,"SailDroidWebInputMethodContext",&info,GTypeFlags(0));}
        if(!derived)return false;
        context=g_object_new(derived,nullptr);g_object_set_qdata(G_OBJECT(context),ownerKey(),this);
        void *b=viewBackend(view);backend=b?wpeBackend(b):nullptr;if(!backend)return false;
        set(view,context);
        g_signal_connect(context,"notify::input-purpose",G_CALLBACK(+[](GObject*,GParamSpec*,gpointer data){static_cast<WebIme*>(data)->report();}),this);
        g_signal_connect(context,"notify::input-hints",G_CALLBACK(+[](GObject*,GParamSpec*,gpointer data){static_cast<WebIme*>(data)->report();}),this);
        return true;
    }
    bool command(const QJsonObject &o){
        QString op=o.value("op").toString();if(!op.startsWith("ime_"))return false;
        if(!context||!focused||o.value("epoch").toInt()!=int(epoch)){send(QJsonObject{{"event","ime_ack"},{"accepted",false}});return true;}
        if(op=="ime_commit"){
            QString text=o.value("text").toString();clearPreedit();QByteArray bytes=text.toUtf8();g_signal_emit_by_name(context,"committed",bytes.constData());
        }else if(op=="ime_preedit"){
            QString text=o.value("text").toString();bool started=preedit.isEmpty()&&!text.isEmpty();bool ended=!preedit.isEmpty()&&text.isEmpty();
            preedit=text;preeditCursor=qBound(0,o.value("cursor").toInt(text.size()),text.size());
            if(started)g_signal_emit_by_name(context,"preedit-started");
            g_signal_emit_by_name(context,"preedit-changed");
            if(ended)g_signal_emit_by_name(context,"preedit-finished");
        }else if(op=="ime_finish"){
            QString value=preedit;clearPreedit();if(!value.isEmpty()){QByteArray bytes=value.toUtf8();g_signal_emit_by_name(context,"committed",bytes.constData());}
        }else if(op=="ime_delete"){
            int before=qBound(0,o.value("before").toInt(),16384),after=qBound(0,o.value("after").toInt(),16384);
            int from=qMax(0,cursor-before),to=qMin(surrounding.size(),cursor+after);
            int beforeChars=surrounding.mid(from,cursor-from).toUcs4().size(),afterChars=surrounding.mid(cursor,to-cursor).toUcs4().size();
            g_signal_emit_by_name(context,"delete-surrounding",-beforeChars,guint(beforeChars+afterChars));
        }else if(op=="ime_select"){
            int a=o.value("start").toInt(),b=o.value("end").toInt();
            if(a<0||b<0||a>surrounding.size()||b>surrounding.size()||surrounding.size()>8192){send(QJsonObject{{"event","ime_ack"},{"accepted",false}});return true;}
            if(a!=cursor||b!=anchor){
                stroke(0xff50,wpe_input_keyboard_modifier_control);
                int start=surrounding.left(a).toUcs4().size(),end=surrounding.left(b).toUcs4().size();
                for(int i=0;i<start;i++)stroke(0xff53);
                for(int i=start;i<end;i++)stroke(0xff53,wpe_input_keyboard_modifier_shift);
                for(int i=start;i>end;i--)stroke(0xff51,wpe_input_keyboard_modifier_shift);
            }
        }else if(op=="ime_key"){
            int code=o.value("code").toInt();quint32 symbol=code==67?0xff08:code==112?0xffff:code==66?0xff0d:code==61?0xff09:code==21?0xff51:code==22?0xff53:code==19?0xff52:code==20?0xff54:0;
            if(!symbol){quint32 cp=quint32(o.value("unicode").toInt());symbol=cp<=0xff?cp:0x01000000|cp;}
            int android=o.value("modifiers").toInt();quint32 mods=0;
            if(android&0x1000)mods|=wpe_input_keyboard_modifier_control;
            if(android&1)mods|=wpe_input_keyboard_modifier_shift;
            if(android&2)mods|=wpe_input_keyboard_modifier_alt;
            if(android&0x10000)mods|=wpe_input_keyboard_modifier_meta;
            if(symbol)key(symbol,o.value("down").toBool(),mods);
        }else{send(QJsonObject{{"event","ime_ack"},{"accepted",false}});return true;}
        send(QJsonObject{{"event","ime_ack"},{"accepted",true}});return true;
    }
    ~WebIme(){
        if(context){auto set=SdWebApi::web<void(*)(void*,void*)>("webkit_web_view_set_input_method_context");if(set)set(view,nullptr);g_signal_handlers_disconnect_by_data(context,this);g_object_set_qdata(G_OBJECT(context),ownerKey(),nullptr);g_object_unref(context);}
    }
};
