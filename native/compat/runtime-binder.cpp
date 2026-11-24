#include <jni.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <linux/android/binder.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstring>
#include <cstdio>

extern "C" void *sd_lookup_android(const char *name);

// AOSP sp<T> is one pointer with non-trivial call semantics. This holder keeps
// the returned native strong reference for the process lifetime. In particular,
// GCC/Clang use the same ARM64 hidden-result-pointer ABI for this return type.
// No host C++ object is passed as an Android ProcessState or Binder object.
struct NativeStrong {void *pointer=nullptr;~NativeStrong(){}};
static void *process_state;
static bool configured;
static jobject context_manager;
static void fail(JNIEnv *env,const char *message){env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),message);}
extern "C" int sd_private_binder_active(void){return configured;}

extern "C" JNIEXPORT jboolean JNICALL Java_SdBridge_configurePrivateBinder(JNIEnv *env,jclass,jstring value){
    if(configured)return JNI_TRUE;
    const char *path=env->GetStringUTFChars(value,nullptr);if(!path)return JNI_FALSE;
    if(std::strcmp(path,"/home/art/runtime/binder/binder")!=0){env->ReleaseStringUTFChars(value,path);fail(env,"Private Binder path differs from the component configuration");return JNI_FALSE;}
    struct stat info;
    if(lstat(path,&info)||!S_ISCHR(info.st_mode)||info.st_uid!=getuid()||(info.st_mode&077)!=0){env->ReleaseStringUTFChars(value,path);fail(env,"Private Binder device identity or permissions are invalid");return JNI_FALSE;}
    int fd=open(path,O_RDWR|O_CLOEXEC);struct binder_version version={};
    bool supported=fd>=0&&ioctl(fd,BINDER_VERSION,&version)==0&&version.protocol_version==BINDER_CURRENT_PROTOCOL_VERSION;
    if(fd>=0)close(fd);
    if(!supported){env->ReleaseStringUTFChars(value,path);fail(env,"Private Binder driver is unavailable or has an incompatible protocol");return JNI_FALSE;}
    auto existing=reinterpret_cast<NativeStrong(*)()>(sd_lookup_android("_ZN7android12ProcessState10selfOrNullEv"));
    auto initialize=reinterpret_cast<NativeStrong(*)(const char*)>(sd_lookup_android("_ZN7android12ProcessState14initWithDriverEPKc"));
    if(!existing||!initialize){env->ReleaseStringUTFChars(value,path);fail(env,"Matching Android Binder entry points are unavailable");return JNI_FALSE;}
    NativeStrong current=existing();
    if(current.pointer){env->ReleaseStringUTFChars(value,path);fail(env,"Binder was initialized before private driver selection");return JNI_FALSE;}
    NativeStrong result=initialize(path);env->ReleaseStringUTFChars(value,path);
    if(!result.pointer){fail(env,"Private Binder ProcessState creation failed");return JNI_FALSE;}
    process_state=result.pointer;configured=true;
    std::fprintf(stderr,"SDBINDER=driver_configured|protocol=%d|pid=%d\n",version.protocol_version,getpid());return JNI_TRUE;
}
extern "C" JNIEXPORT void JNICALL Java_SdBridge_startBinderPool(JNIEnv *env,jclass){
    auto start=reinterpret_cast<void(*)(void*)>(sd_lookup_android("_ZN7android12ProcessState15startThreadPoolEv"));
    if(!configured||!start){fail(env,"Private Binder was not configured");return;}start(process_state);
}
extern "C" JNIEXPORT jboolean JNICALL Java_SdBridge_becomeBinderContextManager(JNIEnv *env,jclass,jobject manager){
    auto convert=reinterpret_cast<NativeStrong(*)(JNIEnv*,jobject)>(sd_lookup_android("_ZN7android20ibinderForJavaObjectEP7_JNIEnvP8_jobject"));
    auto become=reinterpret_cast<bool(*)(void*,void*,void*)>(sd_lookup_android("_ZN7android12ProcessState20becomeContextManagerEPFbRKNS_8String16ERKNS_2spINS_7IBinderEEEPvES9_"));
    // Non-trivial sp<BBinder> by-value is passed by an invisible reference.
    auto install=reinterpret_cast<void(*)(NativeStrong*)>(sd_lookup_android("_ZN7android19setTheContextObjectENS_2spINS_7BBinderEEE"));
    if(!configured||!convert||!become||!install){fail(env,"Private Binder context entry points are unavailable");return JNI_FALSE;}
    NativeStrong binder=convert(env,manager);if(!binder.pointer)return JNI_FALSE;
    install(&binder);
    if(!become(process_state,nullptr,nullptr)){fail(env,"Private Binder already has a context manager or could not claim one");return JNI_FALSE;}
    context_manager=env->NewGlobalRef(manager);
    std::fprintf(stderr,"SDBINDER=context_manager|pid=%d\n",getpid());return JNI_TRUE;
}
