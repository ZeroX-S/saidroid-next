// JNI additions for owned local SurfaceControl children. No SurfaceFlinger RPCs.
static jclass view_controls;
static jmethodID view_scoped_session,view_reparent_legacy,view_destroy_batched;
static jmethodID view_session,view_session_release,view_create,view_position,view_size,view_layer,view_flags,view_relative,view_color,view_reparent,view_destroy,view_corner,view_defer,view_apply,view_merge,view_free,view_next,view_copy,view_release;
static jlong view_session_create(JNIEnv*e,jclass){return e->CallStaticLongMethod(view_controls,view_session);}
static jlong view_session_create_scoped(JNIEnv*e,jclass,jlong surface){return e->CallStaticLongMethod(view_controls,view_scoped_session,surface);}
static void view_session_free(JNIEnv*e,jclass,jlong id){e->CallStaticVoidMethod(view_controls,view_session_release,id,JNI_FALSE);}
static void view_session_kill(JNIEnv*e,jclass,jlong id){e->CallStaticVoidMethod(view_controls,view_session_release,id,JNI_TRUE);}
static jlong view_control_create(JNIEnv*e,jclass,jobject session,jstring name,jint w,jint h,jint format,jint flags,jlong parent,jobject){if(!session){fail(e,"java/lang/UnsupportedOperationException","A local SurfaceSession is required");return 0;}jclass type=e->GetObjectClass(session);jfieldID field=e->GetFieldID(type,"mNativeClient","J");jlong id=e->GetLongField(session,field);e->DeleteLocalRef(type);return e->CallStaticLongMethod(view_controls,view_create,id,name,w,h,format,flags,parent);}
static jlong view_control_create28(JNIEnv*e,jclass type,jobject session,jstring name,jint width,jint height,jint format,jint flags,jlong parent,jint,jint owner){
 if(owner!=-1&&static_cast<uid_t>(owner)!=getuid()){fail(e,"java/lang/SecurityException","SurfaceControl owner differs from the application");return 0;}
 return view_control_create(e,type,session,name,width,height,format,flags,parent,nullptr);
}
static void view_set_position(JNIEnv*e,jclass,jlong t,jlong id,jfloat x,jfloat y){e->CallStaticVoidMethod(view_controls,view_position,t,id,x,y);}
static void view_set_size(JNIEnv*e,jclass,jlong t,jlong id,jint w,jint h){e->CallStaticVoidMethod(view_controls,view_size,t,id,w,h);}
static void view_set_layer(JNIEnv*e,jclass,jlong t,jlong id,jint z){e->CallStaticVoidMethod(view_controls,view_layer,t,id,z);}
static void view_set_flags(JNIEnv*e,jclass,jlong t,jlong id,jint value,jint mask){e->CallStaticVoidMethod(view_controls,view_flags,t,id,value,mask);}
static void view_set_relative(JNIEnv*e,jclass,jlong t,jlong id,jobject relative,jint z){e->CallStaticVoidMethod(view_controls,view_relative,t,id,relative,z);}
static void view_set_color(JNIEnv*e,jclass,jlong t,jlong id,jfloatArray value){e->CallStaticVoidMethod(view_controls,view_color,t,id,value);}
static void view_set_parent(JNIEnv*e,jclass,jlong t,jlong id,jlong parent){e->CallStaticVoidMethod(view_controls,view_reparent,t,id,parent);}
static void view_control_destroy(JNIEnv*e,jclass,jlong id){e->CallStaticVoidMethod(view_controls,view_destroy,id);}
static void view_control_destroy_batched(JNIEnv*e,jclass,jlong transaction,jlong id){e->CallStaticVoidMethod(view_controls,view_destroy_batched,transaction,id);}
static void view_set_parent28(JNIEnv*e,jclass,jlong transaction,jlong id,jobject parent){e->CallStaticVoidMethod(view_controls,view_reparent_legacy,transaction,id,parent);}
static void view_set_corner(JNIEnv*e,jclass,jlong t,jlong id,jfloat value){e->CallStaticVoidMethod(view_controls,view_corner,t,id,value);}
static void view_defer_frame(JNIEnv*e,jclass,jlong t,jlong id,jlong surface,jlong frame){e->CallStaticVoidMethod(view_controls,view_defer,t,id,surface,frame);}
static void view_apply_transaction(JNIEnv*e,jclass,jlong t,jboolean sync){e->CallStaticVoidMethod(view_controls,view_apply,t,sync);}
static void view_merge_transaction(JNIEnv*e,jclass,jlong target,jlong source){e->CallStaticVoidMethod(view_controls,view_merge,target,source);}
static jlong view_next_frame(JNIEnv*e,jclass,jlong surface){return e->CallStaticLongMethod(view_controls,view_next,surface);}
static jlong view_copy_control(JNIEnv*e,jclass,jlong id){return e->CallStaticLongMethod(view_controls,view_copy,id);}
static void view_release_control(JNIEnv*e,jclass,jlong id){e->CallStaticVoidMethod(view_controls,view_release,id);}
static void view_free_transaction(void*pointer){Env env;if(env.e)env.e->CallStaticVoidMethod(view_controls,view_free,(jlong)(intptr_t)pointer);}
static jlong view_finalizer(JNIEnv*,jclass){return (jlong)(intptr_t)view_free_transaction;}
extern "C" JNIEXPORT jlong JNICALL Java_SdSurfaceViews_nativeFrames(JNIEnv*e,jclass,jobject surface){void*window=from_surface(e,surface);if(!window)return -1;GpuApi&a=gpu_api();jlong value=a.ready?a.frames(window):-1;window_release(window);return value;}
// Solid colors use a process-owned wl_shm layer, with no EGL producer.
extern "C" JNIEXPORT void JNICALL Java_SdSurfaceViews_nativeColor(JNIEnv*e,jclass,jobject surface,jlong id,jfloat red,jfloat green,jfloat blue){
 (void)surface;void *library=dlopen("libsdwindow.so",RTLD_NOW|RTLD_LOCAL);
 auto color=library?(int(*)(int,float,float,float))dlsym(library,"sd_window_color"):nullptr;
 int result=color?color((int)id,red,green,blue):-1;if(library)dlclose(library);
 if(result!=0)fail(e,"java/lang/IllegalStateException","Owned Wayland solid-color queue rejected frame");
}
extern "C" JNIEXPORT void JNICALL Java_SdSurfaceViews_nativeInstall(JNIEnv*e,jclass type){
 jclass version=e->FindClass("android/os/Build$VERSION");if(!version)return;
 jfieldID sdk=e->GetStaticFieldID(version,"SDK_INT","I");if(!sdk)return;
 jint api=e->GetStaticIntField(version,sdk);e->DeleteLocalRef(version);
 // GLSurfaceView uses the API29 EGL10/GLImpl JNI entry points even when its
 // renderer requests GLES2. Register the shipped upstream implementation so
 // it reaches the same process-private EGL/window bridge as EGL14.
 void *linker=dlopen("libdl_bio.so.0",RTLD_NOW|RTLD_GLOBAL);
 auto open=linker?(void*(*)(const char*,int))dlsym(linker,"bionic_dlopen"):nullptr;
 auto symbol=linker?(void*(*)(void*,const char*))dlsym(linker,"bionic_dlsym"):nullptr;
 const char *root=getenv("ANDROID_ROOT");
 void *runtime=open&&root?open((std::string(root)+"/android-libs/libandroid_runtime.so").c_str(),RTLD_NOW):nullptr;
 for(const char *name:{"register_com_google_android_gles_jni_GLImpl","register_com_google_android_gles_jni_EGLImpl"}){
  std::string mangled="_Z"+std::to_string(strlen(name))+name+"P7_JNIEnv";
  auto install=runtime&&symbol?(int(*)(JNIEnv*))symbol(runtime,mangled.c_str()):nullptr;
  if(!install){fail(e,"java/lang/IllegalStateException","Upstream EGL10 JNI registration is unavailable");return;}
  if(install(e)<0||e->ExceptionCheck())return;
 }
 fprintf(stderr,"SDGLSURFACE=installed|api=%d|jni=upstream-egl10-glimpl|egl=process-owned-wayland\n",api);
 view_controls=(jclass)e->NewGlobalRef(type);
#define VIEW_ID(name,sig) e->GetStaticMethodID(type,name,sig)
 view_session=VIEW_ID("session","()J");view_session_release=VIEW_ID("sessionRelease","(JZ)V");view_create=VIEW_ID("create","(JLjava/lang/String;IIIIJ)J");view_position=VIEW_ID("position","(JJFF)V");view_size=VIEW_ID("size","(JJII)V");view_layer=VIEW_ID("layer","(JJI)V");view_flags=VIEW_ID("flags","(JJII)V");view_relative=VIEW_ID("relative","(JJLandroid/os/IBinder;I)V");view_color=VIEW_ID("color","(JJ[F)V");view_reparent=VIEW_ID("reparent","(JJJ)V");view_destroy=VIEW_ID("destroy","(J)V");view_corner=VIEW_ID("corner","(JJF)V");view_defer=VIEW_ID("defer","(JJJJ)V");view_apply=VIEW_ID("apply","(JZ)V");view_merge=VIEW_ID("merge","(JJ)V");view_free=VIEW_ID("free","(J)V");view_next=VIEW_ID("nextFrame","(J)J");view_copy=VIEW_ID("copy","(J)J");view_release=VIEW_ID("release","(J)V");
#undef VIEW_ID
 if(e->ExceptionCheck())return;
 JNINativeMethod sessions[]={METHOD("nativeCreate","()J",view_session_create),METHOD("nativeDestroy","(J)V",view_session_free),METHOD("nativeKill","(J)V",view_session_kill)};
 jclass session=e->FindClass("android/view/SurfaceSession");if(!session||e->RegisterNatives(session,sessions,3)<0)return;
 if(api<29){
  view_scoped_session=e->GetStaticMethodID(type,"session","(J)J");
  if(!view_scoped_session)return;
  JNINativeMethod scoped=METHOD("nativeCreateScoped","(J)J",view_session_create_scoped);
  if(e->RegisterNatives(session,&scoped,1)<0)return;
 }
 e->DeleteLocalRef(session);
 JNINativeMethod controls[]={METHOD("nativeSetPosition","(JJFF)V",view_set_position),METHOD("nativeSetSize","(JJII)V",view_set_size),METHOD("nativeSetLayer","(JJI)V",view_set_layer),METHOD("nativeSetFlags","(JJII)V",view_set_flags),METHOD("nativeSetRelativeLayer","(JJLandroid/os/IBinder;I)V",view_set_relative),METHOD("nativeSetColor","(JJ[F)V",view_set_color),METHOD("nativeDestroy","(J)V",view_control_destroy),METHOD("nativeDeferTransactionUntilSurface","(JJJJ)V",view_defer_frame),METHOD("nativeApplyTransaction","(JZ)V",view_apply_transaction),METHOD("nativeMergeTransaction","(JJ)V",view_merge_transaction),METHOD("nativeGetNativeTransactionFinalizer","()J",view_finalizer),METHOD("nativeRelease","(J)V",view_release_control)};
 jclass control=e->FindClass("android/view/SurfaceControl");if(!control||e->RegisterNatives(control,controls,sizeof(controls)/sizeof(controls[0]))<0)return;
 if(api<29){
  view_reparent_legacy=e->GetStaticMethodID(type,"reparent","(JJLandroid/os/IBinder;)V");
  view_destroy_batched=e->GetStaticMethodID(type,"destroy","(JJ)V");
  if(!view_reparent_legacy||!view_destroy_batched)return;
  JNINativeMethod legacy[]={METHOD("nativeCreate","(Landroid/view/SurfaceSession;Ljava/lang/String;IIIIJII)J",view_control_create28),METHOD("nativeReparent","(JJLandroid/os/IBinder;)V",view_set_parent28),METHOD("nativeDestroy","(JJ)V",view_control_destroy_batched)};
  if(e->RegisterNatives(control,legacy,sizeof(legacy)/sizeof(legacy[0]))<0)return;
 }else{
  JNINativeMethod modern[]={METHOD("nativeCreate","(Landroid/view/SurfaceSession;Ljava/lang/String;IIIIJLandroid/os/Parcel;)J",view_control_create),METHOD("nativeReparent","(JJJ)V",view_set_parent),METHOD("nativeSetCornerRadius","(JJF)V",view_set_corner),METHOD("nativeCopyFromSurfaceControl","(J)J",view_copy_control)};
  if(e->RegisterNatives(control,modern,sizeof(modern)/sizeof(modern[0]))<0)return;
 }
 e->DeleteLocalRef(control);JNINativeMethod surface_methods[]={METHOD("nativeGetNextFrameNumber","(J)J",view_next_frame)};jclass surface=e->FindClass("android/view/Surface");if(!surface||e->RegisterNatives(surface,surface_methods,1)<0)return;e->DeleteLocalRef(surface);fprintf(stderr,"SDSURFACEVIEW=installed|api=%d|backend=owned-hwui-wayland-queues\n",api);
}

// Retiring compositor visibility is separate from releasing producer references.
extern "C" JNIEXPORT void JNICALL Java_SdSurfaceViews_nativeRetire(JNIEnv*e,jclass,jint id){
 void*library=dlopen("libsdwindow.so",RTLD_NOW|RTLD_LOCAL);
 auto retire=library?(void(*)(int))dlsym(library,"sd_window_gpu_retire"):nullptr;
 if(!retire){if(library)dlclose(library);fail(e,"java/lang/IllegalStateException","Owned Wayland layer retirement is unavailable");return;}
 retire(id);dlclose(library);

}
