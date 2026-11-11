#include <jni.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
static JavaVM *control_vm;
static jclass store,controls;
static jmethodID retain_id,release_id,remove_id,get_surface,handle_id,next_frame;
static jmethodID transaction_create,transaction_free,transaction_apply,transaction_merge;
static jmethodID set_position,set_size,set_layer,set_alpha,set_flags,set_matrix,set_crop;
static JNIEnv *current_env(void){JNIEnv *e=NULL;if((*control_vm)->GetEnv(control_vm,(void**)&e,JNI_VERSION_1_6)!=JNI_OK)(*control_vm)->AttachCurrentThreadAsDaemon(control_vm,(void**)&e,NULL);return e;}
static void transaction_finalizer(void *id){JNIEnv *e=current_env();if(e)(*e)->CallStaticVoidMethod(e,controls,transaction_free,(jlong)(intptr_t)id);}
static jlong create_transaction(JNIEnv *e,jclass c){(void)c;return (*e)->CallStaticLongMethod(e,controls,transaction_create);}
static jlong transaction_finalizer_address(JNIEnv *e,jclass c){(void)e;(void)c;return (jlong)(intptr_t)transaction_finalizer;}
static void apply_transaction(JNIEnv *e,jclass c,jlong id,jboolean sync){(void)c;(*e)->CallStaticVoidMethod(e,controls,transaction_apply,id,sync);}
static void merge_transaction(JNIEnv *e,jclass c,jlong target,jlong source){(void)c;(*e)->CallStaticVoidMethod(e,controls,transaction_merge,target,source);}
static void position(JNIEnv *e,jclass c,jlong t,jlong id,jfloat x,jfloat y){(void)c;(*e)->CallStaticVoidMethod(e,controls,set_position,t,id,x,y);}
static void size(JNIEnv *e,jclass c,jlong t,jlong id,jint w,jint h){(void)c;(*e)->CallStaticVoidMethod(e,controls,set_size,t,id,w,h);}
static void layer(JNIEnv *e,jclass c,jlong t,jlong id,jint value){(void)c;(*e)->CallStaticVoidMethod(e,controls,set_layer,t,id,value);}
static void alpha(JNIEnv *e,jclass c,jlong t,jlong id,jfloat value){(void)c;(*e)->CallStaticVoidMethod(e,controls,set_alpha,t,id,value);}
static void flags(JNIEnv *e,jclass c,jlong t,jlong id,jint value,jint mask){(void)c;(*e)->CallStaticVoidMethod(e,controls,set_flags,t,id,value,mask);}
static void matrix(JNIEnv *e,jclass c,jlong t,jlong id,jfloat a,jfloat b,jfloat d,jfloat f){(void)c;(*e)->CallStaticVoidMethod(e,controls,set_matrix,t,id,a,b,d,f);}
static void crop(JNIEnv *e,jclass c,jlong t,jlong id,jint left,jint top,jint right,jint bottom){(void)c;(*e)->CallStaticVoidMethod(e,controls,set_crop,t,id,left,top,right<0?-1:right-left,bottom<0?-1:bottom-top);}
static jlong copy_control(JNIEnv *e,jclass c,jlong id){(void)c;return (*e)->CallStaticLongMethod(e,store,retain_id,id);}
static void release_control(JNIEnv *e,jclass c,jlong id){(void)c;if(id)(*e)->CallStaticVoidMethod(e,store,release_id,id);}
static void destroy_control(JNIEnv *e,jclass c,jlong id){(void)c;if(id)(*e)->CallStaticVoidMethod(e,store,remove_id,id);}
static jobject get_handle(JNIEnv *e,jclass c,jlong id){(void)c;return (*e)->CallStaticObjectMethod(e,store,handle_id,id);}
static jlong surface_from_control(JNIEnv *e,jclass c,jlong old,jlong id){(void)c;return (*e)->CallStaticLongMethod(e,store,get_surface,old,id);}
static jlong create_surface_from_control(JNIEnv *e,jclass c,jlong id){return surface_from_control(e,c,0,id);}
static jlong frame_number(JNIEnv *e,jclass c,jlong id){(void)c;return (*e)->CallStaticLongMethod(e,store,next_frame,id);}
static jint shared_mode(JNIEnv *e,jclass c,jlong id,jboolean enabled){(void)c;(void)(*e)->CallStaticLongMethod(e,store,next_frame,id);return enabled?-ENOTSUP:0;}
static jboolean protected_support(JNIEnv *e,jclass c){(void)e;(void)c;return JNI_FALSE;}
void sd_control_install(JNIEnv *e){
    (*e)->GetJavaVM(e,&control_vm);
    store=(*e)->NewGlobalRef(e,(*e)->FindClass(e,"SdSurfaceStore"));
    controls=(*e)->NewGlobalRef(e,(*e)->FindClass(e,"SdSurfaceControls"));
#define METHOD(target,name,signature) (*e)->GetStaticMethodID(e,target,name,signature)
    retain_id=METHOD(store,"retain","(J)J");release_id=METHOD(store,"release","(J)V");remove_id=METHOD(store,"remove","(J)V");
    get_surface=METHOD(store,"surfaceFromControl","(JJ)J");handle_id=METHOD(store,"handle","(J)Landroid/os/IBinder;");next_frame=METHOD(store,"nextFrame","(J)J");
    transaction_create=METHOD(controls,"createTransaction","()J");transaction_free=METHOD(controls,"freeTransaction","(J)V");transaction_apply=METHOD(controls,"apply","(JZ)V");transaction_merge=METHOD(controls,"merge","(JJ)V");
    set_position=METHOD(controls,"position","(JJFF)V");set_size=METHOD(controls,"size","(JJII)V");set_layer=METHOD(controls,"layer","(JJI)V");set_alpha=METHOD(controls,"alpha","(JJF)V");set_flags=METHOD(controls,"flags","(JJII)V");set_matrix=METHOD(controls,"matrix","(JJFFFF)V");set_crop=METHOD(controls,"crop","(JJIIII)V");
#undef METHOD
    if((*e)->ExceptionCheck(e))return;
    JNINativeMethod control_methods[]={
        {"nativeCreateTransaction","()J",create_transaction},{"nativeGetNativeTransactionFinalizer","()J",transaction_finalizer_address},
        {"nativeApplyTransaction","(JZ)V",apply_transaction},{"nativeMergeTransaction","(JJ)V",merge_transaction},
        {"nativeSetPosition","(JJFF)V",position},{"nativeSetSize","(JJII)V",size},{"nativeSetLayer","(JJI)V",layer},
        {"nativeSetAlpha","(JJF)V",alpha},{"nativeSetFlags","(JJII)V",flags},{"nativeSetMatrix","(JJFFFF)V",matrix},
        {"nativeSetWindowCrop","(JJIIII)V",crop},
        {"nativeRelease","(J)V",release_control},{"nativeDestroy","(J)V",destroy_control},{"nativeGetHandle","(J)Landroid/os/IBinder;",get_handle}};
    if((*e)->RegisterNatives(e,(*e)->FindClass(e,"android/view/SurfaceControl"),control_methods,sizeof(control_methods)/sizeof(control_methods[0]))<0)return;
    jclass version=(*e)->FindClass(e,"android/os/Build$VERSION");if(!version)return;
    jfieldID sdk=(*e)->GetStaticFieldID(e,version,"SDK_INT","I");if(!sdk)return;
    jint api=(*e)->GetStaticIntField(e,version,sdk);(*e)->DeleteLocalRef(e,version);
    if(api>=29){
        JNINativeMethod modern_controls[]={{"nativeCopyFromSurfaceControl","(J)J",copy_control},
            {"nativeGetProtectedContentSupport","()Z",protected_support}};
        if((*e)->RegisterNatives(e,(*e)->FindClass(e,"android/view/SurfaceControl"),modern_controls,2)<0)return;
    }
    JNINativeMethod surface_methods[]={
        {"nativeCreateFromSurfaceControl","(J)J",create_surface_from_control},
        {"nativeGetNextFrameNumber","(J)J",frame_number},{"nativeSetSharedBufferModeEnabled","(JZ)I",shared_mode},
        {"nativeSetAutoRefreshEnabled","(JZ)I",shared_mode}};
    if((*e)->RegisterNatives(e,(*e)->FindClass(e,"android/view/Surface"),surface_methods,sizeof(surface_methods)/sizeof(surface_methods[0]))<0)return;
    JNINativeMethod from_control={"nativeGetFromSurfaceControl",api>=29?"(JJ)J":"(J)J",api>=29?(void*)surface_from_control:(void*)create_surface_from_control};
    (*e)->RegisterNatives(e,(*e)->FindClass(e,"android/view/Surface"),&from_control,1);
}
