// Public opaque WebKit/GLib/libsoup C APIs. Qt and ART objects never cross ABI.
#pragma once
#include <QHash>
#include <QPointer>
#include <QJsonArray>
#include <QDateTime>
#include <functional>

namespace SdWebApi {
template<class T> T web(const char *name){return reinterpret_cast<T>(QLibrary::resolve("/usr/lib64/libWPEWebKit-2.0.so.1",name));}
template<class T> T glib(const char *name){return reinterpret_cast<T>(QLibrary::resolve("/usr/lib64/libglib-2.0.so.0",name));}
template<class T> T object(const char *name){return reinterpret_cast<T>(QLibrary::resolve("/usr/lib64/libgobject-2.0.so.0",name));}
template<class T> T soup(const char *name){return reinterpret_cast<T>(QLibrary::resolve("libsoup-3.0.so.0",name));}
struct List {void *data;List *next,*previous;};
using Async=void(*)(void*,void*,void*);
}
class WebBoundary : public QObject {
    using Emit=std::function<void(QJsonObject)>;
    using Load=std::function<void(QJsonObject)>;
    void *view=nullptr,*content=nullptr,*cookieManager=nullptr,*script=nullptr;
    Emit send;Load load;
    quint64 sequence=0;long long cookieVersion=0;int cookieWrites=0;
    QHash<quint64,void*> policies,dialogs;
    QHash<quint64,QString> popups;
    QHash<void*,int> historyIds;int nextHistoryId=1;
    QJsonObject delayedLoad;
    QString programmatic;
    bool snapshotPending=false,snapshotAgain=false;
    QList<QJsonObject> finishedLoads;
    template<class F> bool connectSignal(void *object,const char *name,F function){
        using Connect=unsigned long(*)(void*,const char*,void(*)(),void*,void*,int);
        auto connect=SdWebApi::object<Connect>("g_signal_connect_data");
        return connect&&connect(object,name,reinterpret_cast<void(*)()>(function),this,nullptr,0)!=0;
    }
    void freeError(void *error){auto free=SdWebApi::glib<void(*)(void*)>("g_error_free");if(error&&free)free(error);}
    void releasePolicy(quint64 id,bool handled){
        void *decision=policies.take(id);if(!decision)return;
        auto action=SdWebApi::web<void(*)(void*)>(handled?"webkit_policy_decision_ignore":"webkit_policy_decision_use");
        auto unref=SdWebApi::object<void(*)(void*)>("g_object_unref");
        if(action)action(decision);
        if(unref)unref(decision);
    }
    void releaseDialog(quint64 id,const QJsonObject &answer){
        void *dialog=dialogs.take(id);if(!dialog)return;
        auto type=SdWebApi::web<int(*)(void*)>("webkit_script_dialog_get_dialog_type");
        auto setText=SdWebApi::web<void(*)(void*,const char*)>("webkit_script_dialog_prompt_set_text");
        auto confirm=SdWebApi::web<void(*)(void*,int)>("webkit_script_dialog_confirm_set_confirmed");
        auto close=SdWebApi::web<void(*)(void*)>("webkit_script_dialog_close");
        auto unref=SdWebApi::web<void(*)(void*)>("webkit_script_dialog_unref");
        if(type&&type(dialog)==2&&answer.value("confirmed").toBool()&&setText){QByteArray text=answer.value("text").toString().toUtf8();setText(dialog,text.constData());}
        else if(confirm&&type&&type(dialog)!=0&&type(dialog)!=2)confirm(dialog,answer.value("confirmed").toBool());
        if(close)close(dialog);
        if(unref)unref(dialog);
    }
    bool policy(void *decision,int type){
        if(type!=0&&type!=1)return false;
        auto getAction=SdWebApi::web<void*(*)(void*)>("webkit_navigation_policy_decision_get_navigation_action");
        auto getRequest=SdWebApi::web<void*(*)(void*)>("webkit_navigation_action_get_request");
        auto getUri=SdWebApi::web<const char*(*)(void*)>("webkit_uri_request_get_uri");
        auto getMethod=SdWebApi::web<const char*(*)(void*)>("webkit_uri_request_get_http_method");
        auto gesture=SdWebApi::web<int(*)(void*)>("webkit_navigation_action_is_user_gesture");
        auto redirect=SdWebApi::web<int(*)(void*)>("webkit_navigation_action_is_redirect");
        auto frameName=SdWebApi::web<const char*(*)(void*)>("webkit_navigation_action_get_frame_name");
        auto ref=SdWebApi::object<void*(*)(void*)>("g_object_ref");
        if(!getAction||!getRequest||!getUri||!ref)return false;
        void *action=getAction(decision),*request=action?getRequest(action):nullptr;if(!request)return false;
        QString url=QString::fromUtf8(getUri(request));const char *rawMethod=getMethod?getMethod(request):nullptr;QString method=rawMethod?QString::fromUtf8(rawMethod):"GET";
        if(url==programmatic&&type==0){programmatic.clear();return false;}
        // Android does not run shouldOverrideUrlLoading for application loadUrl
        // or POST form submissions. WebKit retains its native POST request.
        if(method!="GET"||url=="about:blank")return false;
        const quint64 id=++sequence;policies.insert(id,ref(decision));
        const char *frame=frameName?frameName(action):nullptr;
        send(QJsonObject{{"event","navigation"},{"id",double(id)},{"url",url},{"method",method},
            {"gesture",bool(gesture&&gesture(action))},{"redirect",bool(redirect&&redirect(action))},
            {"mainFrame",!frame||!*frame},{"newWindow",type==1}});
        QTimer::singleShot(8000,this,[this,id]{if(policies.contains(id)){releasePolicy(id,true);send(QJsonObject{{"event","navigation_timeout"}});}});
        return true;
    }
    void popup(void *action){
        auto request=SdWebApi::web<void*(*)(void*)>("webkit_navigation_action_get_request");
        auto uri=SdWebApi::web<const char*(*)(void*)>("webkit_uri_request_get_uri");
        auto gesture=SdWebApi::web<int(*)(void*)>("webkit_navigation_action_is_user_gesture");
        void *r=request?request(action):nullptr;if(!r||!uri)return;
        QString url=QString::fromUtf8(uri(r));quint64 id=++sequence;popups.insert(id,url);
        send(QJsonObject{{"event","navigation"},{"id",double(id)},{"url",url},{"method","GET"},{"gesture",bool(gesture&&gesture(action))},{"redirect",false},{"mainFrame",true},{"newWindow",true}});
        QTimer::singleShot(8000,this,[this,id]{popups.remove(id);});
    }
    bool dialog(void *object){
        auto type=SdWebApi::web<int(*)(void*)>("webkit_script_dialog_get_dialog_type");
        auto message=SdWebApi::web<const char*(*)(void*)>("webkit_script_dialog_get_message");
        auto defaultText=SdWebApi::web<const char*(*)(void*)>("webkit_script_dialog_prompt_get_default_text");
        auto ref=SdWebApi::web<void*(*)(void*)>("webkit_script_dialog_ref");
        auto uri=SdWebApi::web<const char*(*)(void*)>("webkit_web_view_get_uri");
        if(!type||!message||!ref)return false;
        const int kind=type(object);QString text=QString::fromUtf8(message(object));
        const quint64 id=++sequence;dialogs.insert(id,ref(object));
        const QString initial=kind==2&&defaultText?QString::fromUtf8(defaultText(object)):QString();
        if(kind==2&&text=="__SAILDROID_NATIVE_BRIDGE_V1__"){
            const auto doc=QJsonDocument::fromJson(initial.toUtf8());
            if(initial.size()>1024*1024||!doc.isObject()){releaseDialog(id,QJsonObject());return true;}
            send(QJsonObject{{"event","js_interface"},{"id",double(id)},{"request",doc.object()}});
        }else send(QJsonObject{{"event","js_dialog"},{"id",double(id)},{"kind",kind},{"message",text},{"default",initial},{"url",uri?QString::fromUtf8(uri(view)):QString()}});
        QTimer::singleShot(8000,this,[this,id]{if(dialogs.contains(id)){releaseDialog(id,QJsonObject());send(QJsonObject{{"event","script_callback_timeout"}});}});
        return true;
    }
    void scripts(const QJsonObject &interfaces){
        auto create=SdWebApi::web<void*(*)(const char*,int,int,const char*const*,const char*const*)>("webkit_user_script_new");
        auto add=SdWebApi::web<void(*)(void*,void*)>("webkit_user_content_manager_add_script");
        auto remove=SdWebApi::web<void(*)(void*,void*)>("webkit_user_content_manager_remove_script");
        auto unref=SdWebApi::web<void(*)(void*)>("webkit_user_script_unref");
        if(!content||!create||!add||!remove||!unref){send(QJsonObject{{"event","error"},{"message","Java interface injection ABI unavailable"}});return;}
        if(script){remove(content,script);unref(script);script=nullptr;}
        QByteArray source="(function(){'use strict';const nativePrompt=window.prompt.bind(window);const interfaces=";
        source+=QJsonDocument(interfaces).toJson(QJsonDocument::Compact);
        source+=";Object.keys(interfaces).forEach(function(name){const object={};interfaces[name].forEach(function(method){object[method]=function(){const raw=nativePrompt('__SAILDROID_NATIVE_BRIDGE_V1__',JSON.stringify({name:name,method:method,args:Array.prototype.slice.call(arguments)}));if(raw===null)throw new Error('Native bridge cancelled');const result=JSON.parse(raw);if(!result.ok)throw new Error(result.error||'Native bridge failed');return result.undefined?undefined:result.value;};});Object.defineProperty(window,name,{value:Object.freeze(object),configurable:true});});})();";
        script=create(source.constData(),0,0,nullptr,nullptr);if(script)add(content,script);
    }
    void drainCookies(){
        if(cookieWrites)return;
        snapshot();
        if(!delayedLoad.isEmpty()){QJsonObject next=delayedLoad;delayedLoad=QJsonObject();programmatic=next.value("url").toString();if(!command(next))load(next);}
    }
    void cookieFinished(void *result,bool replacing){
        auto finish=SdWebApi::web<int(*)(void*,void*,void**)>(replacing?"webkit_cookie_manager_replace_cookies_finish":"webkit_cookie_manager_add_cookie_finish");
        void *error=nullptr;bool success=finish&&finish(cookieManager,result,&error);freeError(error);
        if(!success)send(QJsonObject{{"event","cookie_error"},{"message","Cookie operation rejected by WebKit"}});
        if(cookieWrites>0)--cookieWrites;
        drainCookies();
    }
    void setCookie(const QJsonObject &cookie){
        auto create=SdWebApi::soup<void*(*)(const char*,const char*,const char*,const char*,int)>("soup_cookie_new");
        auto secure=SdWebApi::soup<void(*)(void*,int)>("soup_cookie_set_secure");
        auto http=SdWebApi::soup<void(*)(void*,int)>("soup_cookie_set_http_only");
        auto add=SdWebApi::web<void(*)(void*,void*,void*,SdWebApi::Async,void*)>("webkit_cookie_manager_add_cookie");
        auto free=SdWebApi::soup<void(*)(void*)>("soup_cookie_free");
        if(!create||!secure||!http||!add||!free||!cookieManager)return;
        const QByteArray name=cookie.value("name").toString().toUtf8(),value=cookie.value("value").toString().toUtf8(),domain=cookie.value("domain").toString().toUtf8(),path=cookie.value("path").toString().toUtf8();
        qint64 expires=qint64(cookie.value("expires").toDouble());
        int age=cookie.value("session").toBool(expires==0)?-1:int(qBound<qint64>(0,expires-QDateTime::currentMSecsSinceEpoch()/1000,2147483647));
        void *item=create(name.constData(),value.constData(),domain.constData(),path.constData(),age);if(!item)return;
        secure(item,cookie.value("secure").toBool());http(item,cookie.value("httpOnly").toBool());++cookieWrites;
        auto *owner=new QPointer<WebBoundary>(this);
        add(cookieManager,item,nullptr,+[](void*,void *result,void *data){std::unique_ptr<QPointer<WebBoundary>> owner(static_cast<QPointer<WebBoundary>*>(data));if(*owner)(*owner)->cookieFinished(result,false);},owner);free(item);
    }
    void clearCookies(bool sessions){
        auto get=SdWebApi::web<void(*)(void*,void*,SdWebApi::Async,void*)>("webkit_cookie_manager_get_all_cookies");
        if(!get)return;
        ++cookieWrites;
        struct Clear {QPointer<WebBoundary> owner;bool sessions;};auto *call=new Clear{this,sessions};
        get(cookieManager,nullptr,+[](void *manager,void *result,void *data){
            std::unique_ptr<Clear> call(static_cast<Clear*>(data));if(!call->owner)return;WebBoundary *self=call->owner;
            auto finish=SdWebApi::web<SdWebApi::List*(*)(void*,void*,void**)>("webkit_cookie_manager_get_all_cookies_finish");
            auto expires=SdWebApi::soup<void*(*)(void*)>("soup_cookie_get_expires");
            auto append=SdWebApi::glib<SdWebApi::List*(*)(SdWebApi::List*,void*)>("g_list_append");
            auto freeList=SdWebApi::glib<void(*)(SdWebApi::List*)>("g_list_free");
            auto freeCookie=SdWebApi::soup<void(*)(void*)>("soup_cookie_free");
            auto replace=SdWebApi::web<void(*)(void*,SdWebApi::List*,void*,SdWebApi::Async,void*)>("webkit_cookie_manager_replace_cookies");
            void *error=nullptr;SdWebApi::List *list=finish?finish(manager,result,&error):nullptr,*keep=nullptr;
            self->freeError(error);
            if(call->sessions&&expires&&append)for(auto *p=list;p;p=p->next)if(expires(p->data))keep=append(keep,p->data);
            if(replace){auto *owner=new QPointer<WebBoundary>(self);replace(manager,keep,nullptr,+[](void*,void *r,void *d){std::unique_ptr<QPointer<WebBoundary>> owner(static_cast<QPointer<WebBoundary>*>(d));if(*owner)(*owner)->cookieFinished(r,true);},owner);}
            else{if(self->cookieWrites>0)--self->cookieWrites;self->drainCookies();}
            if(freeList)freeList(keep);
            for(auto *p=list;p;p=p->next)if(freeCookie)freeCookie(p->data);
            if(freeList)freeList(list);
        },call);
    }
    void snapshot(){
        if(!cookieManager)return;
        if(cookieWrites||snapshotPending){snapshotAgain=true;return;}
        snapshotAgain=false;
        auto get=SdWebApi::web<void(*)(void*,void*,SdWebApi::Async,void*)>("webkit_cookie_manager_get_all_cookies");if(!get)return;
        snapshotPending=true;
        struct Read {QPointer<WebBoundary> owner;long long version;};auto *call=new Read{this,cookieVersion};
        get(cookieManager,nullptr,+[](void *manager,void *result,void *data){
            std::unique_ptr<Read> call(static_cast<Read*>(data));if(!call->owner)return;WebBoundary *self=call->owner;self->snapshotPending=false;
            auto finish=SdWebApi::web<SdWebApi::List*(*)(void*,void*,void**)>("webkit_cookie_manager_get_all_cookies_finish");
            auto name=SdWebApi::soup<const char*(*)(void*)>("soup_cookie_get_name"),value=SdWebApi::soup<const char*(*)(void*)>("soup_cookie_get_value"),domain=SdWebApi::soup<const char*(*)(void*)>("soup_cookie_get_domain"),path=SdWebApi::soup<const char*(*)(void*)>("soup_cookie_get_path");
            auto secure=SdWebApi::soup<int(*)(void*)>("soup_cookie_get_secure"),http=SdWebApi::soup<int(*)(void*)>("soup_cookie_get_http_only");
            auto expires=SdWebApi::soup<void*(*)(void*)>("soup_cookie_get_expires");auto unixTime=SdWebApi::glib<qint64(*)(void*)>("g_date_time_to_unix");
            auto freeCookie=SdWebApi::soup<void(*)(void*)>("soup_cookie_free");auto freeList=SdWebApi::glib<void(*)(SdWebApi::List*)>("g_list_free");
            void *error=nullptr;auto *list=finish?finish(manager,result,&error):nullptr;QJsonArray entries;
            if(!error&&name&&value&&domain&&path&&secure&&http&&expires&&unixTime){
                for(auto *p=list;p;p=p->next){void *c=p->data,*expiry=expires(c);entries.append(QJsonObject{{"name",QString::fromUtf8(name(c))},{"value",QString::fromUtf8(value(c))},{"domain",QString::fromUtf8(domain(c))},{"path",QString::fromUtf8(path(c))},{"secure",bool(secure(c))},{"httpOnly",bool(http(c))},{"expires",expiry?double(unixTime(expiry)):0.0},{"session",!expiry}});}
                self->send(QJsonObject{{"event","cookies"},{"version",double(call->version)},{"entries",entries}});
            }
            self->freeError(error);for(auto *p=list;p;p=p->next)if(freeCookie)freeCookie(p->data);if(freeList)freeList(list);
            auto finished=self->finishedLoads;self->finishedLoads.clear();for(auto event:finished)self->send(event);
            if(self->snapshotAgain)QTimer::singleShot(0,self,[self]{self->snapshot();});
        },call);
    }
public:
    WebBoundary(void *webView,Emit callback,Load navigate,QObject *parent):QObject(parent),view(webView),send(callback),load(navigate){}
    bool initialize(){
        auto manager=SdWebApi::web<void*(*)(void*)>("webkit_web_view_get_user_content_manager");
        auto context=SdWebApi::web<void*(*)(void*)>("webkit_web_view_get_context");
        auto cookies=SdWebApi::web<void*(*)(void*)>("webkit_web_context_get_cookie_manager");
        auto session=SdWebApi::web<void*(*)(void*)>("webkit_web_view_get_network_session");
        auto sessionCookies=SdWebApi::web<void*(*)(void*)>("webkit_network_session_get_cookie_manager");
        auto persistent=SdWebApi::web<void(*)(void*,const char*,int)>("webkit_cookie_manager_set_persistent_storage");
        if(!manager||!persistent)return false;
        content=manager(view);cookieManager=session&&sessionCookies?sessionCookies(session(view)):context&&cookies?cookies(context(view)):nullptr;
        if(!content||!cookieManager)return false;
        QByteArray file=(QString::fromLocal8Bit(qgetenv("HOME"))+"/cookies.sqlite").toUtf8();persistent(cookieManager,file.constData(),1);
        bool ok=connectSignal(view,"decide-policy",+[](void*,void *decision,int type,void *data)->int{return static_cast<WebBoundary*>(data)->policy(decision,type);});
        ok=connectSignal(view,"create",+[](void*,void *action,void *data)->void*{static_cast<WebBoundary*>(data)->popup(action);return nullptr;})&&ok;
        ok=connectSignal(view,"script-dialog",+[](void*,void *dialog,void *data)->int{return static_cast<WebBoundary*>(data)->dialog(dialog);})&&ok;
        ok=connectSignal(view,"load-changed",+[](void*,int state,void *data){auto *self=static_cast<WebBoundary*>(data);if(state==2)self->send(QJsonObject{{"event","document_committed"}});})&&ok;
        ok=connectSignal(cookieManager,"changed",+[](void*,void *data){auto *self=static_cast<WebBoundary*>(data);QTimer::singleShot(0,self,[self]{self->snapshot();});})&&ok;
        return ok;
    }
    void history(){
        auto listFor=SdWebApi::web<void*(*)(void*)>("webkit_web_view_get_back_forward_list");
        auto length=SdWebApi::web<unsigned(*)(void*)>("webkit_back_forward_list_get_length");
        auto back=SdWebApi::web<SdWebApi::List*(*)(void*,unsigned)>("webkit_back_forward_list_get_back_list_with_limit");
        auto nth=SdWebApi::web<void*(*)(void*,int)>("webkit_back_forward_list_get_nth_item");
        auto uri=SdWebApi::web<const char*(*)(void*)>("webkit_back_forward_list_item_get_uri");
        auto original=SdWebApi::web<const char*(*)(void*)>("webkit_back_forward_list_item_get_original_uri");
        auto title=SdWebApi::web<const char*(*)(void*)>("webkit_back_forward_list_item_get_title");
        auto freeList=SdWebApi::glib<void(*)(SdWebApi::List*)>("g_list_free");
        if(!listFor||!length||!back||!nth||!uri||!original||!title||!freeList){send(QJsonObject{{"event","error"},{"message","WebKit history ABI unavailable"}});return;}
        void *list=listFor(view);unsigned size=length(list);if(size>10000){send(QJsonObject{{"event","error"},{"message","WebKit history exceeds transport bound"}});return;}
        int index=0;auto *prior=back(list,size);for(auto *entry=prior;entry;entry=entry->next)index++;freeList(prior);
        auto ref=SdWebApi::object<void*(*)(void*)>("g_object_ref");if(!ref)return;
        QJsonArray items;for(unsigned i=0;i<size;i++){void *item=nth(list,int(i)-index);if(!item)return;if(!historyIds.contains(item)){historyIds.insert(ref(item),nextHistoryId++);}const char *u=uri(item),*o=original(item),*t=title(item);items.append(QJsonObject{{"id",historyIds.value(item)},{"url",QString::fromUtf8(u?u:"")},{"original",QString::fromUtf8(o?o:"")},{"title",QString::fromUtf8(t?t:"")}});}
        send(QJsonObject{{"event","history"},{"index",size?index:-1},{"items",items},{"back",index>0},{"forward",index+1<int(size)}});
    }
    void loaded(const QJsonObject &event){history();finishedLoads.append(event);snapshot();}
    bool command(const QJsonObject &object){
        QString op=object.value("op").toString();
        if(op=="history_go"){
            auto listFor=SdWebApi::web<void*(*)(void*)>("webkit_web_view_get_back_forward_list");auto nth=SdWebApi::web<void*(*)(void*,int)>("webkit_back_forward_list_get_nth_item");auto go=SdWebApi::web<void(*)(void*,void*)>("webkit_web_view_go_to_back_forward_list_item");
            if(!listFor||!nth||!go){send(QJsonObject{{"event","error"},{"message","WebKit history navigation ABI unavailable"}});return true;}void *item=nth(listFor(view),object.value("steps").toInt());if(item)go(view,item);return true;
        }
        if(op=="interfaces"){scripts(object.value("interfaces").toObject());return true;}
        if(op=="js_interface_reply"||op=="js_dialog_reply"){releaseDialog(quint64(object.value("id").toDouble()),object);return true;}
        if(op=="navigation_reply"){
            const quint64 id=quint64(object.value("id").toDouble());bool handled=object.value("handled").toBool();
            if(popups.contains(id)){
                QString url=popups.take(id);if(!handled){QJsonObject next{{"op","load"},{"url",url}};if(!command(next))load(next);}return true;
            }
            if(object.value("newWindow").toBool()&&!handled){releasePolicy(id,true);QJsonObject next{{"op","load"},{"url",object.value("url")}};programmatic=object.value("url").toString();load(next);}
            else releasePolicy(id,handled);
            return true;
        }
        if(op=="cookies_sync"){
            cookieVersion=qMax(cookieVersion,qint64(object.value("version").toDouble()));
            const auto entries=object.value("entries").toArray();for(auto c:entries)setCookie(c.toObject());
            if(!cookieWrites)snapshot();
            return true;
        }
        if(op=="cookie_set"){cookieVersion=qMax(cookieVersion,qint64(object.value("version").toDouble()));setCookie(object.value("cookie").toObject());return true;}
        if(op=="cookies_clear"){cookieVersion=qMax(cookieVersion,qint64(object.value("version").toDouble()));clearCookies(object.value("sessions").toBool());return true;}
        if(op=="load"||op=="post"){
            if(cookieWrites){delayedLoad=object;return true;}
            programmatic=object.value("url").toString();
            if(op=="load"&&!object.value("headers").toObject().isEmpty()){
                auto requestNew=SdWebApi::web<void*(*)(const char*)>("webkit_uri_request_new");
                auto headers=SdWebApi::web<void*(*)(void*)>("webkit_uri_request_get_http_headers");
                auto replace=SdWebApi::soup<void(*)(void*,const char*,const char*)>("soup_message_headers_replace");
                auto loadRequest=SdWebApi::web<void(*)(void*,void*)>("webkit_web_view_load_request");
                auto unref=SdWebApi::object<void(*)(void*)>("g_object_unref");
                if(!requestNew||!headers||!replace||!loadRequest||!unref)return false;
                QByteArray url=programmatic.toUtf8();void *request=requestNew(url.constData());void *h=headers(request);
                QJsonObject values=object.value("headers").toObject();
                for(auto i=values.begin();i!=values.end();++i){QByteArray key=i.key().toUtf8(),value=i.value().toString().toUtf8();if(!key.contains('\r')&&!key.contains('\n')&&!value.contains('\r')&&!value.contains('\n'))replace(h,key.constData(),value.constData());}
                loadRequest(view,request);unref(request);return true;
            }
        }
        return false;
    }
    ~WebBoundary(){
        auto release=SdWebApi::object<void(*)(void*)>("g_object_unref");if(release)for(auto *item:historyIds.keys())release(item);
        auto disconnect=SdWebApi::object<unsigned(*)(void*,unsigned,unsigned,void*,void*,void*)>("g_signal_handlers_disconnect_matched");
        if(disconnect){disconnect(view,16,0,nullptr,nullptr,this);disconnect(cookieManager,16,0,nullptr,nullptr,this);}
        for(auto id:policies.keys())releasePolicy(id,true);
        for(auto id:dialogs.keys())releaseDialog(id,QJsonObject());
        auto remove=SdWebApi::web<void(*)(void*,void*)>("webkit_user_content_manager_remove_script");auto unref=SdWebApi::web<void(*)(void*)>("webkit_user_script_unref");if(script&&remove&&unref){remove(content,script);unref(script);}
    }
};
