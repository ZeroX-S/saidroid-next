#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <limits.h>
#include <stddef.h>
#include <malloc.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <unistd.h>
#include <netdb.h>
#include <jni.h>
#include <pthread.h>

/* NDK bitmap ABI entry points used by QQ's APNG decoder. Keep a temporary
 * native pixel buffer per locked Java Bitmap and copy it through the public
 * Bitmap Buffer API on unlock. This preserves the NDK contract without
 * dereferencing Android's private native Bitmap pointer. */
struct AndroidBitmapInfo { uint32_t width,height,stride,format,flags; };
struct bitmap_lock { jobject bitmap; void *pixels; size_t size; struct bitmap_lock *next; };
static pthread_mutex_t bitmap_lock_mutex=PTHREAD_MUTEX_INITIALIZER;
static struct bitmap_lock *bitmap_locks;
static jmethodID bm_width,bm_height,bm_stride,bm_config,bm_copy_to,bm_copy_from;
static jmethodID cfg_text;
static jclass bm_class,cfg_class;
static int bitmap_methods(JNIEnv *env,jobject bitmap){
    if(bm_width)return 1;
    jclass local=(*env)->GetObjectClass(env,bitmap);if(!local)return 0;
    bm_class=(*env)->NewGlobalRef(env,local);(*env)->DeleteLocalRef(env,local);
    bm_width=(*env)->GetMethodID(env,bm_class,"getWidth","()I");
    bm_height=(*env)->GetMethodID(env,bm_class,"getHeight","()I");
    bm_stride=(*env)->GetMethodID(env,bm_class,"getRowBytes","()I");
    bm_config=(*env)->GetMethodID(env,bm_class,"getConfig","()Landroid/graphics/Bitmap$Config;");
    bm_copy_to=(*env)->GetMethodID(env,bm_class,"copyPixelsToBuffer","(Ljava/nio/Buffer;)V");
    bm_copy_from=(*env)->GetMethodID(env,bm_class,"copyPixelsFromBuffer","(Ljava/nio/Buffer;)V");
    return bm_width&&bm_height&&bm_stride&&bm_config&&bm_copy_to&&bm_copy_from;
}
int AndroidBitmap_getInfo(JNIEnv *env,jobject bitmap,struct AndroidBitmapInfo *info){
    if(!env||!bitmap||!info||!bitmap_methods(env,bitmap))return -2;
    int width=(*env)->CallIntMethod(env,bitmap,bm_width),height=(*env)->CallIntMethod(env,bitmap,bm_height),stride=(*env)->CallIntMethod(env,bitmap,bm_stride);
    jobject config=(*env)->CallObjectMethod(env,bitmap,bm_config);uint32_t format=1;
    if(config){jclass c=(*env)->GetObjectClass(env,config);if(!cfg_text)cfg_text=(*env)->GetMethodID(env,c,"toString","()Ljava/lang/String;");jstring text=cfg_text?(jstring)(*env)->CallObjectMethod(env,config,cfg_text):NULL;const char *name=text?(*env)->GetStringUTFChars(env,text,NULL):NULL;if(name&&strstr(name,"RGB_565"))format=4;if(name&&text)(*env)->ReleaseStringUTFChars(env,text,name);if(text)(*env)->DeleteLocalRef(env,text);(*env)->DeleteLocalRef(env,c);(*env)->DeleteLocalRef(env,config);}
    if((*env)->ExceptionCheck(env)){(*env)->ExceptionClear(env);return -2;}
    info->width=width;info->height=height;info->stride=stride;info->format=format;info->flags=0;return 0;
}
int AndroidBitmap_lockPixels(JNIEnv *env,jobject bitmap,void **address){
    struct AndroidBitmapInfo info;if(!address||AndroidBitmap_getInfo(env,bitmap,&info)!=0)return -2;
    pthread_mutex_lock(&bitmap_lock_mutex);for(struct bitmap_lock *at=bitmap_locks;at;at=at->next)if((*env)->IsSameObject(env,at->bitmap,bitmap)){*address=at->pixels;pthread_mutex_unlock(&bitmap_lock_mutex);return 0;}
    size_t size=(size_t)info.stride*info.height;void *pixels=malloc(size);if(!pixels){pthread_mutex_unlock(&bitmap_lock_mutex);return -1;}
    jobject buffer=(*env)->NewDirectByteBuffer(env,pixels,size);if(!buffer){free(pixels);pthread_mutex_unlock(&bitmap_lock_mutex);return -2;}
    (*env)->CallVoidMethod(env,bitmap,bm_copy_to,buffer);(*env)->DeleteLocalRef(env,buffer);if((*env)->ExceptionCheck(env)){(*env)->ExceptionClear(env);free(pixels);pthread_mutex_unlock(&bitmap_lock_mutex);return -2;}
    struct bitmap_lock *saved=calloc(1,sizeof(*saved));if(!saved){free(pixels);pthread_mutex_unlock(&bitmap_lock_mutex);return -1;}saved->bitmap=(*env)->NewGlobalRef(env,bitmap);saved->pixels=pixels;saved->size=size;saved->next=bitmap_locks;bitmap_locks=saved;*address=pixels;pthread_mutex_unlock(&bitmap_lock_mutex);return 0;
}
int AndroidBitmap_unlockPixels(JNIEnv *env,jobject bitmap){
    pthread_mutex_lock(&bitmap_lock_mutex);struct bitmap_lock **slot=&bitmap_locks;while(*slot&&!(*env)->IsSameObject(env,(*slot)->bitmap,bitmap))slot=&(*slot)->next;if(!*slot){pthread_mutex_unlock(&bitmap_lock_mutex);return -2;}struct bitmap_lock *saved=*slot;*slot=saved->next;pthread_mutex_unlock(&bitmap_lock_mutex);
    jobject buffer=(*env)->NewDirectByteBuffer(env,saved->pixels,saved->size);if(buffer){(*env)->CallVoidMethod(env,bitmap,bm_copy_from,buffer);(*env)->DeleteLocalRef(env,buffer);}int result=(*env)->ExceptionCheck(env)?-2:0;if(result)(*env)->ExceptionClear(env);(*env)->DeleteGlobalRef(env,saved->bitmap);free(saved->pixels);free(saved);return result;
}

/* Android 10 libc ABI extensions for a glibc-owned process. This library does
 * not replace either allocator or claim Android heap-inspection support. */
extern char *program_invocation_name;

/* Bionic LP64 mallinfo has ten size_t fields. glibc's legacy mallinfo uses
 * ten int fields, while mallinfo2 has the matching wide return ABI. Include
 * mmap-backed allocations in Android's total and allocated heap getters. */
struct mallinfo2 bionic_mallinfo(void) {
    _Static_assert(sizeof(size_t)==8, "Bionic LP64 mallinfo required");
    _Static_assert(sizeof(struct mallinfo2)==10*sizeof(size_t), "mallinfo2 ABI differs");
    _Static_assert(offsetof(struct mallinfo2,usmblks)==5*sizeof(size_t), "mallinfo total offset differs");
    _Static_assert(offsetof(struct mallinfo2,uordblks)==7*sizeof(size_t), "mallinfo allocated offset differs");
    _Static_assert(offsetof(struct mallinfo2,fordblks)==8*sizeof(size_t), "mallinfo free offset differs");
    struct mallinfo2 info=mallinfo2();
    info.usmblks=info.arena+info.hblkhd;
    info.uordblks+=info.hblkhd;
    return info;
}

const char *bionic_getprogname(void) {
    // ART changes argv[0] to Android's process name. glibc's cached short-name
    // pointer can then point beyond the new string, especially for private ART
    // paths; derive the basename from the current argv storage instead.
    const char *name=program_invocation_name;
    if(!name)return "";
    const char *slash=strrchr(name,'/');
    return slash?slash+1:name;
}

/* android_dlwarning drains Bionic's deferred linker-deprecation warning queue.
 * This compatibility linker has no such queue: it reports load errors through
 * dlerror and emits its own diagnostics immediately. An empty warning stream
 * must not consume dlerror, hide a failed load, or invent an Activity warning. */
void bionic_android_dlwarning(void *cookie,void (*callback)(void *,const char *)) {
    (void)cookie;(void)callback;
}

/* Use the host resolver for the default network. Explicit Android netIds and
 * fwmarks have no host routing equivalent and must fail rather than leak onto
 * another network. The existing translator owns the addrinfo ABI conversion. */
struct bionic_addrinfo;
int bionic_android_getaddrinfofornet(const char *host,const char *service,
        const struct bionic_addrinfo *hints,unsigned netid,unsigned mark,
        struct bionic_addrinfo **result) {
    if(!result){errno=EINVAL;return EAI_SYSTEM;}
    *result=NULL;
    if(netid||mark){errno=ENONET;return EAI_SYSTEM;}
    int (*resolve)(const char *,const char *,const struct bionic_addrinfo *,
            struct bionic_addrinfo **)=dlsym(RTLD_DEFAULT,"bionic_getaddrinfo");
    if(!resolve){errno=ENOSYS;return EAI_SYSTEM;}
    return resolve(host,service,hints,result);
}

/* libhybris's linker exports DATA named bionic___system_properties_init.
 * Its own relocation must never bind that variable to this function. Our
 * translator resolves Android's function through this private override name. */
int saildroid_bionic___system_properties_init(void) {
    unsigned (*serial)(void)=dlsym(RTLD_DEFAULT,"bionic___system_property_area_serial");
    if (!serial) { errno=ENOSYS;return -1; }
    (void)serial(); /* Initializes the actual process-private property table. */
    return 0;
}
void bionic___system_property_read_callback(const void *property,
        void (*callback)(void *,const char *,const char *,uint32_t),void *cookie) {
    int (*read_property)(const void *,char *,char *)=dlsym(RTLD_DEFAULT,"bionic___system_property_read");
    unsigned (*serial)(const void *)=dlsym(RTLD_DEFAULT,"bionic___system_property_serial");
    if (!property||!callback||!read_property||!serial) { errno=EINVAL;return; }
    char name[256]={0},value[92]={0};
    read_property(property,name,value);callback(cookie,name,value,serial(property));
}

/* glibc exposes no supported allocation-address walk or allocator freeze API.
 * malloc_iterate's documented failure path is used instead of inventing a list
 * of live allocations. The Java Debug facade must expose this as unavailable. */
static void unavailable_heap_walk(void) {
    static atomic_flag reported=ATOMIC_FLAG_INIT;
    if(!atomic_flag_test_and_set(&reported))
        fputs("API29_CAPABILITY=unavailable|name=allocator-address-walk|host=glibc\n",stderr);
    errno=ENOTSUP;
}
int bionic_malloc_iterate(uintptr_t base,size_t size,
        void (*callback)(uintptr_t,size_t,void *),void *argument) {
    (void)base;(void)size;(void)callback;(void)argument;
    unavailable_heap_walk();return -1;
}
void bionic_malloc_disable(void) { unavailable_heap_walk(); }
void bionic_malloc_enable(void) { unavailable_heap_walk(); }
size_t bionic_malloc_backtrace(void *pointer,uintptr_t *frames,size_t count) {
    (void)pointer;(void)frames;(void)count;
    // Bionic also returns zero when allocation backtrace recording is disabled.
    return 0;
}

int bionic_android_mallopt(int operation,void *argument,size_t length) {
    // Android's extended allocator controls are optional and return false when
    // the requested control is not supported by the active allocator.
    (void)operation;(void)argument;(void)length;errno=ENOTSUP;return 0;
}
ssize_t bionic___pwrite64_chk(int fd,const void *buffer,size_t count,
        off64_t offset,size_t buffer_size) {
    if(count>(size_t)SSIZE_MAX||count>buffer_size){fputs("pwrite64: invalid count or buffer size exceeded\n",stderr);abort();}
    return pwrite64(fd,buffer,count,offset);
}

/* AArch64 uses 64-bit off_t for both API29 fortified entry points. */
ssize_t bionic___pwrite_chk(int fd,const void *buffer,size_t count,
        off_t offset,size_t buffer_size) {
    _Static_assert(sizeof(off_t)==sizeof(off64_t), "AArch64 off_t required");
    return bionic___pwrite64_chk(fd,buffer,count,(off64_t)offset,buffer_size);
}
