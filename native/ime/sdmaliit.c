#include <jni.h>
#include <gio/gio.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "maliit-client-xml.h"
static JavaVM *vm;
static jclass client_class;
static jmethodID event_method;
static pthread_mutex_t state_lock=PTHREAD_MUTEX_INITIALIZER;
static GMainContext *context;
static GMainLoop *loop;
static GDBusConnection *connection;
static int started,pending_resets;
static gint64 generation;
static gchar *surrounding;
static gint cursor,anchor;
static JNIEnv *worker_env;
static void emit(int type,const char *text,int a,int b,int c,int d){
    jstring value=NULL;
    if(text){glong length;gunichar2 *utf16=g_utf8_to_utf16(text,-1,NULL,&length,NULL);if(!utf16)return;value=(*worker_env)->NewString(worker_env,(jchar*)utf16,(jsize)length);g_free(utf16);}
    (*worker_env)->CallStaticVoidMethod(worker_env,client_class,event_method,(jlong)generation,(jint)type,value,a,b,c,d);
    if(value)(*worker_env)->DeleteLocalRef(worker_env,value);
    if((*worker_env)->ExceptionCheck(worker_env)){(*worker_env)->ExceptionDescribe(worker_env);(*worker_env)->ExceptionClear(worker_env);}
}
static void method_call(GDBusConnection *c,const gchar *sender,const gchar *path,const gchar *iface,const gchar *name,GVariant *args,GDBusMethodInvocation *reply,gpointer data){
    (void)c;(void)sender;(void)path;(void)iface;(void)data;
    if(!strcmp(name,"commitString")){const gchar *text;gint start,length,position;g_variant_get(args,"(&siii)",&text,&start,&length,&position);if(!pending_resets)emit(1,text,start,length,position,0);}
    else if(!strcmp(name,"updatePreedit")){const gchar *text;GVariant *formats;gint start,length,position;g_variant_get(args,"(&s@a(iii)iii)",&text,&formats,&start,&length,&position);if(!pending_resets)emit(2,text,start,length,position,0);g_variant_unref(formats);}
    else if(!strcmp(name,"keyEvent")){gint type,key,modifiers,count;const gchar *text;gboolean repeat;guchar request;g_variant_get(args,"(iii&sbiy)",&type,&key,&modifiers,&text,&repeat,&count,&request);if(!pending_resets&&request!=1)emit(3,text,type,key,modifiers,count);}
    else if(!strcmp(name,"updateInputMethodArea")){gint x,y,w,h;g_variant_get(args,"(iiii)",&x,&y,&w,&h);emit(4,NULL,x,y,w,h);}
    else if(!strcmp(name,"activationLostEvent"))emit(5,NULL,0,0,0,0);
    else if(!strcmp(name,"imInitiatedHide"))emit(6,NULL,0,0,0,0);
    else if(!strcmp(name,"setSelection")){gint start,length;g_variant_get(args,"(ii)",&start,&length);emit(7,NULL,start,length,0,0);}
    else if(!strcmp(name,"setLanguage")){const gchar *language;g_variant_get(args,"(&s)",&language);emit(8,language,0,0,0,0);}
    else if(!strcmp(name,"selection")){
        gboolean valid=FALSE;gchar *selected=NULL;
        if(surrounding&&cursor!=anchor){glong length;gunichar2 *wide=g_utf8_to_utf16(surrounding,-1,NULL,&length,NULL);gint begin=MIN(cursor,anchor),end=MAX(cursor,anchor);if(wide&&begin>=0&&end<=length){selected=g_utf16_to_utf8(wide+begin,end-begin,NULL,NULL,NULL);valid=selected!=NULL;}g_free(wide);}
        g_dbus_method_invocation_return_value(reply,g_variant_new("(bs)",valid,selected?selected:""));g_free(selected);return;
    }else if(!strcmp(name,"preeditRectangle")){g_dbus_method_invocation_return_value(reply,g_variant_new("(biiii)",FALSE,0,0,0,0));return;}
    else if(!strcmp(name,"setGlobalCorrectionEnabled")){gboolean enabled;g_variant_get(args,"(b)",&enabled);emit(9,NULL,enabled,0,0,0);}
    else {g_dbus_method_invocation_return_error(reply,G_DBUS_ERROR,G_DBUS_ERROR_NOT_SUPPORTED,"SailDroid input context does not implement %s",name);return;}
    g_dbus_method_invocation_return_value(reply,NULL);
}
static const GDBusInterfaceVTable vtable={.method_call=method_call};
static void call_finished(GObject *object,GAsyncResult *result,gpointer data){
    const char *method=data;GError *error=NULL;GVariant *reply=g_dbus_connection_call_finish(G_DBUS_CONNECTION(object),result,&error);
    if(!strcmp(method,"reset")&&pending_resets>0)pending_resets--;
    if(error){fprintf(stderr,"SDIME=peer_call_failed|method=%s|code=%d\n",method,error->code);g_error_free(error);}if(reply)g_variant_unref(reply);
}
static void call(const char *method,GVariant *args){
    if(!connection||g_dbus_connection_is_closed(connection))return;
    g_dbus_connection_call(connection,NULL,"/com/meego/inputmethod/uiserver1","com.meego.inputmethod.uiserver1",method,args,NULL,G_DBUS_CALL_FLAGS_NONE,2000,NULL,call_finished,(gpointer)method);
}
struct job {const char *method;GVariant *args;gint64 generation;gboolean widget,changed,focus;gchar *text;gint cursor,anchor;};
static void free_job(gpointer data){struct job *job=data;g_variant_unref(job->args);g_free(job->text);g_free(job);}
static gboolean send_job(gpointer data){
    struct job *job=data;
    if(job->widget){
        generation=job->generation;
        if(job->changed){pending_resets++;call("reset",NULL);if(job->focus)call("activateContext",NULL);}
        g_free(surrounding);surrounding=job->text;job->text=NULL;cursor=job->cursor;anchor=job->anchor;
    }
    if(!strcmp(job->method,"showInputMethod"))call("activateContext",NULL);
    call(job->method,job->args);return G_SOURCE_REMOVE;
}
static gboolean queue_job(struct job *job){
    pthread_mutex_lock(&state_lock);GMainContext *target=context?g_main_context_ref(context):NULL;pthread_mutex_unlock(&state_lock);
    if(!target){g_variant_unref(job->args);g_free(job->text);g_free(job);return FALSE;}
    g_main_context_invoke_full(target,G_PRIORITY_DEFAULT,send_job,job,free_job);g_main_context_unref(target);return TRUE;
}
static void peer_closed(GDBusConnection *c,gboolean vanished,GError *error,gpointer data){(void)c;(void)vanished;(void)error;(void)data;if(loop)g_main_loop_quit(loop);}
static void *run_peer(void *unused){
    (void)unused;if((*vm)->AttachCurrentThreadAsDaemon(vm,(void**)&worker_env,NULL)!=JNI_OK)return NULL;
    GError *error=NULL;GMainContext *owned=g_main_context_new();g_main_context_push_thread_default(owned);
    const char *runtime=g_getenv("XDG_RUNTIME_DIR");gchar *address=runtime?g_strdup_printf("unix:path=%s/maliit-server/dbus-socket",runtime):NULL;
    if(address)connection=g_dbus_connection_new_for_address_sync(address,G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT,NULL,NULL,&error);
    g_free(address);
    GDBusNodeInfo *node=NULL;guint object=0;
    if(connection){
        g_dbus_connection_set_exit_on_close(connection,FALSE);node=g_dbus_node_info_new_for_xml(maliit_client_xml,&error);
        if(node)object=g_dbus_connection_register_object(connection,"/com/meego/inputmethod/inputcontext",node->interfaces[0],&vtable,NULL,NULL,&error);
    }
    if(object){
        loop=g_main_loop_new(owned,FALSE);g_signal_connect(connection,"closed",G_CALLBACK(peer_closed),NULL);
        pthread_mutex_lock(&state_lock);context=owned;pthread_mutex_unlock(&state_lock);emit(0,NULL,1,0,0,0);
        g_main_loop_run(loop);
        pthread_mutex_lock(&state_lock);context=NULL;pthread_mutex_unlock(&state_lock);
        g_dbus_connection_unregister_object(connection,object);g_main_loop_unref(loop);loop=NULL;
    }
    if(error){fprintf(stderr,"SDIME=connection_unavailable|code=%d\n",error->code);g_error_free(error);}
    emit(0,NULL,0,0,0,0);
    if(connection){g_dbus_connection_close_sync(connection,NULL,NULL);g_object_unref(connection);connection=NULL;}
    if(node)g_dbus_node_info_unref(node);
    g_free(surrounding);surrounding=NULL;pending_resets=0;
    pthread_mutex_lock(&state_lock);started=0;pthread_mutex_unlock(&state_lock);
    g_main_context_pop_thread_default(owned);g_main_context_unref(owned);(*vm)->DetachCurrentThread(vm);return NULL;
}
JNIEXPORT void JNICALL Java_SdMaliit_nativeStart(JNIEnv *env,jclass cls){
    pthread_mutex_lock(&state_lock);if(started){pthread_mutex_unlock(&state_lock);return;}started=1;
    if(!client_class){client_class=(*env)->NewGlobalRef(env,cls);event_method=(*env)->GetStaticMethodID(env,cls,"onNative","(JILjava/lang/String;IIII)V");}
    pthread_t thread;int result=pthread_create(&thread,NULL,run_peer,NULL);if(result)started=0;else pthread_detach(thread);pthread_mutex_unlock(&state_lock);
    if(result)(*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/IllegalStateException"),"Cannot start keyboard connection");
}
static gchar *java_text(JNIEnv *env,jstring text){if(!text)return g_strdup("");const jchar *chars=(*env)->GetStringChars(env,text,NULL);if(!chars)return NULL;gchar *result=g_utf16_to_utf8((gunichar2*)chars,(*env)->GetStringLength(env,text),NULL,NULL,NULL);(*env)->ReleaseStringChars(env,text,chars);return result;}
JNIEXPORT jboolean JNICALL Java_SdMaliit_nativeWidget(JNIEnv *env,jclass cls,jlong gen,jboolean focus,jboolean changed,jint content,jboolean hidden,jboolean prediction,jboolean caps,jstring text,jint cursor_pos,jint anchor_pos,jint enter){
    (void)cls;struct job *job=g_new0(struct job,1);job->method="updateWidgetInformation";job->widget=TRUE;job->generation=gen;job->changed=changed;job->focus=focus;job->text=hidden?g_strdup(""):java_text(env,text);job->cursor=hidden?0:cursor_pos;job->anchor=hidden?0:anchor_pos;
    if(!job->text){g_free(job);return JNI_FALSE;}
    GVariantBuilder values;g_variant_builder_init(&values,G_VARIANT_TYPE("a{sv}"));
#define PROPERTY(name,value) g_variant_builder_add(&values,"{sv}",name,value)
    PROPERTY("focusState",g_variant_new_boolean(focus));PROPERTY("contentType",g_variant_new_int32(content));PROPERTY("hiddenText",g_variant_new_boolean(hidden));PROPERTY("predictionEnabled",g_variant_new_boolean(prediction));PROPERTY("autocapitalizationEnabled",g_variant_new_boolean(caps));PROPERTY("enterKeyType",g_variant_new_int32(enter));PROPERTY("surroundingText",g_variant_new_string(job->text));PROPERTY("cursorPosition",g_variant_new_int32(job->cursor));PROPERTY("anchorPosition",g_variant_new_int32(job->anchor));PROPERTY("hasSelection",g_variant_new_boolean(job->cursor!=job->anchor));
#undef PROPERTY
    job->args=g_variant_ref_sink(g_variant_new("(a{sv}b)",&values,changed));return queue_job(job)?JNI_TRUE:JNI_FALSE;
}
JNIEXPORT jboolean JNICALL Java_SdMaliit_nativeShow(JNIEnv *env,jclass cls,jboolean show){(void)env;(void)cls;struct job *job=g_new0(struct job,1);job->method=show?"showInputMethod":"hideInputMethod";job->args=g_variant_ref_sink(g_variant_new("()"));return queue_job(job)?JNI_TRUE:JNI_FALSE;}
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *value,void *reserved){(void)reserved;vm=value;return JNI_VERSION_1_6;}
