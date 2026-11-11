/* SaiDroid JNI 桥：在进程内按需注册 bionic 库目录，用 bionic 加载器加载 Android 原生库。
 * 不设全局 BIONIC_LD_LIBRARY_PATH，避免 shim 接管 ART 自身的 glibc 库。 */
#define _GNU_SOURCE
#include <jni.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/prctl.h>
#include "../../native/saidroid-system-paths.h"

typedef void* (*bionic_dlopen_t)(const char*, int);
typedef void* (*bionic_dlsym_t)(void*, const char*);
typedef void  (*dl_parse_t)(const char*, char*);

static JavaVM* g_vm = NULL;
static void*   g_handle = NULL;
static void*   g_private_libc = NULL;
static char    g_libdir[1024] = {0};
static char    g_system_root[1024] = "/home/art";
static jclass software_graphics_class;
static jmethodID configure_shader_cache;
static int framework_api = 28;
static jclass namespace_class;
static jmethodID bind_namespace;
static jstring classloader_namespace(JNIEnv *env,jclass cls,jobject loader,jint sdk,jstring libraries,jstring permitted,jboolean shared,jstring dex){
    (void)cls;return (jstring)(*env)->CallStaticObjectMethod(env,namespace_class,bind_namespace,loader,sdk,libraries,permitted,shared,dex);
}
static jstring classloader_namespace28(JNIEnv *env,jclass cls,jobject loader,jint sdk,jstring libraries,jstring permitted,jboolean shared,jboolean vendor){
    (void)cls;return (jstring)(*env)->CallStaticObjectMethod(env,namespace_class,bind_namespace,loader,sdk,libraries,permitted,shared,vendor);
}
JNIEXPORT jboolean JNICALL Java_SdBridge_installClassLoaderNamespaces(JNIEnv *env,jclass cls){
    (void)cls;if(framework_api<28)return JNI_FALSE;
    namespace_class=(*env)->NewGlobalRef(env,(*env)->FindClass(env,"SdClassLoaderNamespaces"));if(!namespace_class)return JNI_FALSE;
    if(framework_api==28){
        bind_namespace=(*env)->GetStaticMethodID(env,namespace_class,"bindLegacy","(Ljava/lang/ClassLoader;ILjava/lang/String;Ljava/lang/String;ZZ)Ljava/lang/String;");if(!bind_namespace)return JNI_FALSE;
        JNINativeMethod methods[]={{"createClassloaderNamespace","(Ljava/lang/ClassLoader;ILjava/lang/String;Ljava/lang/String;ZZ)Ljava/lang/String;",classloader_namespace28}};
        return (*env)->RegisterNatives(env,(*env)->FindClass(env,"com/android/internal/os/ClassLoaderFactory"),methods,1)==0?JNI_TRUE:JNI_FALSE;
    }
    bind_namespace=(*env)->GetStaticMethodID(env,namespace_class,"bind","(Ljava/lang/ClassLoader;ILjava/lang/String;Ljava/lang/String;ZLjava/lang/String;)Ljava/lang/String;");if(!bind_namespace)return JNI_FALSE;
    JNINativeMethod methods[]={{"createClassloaderNamespace","(Ljava/lang/ClassLoader;ILjava/lang/String;Ljava/lang/String;ZLjava/lang/String;)Ljava/lang/String;",classloader_namespace}};
    return (*env)->RegisterNatives(env,(*env)->FindClass(env,"com/android/internal/os/ClassLoaderFactory"),methods,1)==0?JNI_TRUE:JNI_FALSE;
}

static bool private_system_font_path(char **path) {
    return framework_api>=29?saidroid_private_api29_path(g_system_root,path):saidroid_private_font_path(g_system_root, path);
}

/* The standalone service registry has only in-process Binder endpoints. Identity
 * is the real Linux process, and there is no kernel transaction queue to flush.
 * Keep native Binder object/Parcel lifetime management from Android itself. */
static __thread jint local_strict_policy;
static __thread jint local_work_source=-1;
static jboolean local_is_handling(JNIEnv *env,jclass cls){(void)env;(void)cls;return JNI_FALSE;}
static jint local_get_work_source(JNIEnv *env,jclass cls){(void)env;(void)cls;return local_work_source;}
static jlong local_set_work_source(JNIEnv *env,jclass cls,jint uid){(void)env;(void)cls;jint previous=local_work_source;local_work_source=uid;return previous;}
static jlong local_clear_work_source(JNIEnv *env,jclass cls){return local_set_work_source(env,cls,-1);}
static void local_restore_work_source(JNIEnv *env,jclass cls,jlong token){(void)env;(void)cls;local_work_source=(jint)token;}
static jint local_calling_pid(JNIEnv *env, jclass cls) { (void)env; (void)cls; return getpid(); }
static jint local_calling_uid(JNIEnv *env, jclass cls) { (void)env; (void)cls; return getuid(); }
static jlong local_clear_identity(JNIEnv *env, jclass cls) { (void)env; (void)cls; return ((jlong)getuid()<<32)|(uint32_t)getpid(); }
static void local_restore_identity(JNIEnv *env, jclass cls, jlong value) {
    if (value != local_clear_identity(env, cls)) {
        (*env)->ThrowNew(env, (*env)->FindClass(env,"java/lang/SecurityException"), "Foreign Binder identity is unavailable in this process");
    }
}
static void local_set_strict(JNIEnv *env,jclass cls,jint value) { (void)env;(void)cls;local_strict_policy=value; }
static jint local_get_strict(JNIEnv *env,jclass cls) { (void)env;(void)cls;return local_strict_policy; }
static void local_flush(JNIEnv *env,jclass cls) { (void)env;(void)cls; /* No remote Binder commands are queued. */ }
static void local_pool_unsupported(JNIEnv *env,jclass cls) { (void)cls;(*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/UnsupportedOperationException"),"Kernel Binder thread pools are not part of this runtime"); }
static jobject local_context_unsupported(JNIEnv *env,jclass cls) { local_pool_unsupported(env,cls);return NULL; }
static int register_local_binder(JNIEnv *env) {
    JNINativeMethod methods[] = {
        {"getCallingPid","()I",local_calling_pid},{"getCallingUid","()I",local_calling_uid},
        {"clearCallingIdentity","()J",local_clear_identity},{"restoreCallingIdentity","(J)V",local_restore_identity},
        {"setThreadStrictModePolicy","(I)V",local_set_strict},{"getThreadStrictModePolicy","()I",local_get_strict},
        {"flushPendingCommands","()V",local_flush},
        {"blockUntilThreadAvailable","()V",local_pool_unsupported}};
    if((*env)->RegisterNatives(env,(*env)->FindClass(env,"android/os/Binder"),methods,sizeof(methods)/sizeof(methods[0]))<0)return -1;
    if(framework_api<28){JNINativeMethod pool[]={{"joinThreadPool","()V",local_pool_unsupported}};if((*env)->RegisterNatives(env,(*env)->FindClass(env,"android/os/Binder"),pool,1)<0)return -1;}
    if(framework_api>=29){
        JNINativeMethod attribution[]={{"isHandlingTransaction","()Z",local_is_handling},{"getCallingWorkSourceUid","()I",local_get_work_source},{"setCallingWorkSourceUid","(I)J",local_set_work_source},{"clearCallingWorkSource","()J",local_clear_work_source},{"restoreCallingWorkSource","(J)V",local_restore_work_source}};
        if((*env)->RegisterNatives(env,(*env)->FindClass(env,"android/os/Binder"),attribution,sizeof(attribution)/sizeof(attribution[0]))<0)return -1;
    }
    JNINativeMethod internal[]={{"handleGc","()V",local_flush},{"joinThreadPool","()V",local_pool_unsupported},{"getContextObject","()Landroid/os/IBinder;",local_context_unsupported}};
    return (*env)->RegisterNatives(env,(*env)->FindClass(env,"com/android/internal/os/BinderInternal"),internal,sizeof(internal)/sizeof(internal[0]));
}

static void standalone_process_name(JNIEnv *env,jclass cls,jstring value) {
    (void)cls;
    if(!value){(*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/NullPointerException"),"processName");return;}
    const char *name=(*env)->GetStringUTFChars(env,value,NULL);if(!name)return;
    size_t length=strlen(name);
    if(!length||length>255){(*env)->ReleaseStringUTFChars(env,value,name);(*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/IllegalArgumentException"),"Invalid process name");return;}
    /* Linux exposes our own writable argv region. ART has already copied its
     * Java arguments; update the real process title without an app_process object. */
    FILE *stream=fopen("/proc/self/stat","r");char stat_line[8192];uintptr_t begin=0,end=0;
    if(stream){if(fgets(stat_line,sizeof(stat_line),stream)){
        char *cursor=strrchr(stat_line,')');if(cursor){cursor+=2;char *save=NULL;int field=3;
            for(char *token=strtok_r(cursor," ",&save);token;token=strtok_r(NULL," ",&save),field++){
                if(field==48)begin=(uintptr_t)strtoull(token,NULL,10);
                if(field==49){end=(uintptr_t)strtoull(token,NULL,10);break;}
            }
        }
    }fclose(stream);}
    if(begin&&end>begin&&end-begin<1024*1024&&length<end-begin){
        memset((void*)begin,0,end-begin);memcpy((void*)begin,name,length);
    }
    prctl(PR_SET_NAME,(unsigned long)(length>15?name+length-15:name),0,0,0);
    (*env)->ReleaseStringUTFChars(env,value,name);
}
static void software_shader_cache(JNIEnv *env,jclass cls,jstring path) {
    (void)cls;
    (*env)->CallStaticVoidMethod(env,software_graphics_class,configure_shader_cache,path);
}

/* Host ABI bridges belong exclusively on glibc's library path. Loading a second
 * copy as an Android ELF creates independent allocator/dlsym state. Refuse the
 * broken legacy deployment layout before any Android library is opened. */
static int android_library_layout_valid(const char *dirs) {
    const char *prefixes[] = {"libc_bio.so", "libdl_bio.so", "libpthread_bio.so", "libstdc++_bio.so", NULL};
    char *copy = strdup(dirs);
    if (!copy) return 0;
    char *save = NULL;
    int valid = 1;
    for (char *path = strtok_r(copy, ":", &save); path && valid; path = strtok_r(NULL, ":", &save)) {
        DIR *directory = opendir(path);
        if (!directory) continue;
        struct dirent *entry;
        while ((entry = readdir(directory)) != NULL) {
            for (int i = 0; prefixes[i]; i++) {
                size_t length = strlen(prefixes[i]);
                if (!strncmp(entry->d_name, prefixes[i], length)
                        && (entry->d_name[length] == '\0' || entry->d_name[length] == '.')) {
                    fprintf(stderr, "SDBRIDGE invalid Android library layout: %s/%s is a host ABI bridge\n",
                            path, entry->d_name);
                    valid = 0;
                    break;
                }
            }
        }
        closedir(directory);
    }
    free(copy);
    return valid;
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* reserved) {
    Dl_info owner;
    if (!dladdr((void *)android_library_layout_valid, &owner)) return JNI_ERR;
    void *global = dlopen(owner.dli_fname, RTLD_NOW | RTLD_GLOBAL | RTLD_NOLOAD);
    if (!global) return JNI_ERR;
    dlclose(global);
    g_vm = vm;
    return JNI_VERSION_1_6;
}

/* The private link map and each DSO's CFI checker own validation. Android's
 * shared shadow mapping is absent, matching libdl's unmapped-shadow result. */
size_t bionic___cfi_shadow_size(void) { return 0; }

/* No malloc-debug allocation-backtrace recorder is enabled in this process,
 * matching Bionic's empty result when its malloc-debug hooks are absent. */
void bionic_get_malloc_leak_info(uint8_t **info, size_t *overall, size_t *entry,
                                size_t *allocated, size_t *backtrace) {
    *info = NULL;
    *overall = *entry = *allocated = *backtrace = 0;
}
void bionic_free_malloc_leak_info(uint8_t *info) { free(info); }

extern int sd_import_host_hardware_properties(void *private_libc);
extern int sd_import_host_product_properties(void *private_libc);
extern int sd_import_host_timezone_properties(void *private_libc, char timezone[92]);

JNIEXPORT jstring JNICALL
Java_SdTimeZone_refreshNative(JNIEnv *env, jclass cls) {
    (void)cls;
    char timezone[92];
    int result = g_private_libc ? sd_import_host_timezone_properties(g_private_libc, timezone) : -1;
    if (result < 0) {
        (*env)->ThrowNew(env, (*env)->FindClass(env, "java/lang/IllegalStateException"),
                        "Host timezone import failed");
        return NULL;
    }
    return result ? (*env)->NewStringUTF(env, timezone) : NULL;
}

JNIEXPORT jboolean JNICALL
Java_SdBridge_loadBionicLibrary(JNIEnv* env, jclass cls, jstring jpath, jstring jdirs) {
    if (!g_vm) { fprintf(stderr, "SDBRIDGE no vm\n"); return JNI_FALSE; }

    const char* path = (*env)->GetStringUTFChars(env, jpath, NULL);
    const char* dirs = (*env)->GetStringUTFChars(env, jdirs, NULL);
    if (!path || !dirs) return JNI_FALSE;
    if (!android_library_layout_valid(dirs)) {
        (*env)->ReleaseStringUTFChars(env, jpath, path);
        (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
        return JNI_FALSE;
    }

    void* dl = dlopen("libdl_bio.so.0", RTLD_NOW | RTLD_GLOBAL);
    if (!dl) { fprintf(stderr, "SDBRIDGE dlopen libdl_bio: %s\n", dlerror()); return JNI_FALSE; }

    dl_parse_t       parse = (dl_parse_t)       dlsym(dl, "dl_parse_library_path");
    bionic_dlopen_t  bopen = (bionic_dlopen_t)  dlsym(dl, "bionic_dlopen");
    bionic_dlsym_t   bsym  = (bionic_dlsym_t)   dlsym(dl, "bionic_dlsym");
    if (!parse || !bopen || !bsym) {
        fprintf(stderr, "SDBRIDGE missing symbols: parse=%p open=%p sym=%p\n", parse, bopen, bsym);
        return JNI_FALSE;
    }

    parse(dirs, ":");
    snprintf(g_libdir, sizeof(g_libdir), "%s", dirs);
    const char *system_root = getenv("ANDROID_ROOT");
    if (system_root && system_root[0] == '/' && strlen(system_root) < sizeof(g_system_root)) {
        snprintf(g_system_root, sizeof(g_system_root), "%s", system_root);
    }
    /* 提高 bionic linker 调试等级，并保证缺符号时降级为桩而不是退出 */
    int* verbosity = (int*) dlsym(dl, "apkenv_debug_verbosity");
    if (verbosity) { *verbosity = getenv("SAILDROID_LINKER_VERBOSE") ? 1 : 0; fprintf(stderr, "SDBRIDGE verbosity set\n"); }
    if (getenv("SAILDROID_STRICT_LINK")) unsetenv("LINKER_DIE_AT_RUNTIME");
    else setenv("LINKER_DIE_AT_RUNTIME", "", 0);

    /* 用 glibc 的 dlopen 把兼容层载入全局符号表：
     * bionic 链接器解析未定义符号时会先找 "bionic_<name>"（dlsym RTLD_DEFAULT），
     * 只有这些库在 glibc 全局作用域里，pthread_* 之类的兼容实现才会被选中。 */
    {
        const char* preloads[] = { "libpthread_bio.so.0", "libc_bio.so.0", "libdl_bio.so.0", "libstdc++_bio.so.0", NULL };
        for (int i = 0; preloads[i]; ++i) {
            void* gh = dlopen(preloads[i], RTLD_NOW | RTLD_GLOBAL);
            fprintf(stderr, "SDBRIDGE glibc dlopen %s = %p\n", preloads[i], gh);
            if (gh && !strcmp(preloads[i], "libc_bio.so.0")) {
                void (*set_paths)(bool (*)(char **)) = dlsym(gh, "libc_bio_set_apply_path_overrides_func");
                if (!set_paths) {
                    fprintf(stderr, "SDBRIDGE native font path backend unavailable\n");
                    (*env)->ReleaseStringUTFChars(env, jpath, path);
                    (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
                    return JNI_FALSE;
                }
                set_paths(private_system_font_path);
                if (sd_import_host_product_properties(gh) < 0) {
                    (*env)->ReleaseStringUTFChars(env, jpath, path);
                    (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
                    return JNI_FALSE;
                }
                sd_import_host_hardware_properties(gh);
                g_private_libc = gh;
                char timezone[92];
                if (sd_import_host_timezone_properties(gh, timezone) < 0) {
                    (*env)->ReleaseStringUTFChars(env, jpath, path);
                    (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
                    return JNI_FALSE;
                }
                fprintf(stderr, "SDBRIDGE private native font root=%s\n", g_system_root);
            }
        }
    }

    /* 先载入 pthread 标准名 trampoline 库，让后续 bionic 库解析到兼容版本
     * （否则会用 glibc 的 pthread_mutex_t 写穿 bionic 的 4 字节结构） */
    {
        char pre[1024];
        snprintf(pre, sizeof(pre), "%s/libpthread_names.so", dirs);
        void* ph = bopen(pre, RTLD_NOW);
        fprintf(stderr, "SDBRIDGE preload pthread_names=%p\n", ph);
    }

    void* h = bopen(path, RTLD_NOW);
    if (!h) {
        typedef const char* (*geterr_t)(void);
        geterr_t geterr = (geterr_t) dlsym(dl, "apkenv_linker_get_error");
        const char* e = geterr ? geterr() : "?";
        fprintf(stderr, "SDBRIDGE bionic_dlopen failed for %s : %s\n", path, e ? e : "(null)");
        return JNI_FALSE;
    }
    g_handle = h;
    fprintf(stderr, "SDBRIDGE loaded %s handle=%p\n", path, h);
    /* app_process normally supplies this VM. We host the same Android natives
     * in an already running ART VM; stream/input callbacks must see that VM. */
    JavaVM **android_vm = (JavaVM **)bsym(h, "_ZN7android14AndroidRuntime7mJavaVME");
    if (!android_vm || (*android_vm && *android_vm != g_vm)) {
        fprintf(stderr, "SDBRIDGE AndroidRuntime JavaVM ownership mismatch\n");
        (*env)->ReleaseStringUTFChars(env, jpath, path);
        (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
        return JNI_FALSE;
    }
    *android_vm = g_vm;
    /* Android's helper also contains obsolete legacy-libcore caches. Initialize
     * the real common classes used by framework stream and weak-ref callbacks;
     * the external VM's modern libcore owns its own core-native initialization. */
    const char *jni_classes[][2] = {
        {"referenceClass","java/lang/ref/Reference"},{"objectClass","java/lang/Object"},
        {"objectArrayClass","[Ljava/lang/Object;"},{"stringClass","java/lang/String"},
        {"byteArrayClass","[B"},{"inputStreamClass","java/io/InputStream"},
        {"outputStreamClass","java/io/OutputStream"},{"fileDescriptorClass","java/io/FileDescriptor"},
        {"booleanClass","java/lang/Boolean"},{"byteClass","java/lang/Byte"},
        {"characterClass","java/lang/Character"},{"doubleClass","java/lang/Double"},
        {"floatClass","java/lang/Float"},{"integerClass","java/lang/Integer"},
        {"longClass","java/lang/Long"},{"shortClass","java/lang/Short"},
        {"fieldClass","java/lang/reflect/Field"},{"methodClass","java/lang/reflect/Method"},
        {"constructorClass","java/lang/reflect/Constructor"},{"calendarClass","java/util/Calendar"},
        {"bigDecimalClass","java/math/BigDecimal"},{"deflaterClass","java/util/zip/Deflater"},
        {"inflaterClass","java/util/zip/Inflater"},{"zipEntryClass","java/util/zip/ZipEntry"},
        {"socketClass","java/net/Socket"},{"socketImplClass","java/net/SocketImpl"},
        {"inetAddressClass","java/net/InetAddress"},{"inet6AddressClass","java/net/Inet6Address"},
        {"inetSocketAddressClass","java/net/InetSocketAddress"},{NULL,NULL}
    };
    void (*initialize_modern_constants)(JNIEnv *) = bsym(h,"_ZN12JniConstants32EnsureClassReferencesInitializedEP7_JNIEnv");
    void (*initialize_api28_constants)(JNIEnv *) = bsym(h,"_ZN12JniConstants4initEP7_JNIEnv");
    if (initialize_modern_constants) {
        framework_api = 29;
        initialize_modern_constants(env);
        if ((*env)->ExceptionCheck(env)) return JNI_FALSE;
        fprintf(stderr,"SDBRIDGE JNI cache=API%d nativehelper\n",framework_api);
    } else if (initialize_api28_constants) {
        framework_api = 28;
        initialize_api28_constants(env);
        if ((*env)->ExceptionCheck(env)) return JNI_FALSE;
        fprintf(stderr,"SDBRIDGE JNI cache=API28 nativehelper\n");
    } else for(int i=0;jni_classes[i][0];i++) {
        char symbol[160];
        snprintf(symbol,sizeof(symbol),"_ZN12JniConstants%zu%sE",strlen(jni_classes[i][0]),jni_classes[i][0]);
        jclass *slot=(jclass *)bsym(h,symbol);
        if(!slot)return JNI_FALSE;
        jclass type=(*env)->FindClass(env,jni_classes[i][1]);
        if(!type)return JNI_FALSE;
        if(!*slot)*slot=(*env)->NewGlobalRef(env,type);
        (*env)->DeleteLocalRef(env,type);
    }
    typedef int (*android_thread_factory)(int (*)(void *), void *, const char *, int32_t, size_t, void **);
    void (*set_thread_factory)(android_thread_factory) = bsym(h,"androidSetCreateThreadFunc");
    android_thread_factory java_thread_factory = bsym(h,"_ZN7android14AndroidRuntime19javaCreateThreadEtcEPFiPvES1_PKcimPS1_");
    if (!set_thread_factory || !java_thread_factory) return JNI_FALSE;
    set_thread_factory(java_thread_factory);

    void* onload = bsym(h, "JNI_OnLoad");
    if (onload) {
        typedef jint (*onload_t)(JavaVM*, void*);
        jint v = ((onload_t)onload)(g_vm, NULL);
        fprintf(stderr, "SDBRIDGE JNI_OnLoad returned 0x%x\n", v);
    } else {
        fprintf(stderr, "SDBRIDGE no JNI_OnLoad in %s\n", path);
    }

    (*env)->ReleaseStringUTFChars(env, jpath, path);
    (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
    return JNI_TRUE;
}


/* Android 的框架 natives 由 app_process 逐个调用 register_android_* 完成注册，
 * libandroid_runtime.so 本身不导出 JNI_OnLoad。这里照同样方式注册常用模块。 */
static const char* kRegEntryPoints[] = {
    "_ZN7android25register_android_util_LogEP7_JNIEnv",
    "_ZN7android30register_android_util_EventLogEP7_JNIEnv",
    "_ZN7android31register_android_os_SystemClockEP7_JNIEnv",
    "_ZN7android36register_android_os_SystemPropertiesEP7_JNIEnv",
    "_ZN7android25register_android_os_TraceEP7_JNIEnv",
    "_Z27register_android_os_ProcessP7_JNIEnv",
    "_ZN7android32register_android_os_FileObserverEP7_JNIEnv",
    "_ZN7android25register_android_os_DebugEP7_JNIEnv",
    "_ZN7android30register_android_os_MemoryFileEP7_JNIEnv",
    "_ZN7android33register_android_view_InputDeviceEP7_JNIEnv",
    "_ZN7android37register_android_view_KeyCharacterMapEP7_JNIEnv",
    "_ZN7android47register_android_animation_PropertyValuesHolderEP7_JNIEnv",
    "_ZN7android32register_android_os_MessageQueueEP7_JNIEnv",
    "_ZN7android34register_android_view_InputChannelEP7_JNIEnv",
    "_ZN7android38register_android_view_InputEventSenderEP7_JNIEnv",
    "_ZN7android40register_android_view_InputEventReceiverEP7_JNIEnv",
    /* Binder/Parcel：ActivityThread 构造要先 new ApplicationThread -> new Binder -> init()，
     * 所以 Binder 的 natives 必须先注册。之前因为没有 Binder.onBinderStrictModePolicyChange
     * （Android 7.0 才加进 Java 类）导致整个注册 abort，才把它从列表里去掉；
     * 现在框架侧已经把这个方法补进去了。 */
    "_Z26register_android_os_BinderP7_JNIEnv",
    /* Parcel：BaseBundle.<clinit> 就会 Parcel.obtain()，
     * 所以 Instrumentation / ActivityThread.attach 离不开它。
     * Java 侧的 nativeSetDataSize 已按本库注册表改成 (JI)V。 */
    "_ZN7android26register_android_os_ParcelEP7_JNIEnv",
    /* Actual API23 SQLite implementation, including CursorWindow queries. */
    "_ZN7android38register_android_database_CursorWindowEP7_JNIEnv",
    "_ZN7android38register_android_database_SQLiteGlobalEP7_JNIEnv",
    "_ZN7android37register_android_database_SQLiteDebugEP7_JNIEnv",
    "_ZN7android42register_android_database_SQLiteConnectionEP7_JNIEnv",
    "_ZN7android33register_android_content_AssetManagerEP7_JNIEnv",
    "_ZN7android33register_android_content_XmlBlockEP7_JNIEnv",
    "_Z33register_android_content_AssetManagerP7_JNIEnv",
    /* 真实符号是 36，不是 34；读资源字符串要用它 */
    "_ZN7android36register_android_content_StringBlockEP7_JNIEnv",
    "_ZN7android32register_android_util_StringBlockP7_JNIEnv",
    "_Z34register_android_graphics_GraphicsP7_JNIEnv",
    "_Z31register_android_graphics_MovieP7_JNIEnv",
    "_Z32register_android_graphics_BitmapP7_JNIEnv",
    "_Z32register_android_graphics_CameraP7_JNIEnv",
    "_Z32register_android_graphics_ShaderP7_JNIEnv",
    "_Z34register_android_graphics_TypefaceP7_JNIEnv",
    "_Z34register_android_graphics_YuvImageP7_JNIEnv",
    "_Z35register_android_graphics_NinePatchP7_JNIEnv",
    "_Z36register_android_graphics_MaskFilterP7_JNIEnv",
    "_Z36register_android_graphics_PathEffectP7_JNIEnv",
    "_Z38register_android_graphics_InterpolatorP7_JNIEnv",
    "_Z39register_android_graphics_BitmapFactoryP7_JNIEnv",
    "_ZN7android33register_android_view_MotionEventEP7_JNIEnv",
    "_ZN7android30register_android_view_KeyEventEP7_JNIEnv",
    "_ZN7android35register_android_emoji_EmojiFactoryEP7_JNIEnv",
    "_ZN7android38register_android_text_AndroidCharacterEP7_JNIEnv",
    "_ZN7android33register_android_text_AndroidBidiEP7_JNIEnv",
    "_ZN7android34register_android_text_StaticLayoutEP7_JNIEnv",
    "_ZN7android37register_android_view_VelocityTrackerEP7_JNIEnv",
    "_ZN7android33register_android_view_PointerIconEP7_JNIEnv",
    "_Z45register_android_graphics_BitmapRegionDecoderP7_JNIEnv",
    "_Z55register_android_graphics_CreateJavaOutputStreamAdaptorP7_JNIEnv",
    "_ZN7android30register_android_graphics_PathEP7_JNIEnv",
    "_ZN7android31register_android_graphics_PaintEP7_JNIEnv",
    "_ZN7android32register_android_graphics_CanvasEP7_JNIEnv",
    "_ZN7android32register_android_graphics_MatrixEP7_JNIEnv",
    "_ZN7android32register_android_graphics_RegionEP7_JNIEnv",
    "_ZN7android33register_android_graphics_PictureEP7_JNIEnv",
    "_ZN7android34register_android_graphics_XfermodeEP7_JNIEnv",
    /* View 构造里 View.<init> 会 RenderNode.create()，这是硬件渲染层的入口。
     * 换成真实的 libhwui 之后（替身只有 13 个符号，根本提供不了 RenderNode），
     * 这两个必须注册。ThreadedRenderer 走 GL，暂时不开。 */
    "_ZN7android32register_android_view_RenderNodeEP7_JNIEnv",
    "_ZN7android40register_android_view_RenderNodeAnimatorEP7_JNIEnv",
    "_ZN7android39register_android_view_DisplayListCanvasEP7_JNIEnv",
    "_ZN7android38register_android_view_ThreadedRendererEP7_JNIEnv",
    "_ZN7android36register_android_graphics_DrawFilterEP7_JNIEnv",
    "_ZN7android36register_android_graphics_FontFamilyEP7_JNIEnv",
    "_ZN7android36register_android_graphics_PorterDuffEP7_JNIEnv",
    "_ZN7android36register_android_graphics_RasterizerEP7_JNIEnv",
    "_ZN7android37register_android_graphics_ColorFilterEP7_JNIEnv",
    "_ZN7android37register_android_graphics_PathMeasureEP7_JNIEnv",
    "_ZN7android39register_android_graphics_pdf_PdfEditorEP7_JNIEnv",
    "_ZN7android40register_android_graphics_CanvasPropertyEP7_JNIEnv",
    "_ZN7android40register_android_graphics_SurfaceTextureEP7_JNIEnv",
    "_ZN7android41register_android_graphics_LayerRasterizerEP7_JNIEnv",
    "_ZN7android41register_android_graphics_pdf_PdfDocumentEP7_JNIEnv",
    "_ZN7android41register_android_graphics_pdf_PdfRendererEP7_JNIEnv",
    "_ZN7android37register_android_content_AssetManagerEP7_JNIEnv",
    NULL
};


static const char *kRegEntryPoints29[] = {
#include "../../native/api29-jni-entries.inc"
    NULL
};
static const char *kRegEntryPoints28[] = {
#include "../../native/api28-jni-entries.inc"
    NULL
};
extern int sd_private_binder_active(void);
extern int sd_memory_install(JNIEnv *env);
extern int sd_event_log_install(JNIEnv *env,void *(*lookup)(const char*));
void *sd_lookup_android(const char *name){
    if(!g_handle)return NULL;
    void *dl=dlopen("libdl_bio.so.0",RTLD_NOW|RTLD_GLOBAL);if(!dl)return NULL;
    bionic_dlsym_t lookup=(bionic_dlsym_t)dlsym(dl,"bionic_dlsym");return lookup?lookup(g_handle,name):NULL;
}
static jstring unavailable_unreachable_memory(JNIEnv *env,jclass cls,jint limit,jboolean contents){
    (void)cls;(void)limit;(void)contents;
    (*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/UnsupportedOperationException"),
        "Native heap reachability inspection is unavailable with the host allocator");
    return NULL;
}
static void (*exchange_fd_owner)(int,uint64_t,uint64_t);
/* Opt-in application diagnostics; the phone's Android logd is not this runtime's
 * logger. Keep these Java Log records in the owning app's existing private log. */
static jint application_log_stderr(JNIEnv *env,jclass type,jint buffer,jint priority,jstring tag,jstring message){
    (void)type;const char *name=tag?(*env)->GetStringUTFChars(env,tag,NULL):NULL;
    const char *value=message?(*env)->GetStringUTFChars(env,message,NULL):NULL;
    if((*env)->ExceptionCheck(env)){if(name)(*env)->ReleaseStringUTFChars(env,tag,name);return -1;}
    int length=value?(int)strlen(value):0;
    fprintf(stderr,"SDANDROID_LOG|buffer=%d|priority=%d|tag=%s|%s\n",buffer,priority,name?name:"",value?value:"");
    if(value)(*env)->ReleaseStringUTFChars(env,message,value);
    if(name)(*env)->ReleaseStringUTFChars(env,tag,name);
    return length;
}
static void core_exchange_fd_owner(JNIEnv *env,jclass cls,jint fd,jlong old,jlong owner){
    (void)env;(void)cls;exchange_fd_owner(fd,(uint64_t)old,(uint64_t)owner);
}

JNIEXPORT jint JNICALL
Java_SdBridge_registerFrameworkNatives(JNIEnv* env, jclass cls) {
    if (!g_handle) return -1;
    const char *failure_capture = getenv("SAILDROID_NATIVE_FAILURE_DIAGNOSTICS");
    if (failure_capture && !strcmp(failure_capture, "1")) {
        void (*capture_failure)(void) = dlsym(RTLD_DEFAULT, "sd_failure_diagnostics_install");
        if (capture_failure) capture_failure();
    }
    void* dl = dlopen("libdl_bio.so.0", RTLD_NOW | RTLD_GLOBAL);
    if (!dl) return -2;
    bionic_dlsym_t bsym = (bionic_dlsym_t) dlsym(dl, "bionic_dlsym");
    if (!bsym) return -3;
    int ok = 0, missing = 0;
    const char **entries=framework_api>=29?kRegEntryPoints29:
        framework_api==28?kRegEntryPoints28:kRegEntryPoints;
    for (int i = 0; entries[i]; ++i) {
        void* fn = bsym(g_handle, entries[i]);
        if (!fn) { missing++; if(framework_api>=28)return -10;continue; }
        int (*reg)(JNIEnv*) = (int (*)(JNIEnv*)) fn;
        int r = reg(env);
        if ((*env)->ExceptionCheck(env)) {
            fprintf(stderr, "SDBRIDGE reg exception in %s:\n", entries[i]);
            (*env)->ExceptionDescribe(env);
            return -11;
        }
        fprintf(stderr, "SDBRIDGE reg %s -> %d\n", entries[i], r);
        if(r<0)return -12;
        ok++;
    }
    fprintf(stderr, "SDBRIDGE registered=%d missing=%d\n", ok, missing);
    if (!sd_private_binder_active()&&register_local_binder(env) < 0) return -4;
    JNINativeMethod naming[]={{"setArgV0","(Ljava/lang/String;)V",standalone_process_name}};
    if((*env)->RegisterNatives(env,(*env)->FindClass(env,"android/os/Process"),naming,1)<0)return -5;
    if(framework_api>=28){
        if(sd_memory_install(env)<0)return -17;
        if(sd_event_log_install(env,sd_lookup_android)<0)return -18;
        fprintf(stderr,"SDEVENTLOG=ready|backend=app-private-file|encoder=android-liblog|capacity=1048576|system_logd=false\n");
        if(getenv("SAILDROID_ANDROID_LOG_STDERR")){
            JNINativeMethod logging={"println_native","(IILjava/lang/String;Ljava/lang/String;)I",application_log_stderr};
            if((*env)->RegisterNatives(env,(*env)->FindClass(env,"android/util/Log"),&logging,1)<0)return -16;
        }
        exchange_fd_owner=dlsym(RTLD_DEFAULT,"bionic_android_fdsan_exchange_owner_tag");
        if(!exchange_fd_owner)return -14;
        JNINativeMethod ownership={"exchangeOwnerTag","(IJJ)V",core_exchange_fd_owner};
        if((*env)->RegisterNatives(env,(*env)->FindClass(env,"libcore/io/IoUtils"),&ownership,1)<0)return -15;
        JNINativeMethod heap={"getUnreachableMemory","(IZ)Ljava/lang/String;",unavailable_unreachable_memory};
        if((*env)->RegisterNatives(env,(*env)->FindClass(env,"android/os/Debug"),&heap,1)<0)return -13;
        jclass timezone = (*env)->FindClass(env, "SdTimeZone");
        if (!timezone) return -19;
        jmethodID install_timezone = (*env)->GetStaticMethodID(env, timezone, "install", "()V");
        if (!install_timezone) return -19;
        (*env)->CallStaticVoidMethod(env, timezone, install_timezone);
        (*env)->DeleteLocalRef(env, timezone);
        if ((*env)->ExceptionCheck(env)) return -19;
        return ok;
    }
    JNINativeMethod cache[]={{"setupShadersDiskCache","(Ljava/lang/String;)V",software_shader_cache}};
    software_graphics_class=(*env)->NewGlobalRef(env,(*env)->FindClass(env,"SdSoftwareGraphics"));
    if(!software_graphics_class)return -6;
    configure_shader_cache=(*env)->GetStaticMethodID(env,software_graphics_class,"configureShaderCache","(Ljava/lang/String;)V");
    if(!configure_shader_cache)return -6;
    if((*env)->RegisterNatives(env,(*env)->FindClass(env,"android/view/ThreadedRenderer"),cache,1)<0)return -6;
    return ok;
}

/* 往 bionic 链接器的搜索路径里追加目录。
 * System.loadLibrary 传进来的是绝对路径，bionic 的 apkenv_open_library 会拿它和
 * 注册过的 LD 路径做 fnmatch，命中才肯直接打开；没注册就报 not found。 */
JNIEXPORT jboolean JNICALL
Java_SdBridge_addBionicLibraryPath(JNIEnv* env, jclass cls, jstring jdirs)
{
    (void)cls;
    void* dl = dlopen("libdl_bio.so.0", RTLD_NOW | RTLD_GLOBAL);
    if (!dl) return JNI_FALSE;
    int (*append)(const char *) = dlsym(dl,"bionic_add_library_path");
    if (!append) return JNI_FALSE;
    const char* dirs = jdirs ? (*env)->GetStringUTFChars(env, jdirs, NULL) : NULL;
    if (dirs) {
        int result=append(dirs);
        (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
        if(result<0)return JNI_FALSE;
    }
    return JNI_TRUE;
}

JNIEXPORT jlong JNICALL
Java_SdBridge_lookupSymbol(JNIEnv* env, jclass cls, jstring jsym) {
    if (!g_handle) return 0;
    void* dl = dlopen("libdl_bio.so.0", RTLD_NOW | RTLD_GLOBAL);
    if (!dl) return 0;
    bionic_dlsym_t bsym = (bionic_dlsym_t) dlsym(dl, "bionic_dlsym");
    if (!bsym) return 0;
    const char* sym = (*env)->GetStringUTFChars(env, jsym, NULL);
    void* p = bsym(g_handle, sym);
    (*env)->ReleaseStringUTFChars(env, jsym, sym);
    return (jlong)(intptr_t)p;
}

/* 原生侧自检：验证 FindClass/CallStaticObjectMethod 路径 */
JNIEXPORT jstring JNICALL
Java_SdBridge_selfTestVmRuntime(JNIEnv* env, jclass cls) {
    char buf[512];
    jclass c = (*env)->FindClass(env, "dalvik/system/VMRuntime");
    if (!c) { (*env)->ExceptionClear(env); return (*env)->NewStringUTF(env, "FindClass=NULL"); }
    jmethodID m = (*env)->GetStaticMethodID(env, c, "getRuntime", "()Ldalvik/system/VMRuntime;");
    if (!m) { (*env)->ExceptionClear(env); return (*env)->NewStringUTF(env, "GetStaticMethodID=NULL"); }
    jobject o = (*env)->CallStaticObjectMethod(env, c, m);
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionDescribe(env); (*env)->ExceptionClear(env);
        snprintf(buf, sizeof(buf), "CallStatic threw (class=%p mid=%p)", (void*)c, (void*)m);
        return (*env)->NewStringUTF(env, buf);
    }
    jobject g = o ? (*env)->NewGlobalRef(env, o) : NULL;
    if ((*env)->ExceptionCheck(env)) { (*env)->ExceptionDescribe(env); (*env)->ExceptionClear(env); }
    snprintf(buf, sizeof(buf), "FindClass=%p mid=%p obj=%p global=%p", (void*)c, (void*)m, o, g);
    return (*env)->NewStringUTF(env, buf);
}

/* 逐项复现 Graphics.cpp 初始化里的 JNI lookup，定位失败点 */
JNIEXPORT jstring JNICALL
Java_SdBridge_checkGraphicsInit(JNIEnv* env, jclass cls) {
    char out[4096]; out[0] = 0;
    char line[256];
#define APP(...) do { snprintf(line, sizeof(line), __VA_ARGS__); strncat(out, line, sizeof(out)-strlen(out)-1); } while (0)
#define CLR() do { if ((*env)->ExceptionCheck(env)) { (*env)->ExceptionClear(env); APP(" [EXC]"); } } while (0)

    jclass c = (*env)->FindClass(env, "android/graphics/Bitmap"); CLR();
    APP("Bitmap=%p", (void*)c);
    jfieldID f = (*env)->GetFieldID(env, c, "mNativePtr", "J"); CLR(); APP(" mNativePtr=%p", (void*)f);
    jmethodID m = (*env)->GetMethodID(env, c, "<init>", "(J[BIIIZZ[BLandroid/graphics/NinePatch$InsetStruct;)V"); CLR(); APP(" ctor=%p", (void*)m);
    m = (*env)->GetMethodID(env, c, "reinit", "(IIZ)V"); CLR(); APP(" reinit=%p", (void*)m);
    m = (*env)->GetMethodID(env, c, "getAllocationByteCount", "()I"); CLR(); APP(" allocCount=%p", (void*)m);

    jclass cc = (*env)->FindClass(env, "android/graphics/Bitmap$Config"); CLR();
    f = (*env)->GetFieldID(env, cc, "nativeInt", "I"); CLR(); APP(" | Config=%p nativeInt=%p", (void*)cc, (void*)f);

    jclass canv = (*env)->FindClass(env, "android/graphics/Canvas"); CLR();
    f = (*env)->GetFieldID(env, canv, "mNativeCanvasWrapper", "J"); CLR(); APP(" | Canvas=%p mNativeCanvasWrapper=%p", (void*)canv, (void*)f);

    jclass pic = (*env)->FindClass(env, "android/graphics/Picture"); CLR();
    f = (*env)->GetFieldID(env, pic, "mNativePicture", "J"); CLR(); APP(" | Picture=%p mNativePicture=%p", (void*)pic, (void*)f);

    jclass reg = (*env)->FindClass(env, "android/graphics/Region"); CLR();
    f = (*env)->GetFieldID(env, reg, "mNativeRegion", "J"); CLR(); APP(" | Region=%p mNativeRegion=%p", (void*)reg, (void*)f);
    m = (*env)->GetMethodID(env, reg, "<init>", "(JI)V"); CLR(); APP(" RegionCtor(JI)=%p", (void*)m);

    jclass brd = (*env)->FindClass(env, "android/graphics/BitmapRegionDecoder"); CLR();
    m = (*env)->GetMethodID(env, brd, "<init>", "(J)V"); CLR(); APP(" | BRD=%p ctor=%p", (void*)brd, (void*)m);

    jclass vm = (*env)->FindClass(env, "dalvik/system/VMRuntime"); CLR();
    jmethodID gm = (*env)->GetStaticMethodID(env, vm, "getRuntime", "()Ldalvik/system/VMRuntime;"); CLR();
    jobject vmo = gm ? (*env)->CallStaticObjectMethod(env, vm, gm) : NULL; CLR();
    jmethodID nm = (*env)->GetMethodID(env, vm, "newNonMovableArray", "(Ljava/lang/Class;I)Ljava/lang/Object;"); CLR();
    jmethodID ao = (*env)->GetMethodID(env, vm, "addressOf", "(Ljava/lang/Object;)J"); CLR();
    APP(" | VMRuntime=%p getRuntime=%p obj=%p newNonMovable=%p addressOf=%p", (void*)vm, (void*)gm, vmo, (void*)nm, (void*)ao);
#undef APP
#undef CLR
    return (*env)->NewStringUTF(env, out);
}


/* ---- 资产层探针 ----
 * Java 侧 new AssetManager() 会先 init 再 ensureSystemAssets()，内部走
 * getStringBlockCount() -> AssetManager::getResources(true)，如果 mResources 没被
 * 载入，getResources 返回 NULL，Java 侧不判空直接 getTableCount -> 空指针。
 * 这里绕开 Java，直接按 C++ 导出符号依次验证：zip 能不能开、AssetManager 能不能构造、
 * addDefaultAssets 返回什么、getResources 是否为空。 */
JNIEXPORT jstring JNICALL
Java_SdBridge_nativeAssetProbe(JNIEnv* env, jclass cls, jstring jdirs)
{
    static char out[2048];
    out[0] = 0;
    char line[400];
#define AP(...) do { snprintf(line, sizeof(line), __VA_ARGS__); \
        strncat(out, line, sizeof(out) - strlen(out) - 1); } while (0)

    const char* dirs = jdirs ? (*env)->GetStringUTFChars(env, jdirs, NULL) : g_libdir;
    char so[1200];
    snprintf(so, sizeof(so), "%s/libandroidfw.so", dirs);

    void* dl = dlopen("libdl_bio.so.0", RTLD_NOW | RTLD_GLOBAL);
    if (!dl) { AP("dlopen libdl_bio 失败"); goto done; }
    bionic_dlopen_t bopen = (bionic_dlopen_t) dlsym(dl, "bionic_dlopen");
    bionic_dlsym_t bsym  = (bionic_dlsym_t)  dlsym(dl, "bionic_dlsym");
    if (!bopen || !bsym) { AP("缺 bionic_dlopen/bionic_dlsym"); goto done; }

    void* h = bopen(so, RTLD_NOW);
    AP("open %s -> %p | ", so, h);
    if (!h) goto done;

    const char* root = getenv("ANDROID_ROOT");
    AP("ANDROID_ROOT=%s | ", root ? root : "(null)");

    {
        typedef void* (*zipopen_t)(const char*);
        zipopen_t zo = (zipopen_t) bsym(h, "_ZN7android9ZipFileRO4openEPKc");
        char apk[1200];
        snprintf(apk, sizeof(apk), "%s/framework/framework-res.apk", root ? root : "");
        if (zo) { void* z = zo(apk); AP("ZipFileRO::open(%s)=%p | ", apk, z); }
        else AP("没有 ZipFileRO::open | ");
    }

    /* ZipFileRO::open 内部就是 open + lseek + mmap，逐步验证是哪一步在设备上挂了 */
    {
        typedef int   (*open_t)(const char*, int, ...);
        typedef long long (*lseek_t)(int, long long, int);
        typedef void* (*mmap_t)(void*, size_t, int, int, int, long long);
        open_t  bopen_f = (open_t)  bsym(h, "open");
        lseek_t blseek  = (lseek_t) bsym(h, "lseek64");
        if (!blseek) blseek = (lseek_t) bsym(h, "lseek");
        mmap_t  bmmap   = (mmap_t)  bsym(h, "mmap");
        char apk3[1200];
        snprintf(apk3, sizeof(apk3), "%s/framework/framework-res.apk", root ? root : "");
        AP("bionic open=%p lseek=%p mmap=%p | ", (void*)bopen_f, (void*)blseek, (void*)bmmap);
        if (bopen_f) {
            int e = 0;
            errno = 0;
            int fd = bopen_f(apk3, 0 /*O_RDONLY*/);
            e = errno;
            AP("bionic open(%s)=%d errno=%d | ", apk3, fd, e);
            if (fd >= 0 && blseek) {
                errno = 0;
                long long len = blseek(fd, 0, 2 /*SEEK_END*/);
                AP("lseek(END)=%lld errno=%d | ", len, errno);
                if (len > 0 && bmmap) {
                    errno = 0;
                    void* m = bmmap(NULL, (size_t)len, 1 /*PROT_READ*/, 2 /*MAP_PRIVATE*/, fd, 0);
                    AP("mmap=%p errno=%d | ", m, errno);
                }
            }
        }
    }
    {
        typedef void   (*ctor_t)(void*, int);
        typedef int    (*adddef_t)(void*);
        typedef const void* (*getres_t)(const void*, int);
        typedef size_t (*tcount_t)(const void*);

        ctor_t   ctor  = (ctor_t)   bsym(h, "_ZN7android12AssetManagerC1ENS0_9CacheModeE");
        adddef_t addd  = (adddef_t) bsym(h, "_ZN7android12AssetManager16addDefaultAssetsEv");
        getres_t getres= (getres_t) bsym(h, "_ZNK7android12AssetManager12getResourcesEb");
        tcount_t tcnt  = (tcount_t) bsym(h, "_ZNK7android8ResTable13getTableCountEv");
        AP("符号 ctor=%p addDefault=%p getResources=%p tableCount=%p | ", (void*)ctor, (void*)addd, (void*)getres, (void*)tcnt);
        if (!ctor || !getres) goto done;

        void* am = malloc(4096);
        memset(am, 0, 4096);
        ctor(am, 0);
        AP("AssetManager(0) 构造完成 am=%p | ", am);
        if (addd) { int added = addd(am); AP("addDefaultAssets()=%d | ", added); }
        else AP("addDefaultAssets 符号缺失 | ");
        {
            typedef void (*s8ctor_t)(void*, const char*);
            typedef int  (*addpath_t)(void*, const void*, int*);
            s8ctor_t s8c = (s8ctor_t) bsym(h, "_ZN7android7String8C1EPKc");
            addpath_t addp = (addpath_t) bsym(h, "_ZN7android12AssetManager12addAssetPathERKNS_7String8EPi");
            AP("String8ctor=%p addAssetPath=%p | ", (void*)s8c, (void*)addp);
            if (s8c && addp) {
                char apk2[1200];
                snprintf(apk2, sizeof(apk2), "%s/framework/framework-res.apk", root ? root : "");
                void* s8 = calloc(1, 64);
                s8c(s8, apk2);
                int cookie = -1;
                int r = addp(am, s8, &cookie);
                AP("addAssetPath(res)=%d cookie=%d | ", r, cookie);
                /* 单变量对照：同一个路径、同一个构造，只有 cookie 参数不同 */
                {
                    void* am2 = malloc(4096);
                    memset(am2, 0, 4096);
                    ctor(am2, 0);
                    void* s8b = calloc(1, 64);
                    s8c(s8b, apk2);
                    int r2 = addp(am2, s8b, NULL);
                    AP("对照 addAssetPath(cookie=NULL)=%d | ", r2);
                    void* s8c2 = calloc(1, 64);
                    s8c(s8c2, apk2);
                    int ck2 = -1;
                    int r3 = addp(am2, s8c2, &ck2);
                    AP("同一 am 再加一次(cookie!=NULL)=%d ck=%d | ", r3, ck2);
                }
                free(s8);
                /* 复现 addDefaultAssets 内部的路径构造：bionic 命名空间下的 getenv + String8::appendPath */
                {
                    typedef char* (*getenv_t)(const char*);
                    typedef void  (*append_t)(void*, const char*);
                    getenv_t genv_b = (getenv_t) bsym(h, "getenv");
                    append_t apnd   = (append_t) bsym(h, "_ZN7android7String810appendPathEPKc");
                    AP("bionic getenv=%p appendPath=%p | ", (void*)genv_b, (void*)apnd);
                    const char* r_b = genv_b ? genv_b("ANDROID_ROOT") : NULL;
                    AP("bionic getenv(ANDROID_ROOT)=%s | ", r_b ? r_b : "(null)");
                    if (apnd && r_b) {
                        void* s8x = calloc(1, 64);
                        s8c(s8x, r_b);
                        apnd(s8x, "framework/framework-res.apk");
                        char** words = (char**) s8x;
                        AP("String8[*0]=%p [*1]=%p | ", (void*)words[0], (void*)words[1]);
                        for (int wi = 0; wi < 2; ++wi) {
                            unsigned long q = (unsigned long) words[wi];
                            if (q > 0x1000 && q < 0x0001000000000000UL) {
                                char tmpb[340];
                                snprintf(tmpb, sizeof(tmpb), "  str[%d]=%s", wi, (char*)q);
                                AP("%s", tmpb);
                            }
                        }
                        void* am3 = malloc(4096);
                        memset(am3, 0, 4096);
                        ctor(am3, 0);
                        int r4 = addp(am3, s8x, NULL);
                        AP(" | 用 appendPath 结果 addAssetPath=%d", r4);
                    }
                }
                const void* res2 = getres(am, 1);
                AP("之后 getResources(true)=%p", res2);
                if (res2 && tcnt) AP(" tableCount=%zu", tcnt(res2));
                AP(" | ");
            }
        }
        const void* res = getres(am, 1);
        AP("getResources(true)=%p | ", res);
        if (res && tcnt) AP("getTableCount()=%zu", tcnt(res));
        free(am);
    }
done:
    if (jdirs) (*env)->ReleaseStringUTFChars(env, jdirs, dirs);
#undef AP
    return (*env)->NewStringUTF(env, out);
}

/* GraphicsEnvironment describes the actual software producer in this host. */
static jclass graphics_environment;
static jmethodID graphics_can_load,graphics_layers,graphics_debug,graphics_stats,graphics_driver,graphics_angle,graphics_hint;
static jint graphics_can_load_system(JNIEnv *e,jclass c){(void)c;return (*e)->CallStaticIntMethod(e,graphics_environment,graphics_can_load);}
static void graphics_layer_paths(JNIEnv *e,jclass c,jobject loader,jstring paths){(void)c;(*e)->CallStaticVoidMethod(e,graphics_environment,graphics_layers,loader,paths);}
static void graphics_debug_layers(JNIEnv *e,jclass c,jstring value){(void)c;(*e)->CallStaticVoidMethod(e,graphics_environment,graphics_debug,value,JNI_FALSE);}
static void graphics_debug_gles(JNIEnv *e,jclass c,jstring value){(void)c;(*e)->CallStaticVoidMethod(e,graphics_environment,graphics_debug,value,JNI_TRUE);}
static void graphics_gpu_stats(JNIEnv *e,jclass c,jstring driver,jstring version,jlong code,jlong time,jstring app,jint vulkan){(void)c;(*e)->CallStaticVoidMethod(e,graphics_environment,graphics_stats,driver,version,code,time,app,vulkan);}
static void graphics_driver_paths(JNIEnv *e,jclass c,jstring path,jstring sphal){(void)c;(*e)->CallStaticVoidMethod(e,graphics_environment,graphics_driver,path,sphal);}
static jboolean graphics_use_angle(JNIEnv *e,jclass c,jstring app){(void)c;return (*e)->CallStaticBooleanMethod(e,graphics_environment,graphics_angle,app);}
static void graphics_launch_hint(JNIEnv *e,jclass c){(void)c;(*e)->CallStaticVoidMethod(e,graphics_environment,graphics_hint);}
JNIEXPORT jboolean JNICALL Java_SdBridge_installGraphicsEnvironment(JNIEnv *e,jclass cls){
    (void)cls;graphics_environment=(*e)->NewGlobalRef(e,(*e)->FindClass(e,"SdGraphicsEnvironment"));if(!graphics_environment)return JNI_FALSE;
#define METHOD(name,signature) (*e)->GetStaticMethodID(e,graphics_environment,name,signature)
    graphics_can_load=METHOD("canLoadSystemLibraries","()I");graphics_layers=METHOD("layers","(Ljava/lang/ClassLoader;Ljava/lang/String;)V");graphics_debug=METHOD("debug","(Ljava/lang/String;Z)V");graphics_stats=METHOD("stats","(Ljava/lang/String;Ljava/lang/String;JJLjava/lang/String;I)V");graphics_driver=METHOD("driver","(Ljava/lang/String;Ljava/lang/String;)V");graphics_angle=METHOD("angle","(Ljava/lang/String;)Z");graphics_hint=METHOD("hint","()V");
#undef METHOD
    if((*e)->ExceptionCheck(e))return JNI_FALSE;
    if(framework_api==28){
        JNINativeMethod methods[]={{"setLayerPaths","(Ljava/lang/ClassLoader;Ljava/lang/String;)V",graphics_layer_paths},{"setDebugLayers","(Ljava/lang/String;)V",graphics_debug_layers}};
        return (*e)->RegisterNatives(e,(*e)->FindClass(e,"android/os/GraphicsEnvironment"),methods,sizeof(methods)/sizeof(methods[0]))==0?JNI_TRUE:JNI_FALSE;
    }
    JNINativeMethod methods[]={{"getCanLoadSystemLibraries","()I",graphics_can_load_system},{"setLayerPaths","(Ljava/lang/ClassLoader;Ljava/lang/String;)V",graphics_layer_paths},{"setDebugLayers","(Ljava/lang/String;)V",graphics_debug_layers},{"setDebugLayersGLES","(Ljava/lang/String;)V",graphics_debug_gles},{"setGpuStats","(Ljava/lang/String;Ljava/lang/String;JJLjava/lang/String;I)V",graphics_gpu_stats},{"setDriverPathAndSphalLibraries","(Ljava/lang/String;Ljava/lang/String;)V",graphics_driver_paths},{"getShouldUseAngle","(Ljava/lang/String;)Z",graphics_use_angle},{"hintActivityLaunch","()V",graphics_launch_hint}};
    return (*e)->RegisterNatives(e,(*e)->FindClass(e,"android/os/GraphicsEnvironment"),methods,sizeof(methods)/sizeof(methods[0]))==0?JNI_TRUE:JNI_FALSE;
}
/* Explicit VM diagnostic only: preserve exit status and expose its Java caller. */
static void diagnostic_runtime_exit(JNIEnv *e,jclass cls,jint status){
    (void)cls;jclass thread=(*e)->FindClass(e,"java/lang/Thread");jmethodID dump=thread?(*e)->GetStaticMethodID(e,thread,"dumpStack","()V"):NULL;
    if(dump)(*e)->CallStaticVoidMethod(e,thread,dump);fflush(NULL);_exit(status);
}
static jstring (*diagnostic_native_load)(JNIEnv *,jstring,jobject,jclass);
static jstring diagnostic_runtime_load(JNIEnv *e,jclass cls,jstring file,jobject loader,jclass caller){
    (void)cls;
    jstring result=diagnostic_native_load(e,file,loader,caller);
    if((*e)->ExceptionCheck(e)){
        jthrowable failure=(*e)->ExceptionOccurred(e);
        (*e)->ExceptionDescribe(e);
        (*e)->ExceptionClear(e);
        (*e)->Throw(e,failure);
        (*e)->DeleteLocalRef(e,failure);
    }
    if(result&&!(*e)->ExceptionCheck(e)){
        const char *reason=(*e)->GetStringUTFChars(e,result,NULL);
        if(reason){fprintf(stderr,"SD_VM_NATIVE_LOAD_FAILED=%s\n",reason);(*e)->ReleaseStringUTFChars(e,result,reason);}
    }
    return result;
}
JNIEXPORT void JNICALL Java_SdBridge_installExitDiagnostics(JNIEnv *e,jclass cls){
    void (*failure_diagnostics)(void)=dlsym(RTLD_DEFAULT,"sd_failure_diagnostics_install");
    if(failure_diagnostics)failure_diagnostics();
    (void)cls;JNINativeMethod method={"nativeExit","(I)V",diagnostic_runtime_exit};(*e)->RegisterNatives(e,(*e)->FindClass(e,"java/lang/Runtime"),&method,1);
    diagnostic_native_load=dlsym(RTLD_DEFAULT,"JVM_NativeLoad");
    if(!diagnostic_native_load){
        void *jvm=dlopen("libopenjdkjvm.so",RTLD_NOW|RTLD_NOLOAD);
        if(jvm)diagnostic_native_load=dlsym(jvm,"JVM_NativeLoad");
    }
    fprintf(stderr,"SD_VM_NATIVE_LOAD_DIAGNOSTICS=%s\n",diagnostic_native_load?"enabled":"unavailable");
    if(diagnostic_native_load){
        JNINativeMethod load={"nativeLoad","(Ljava/lang/String;Ljava/lang/ClassLoader;Ljava/lang/Class;)Ljava/lang/String;",diagnostic_runtime_load};
        (*e)->RegisterNatives(e,(*e)->FindClass(e,"java/lang/Runtime"),&load,1);
    }
}
