#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifndef SD_HOST_LOADER_LIBRARY
#define SD_HOST_LOADER_LIBRARY "/usr/lib64/libhybris-common.so.1"
#endif
#ifndef SD_HOST_VNDK_LIBRARY
#define SD_HOST_VNDK_LIBRARY "/system/lib64/libvndksupport.so"
#endif

/* Hardware HALs belong to the running phone's Android linker, libc and HIDL
 * dependency graph. Delegate the public C SP-HAL API to that graph. A private
 * namespace is never represented by a fabricated pointer or a global search
 * path. Only handles returned by the actual host loader cross this boundary. */
static pthread_once_t once=PTHREAD_ONCE_INIT;
static pthread_mutex_t lock=PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP;
static void *(*host_open)(const char *,int);
static void *(*host_symbol)(void *,const char *);
static int (*host_close)(void *);
static int (*host_addr)(const void *,Dl_info *);
static const char *(*host_error)(void);
static void *(*host_sphal_open)(const char *,int);
static int (*host_sphal_close)(void *);
static void *host_vndk;
static _Thread_local char last_error[512];
static void remember_error(const char *message) {
    snprintf(last_error,sizeof(last_error),"%s",message?message:"Host Android hardware loader failed");
}
const char *sd_hardware_error(void) {
    static _Thread_local char result[512];
    if(!last_error[0])return NULL;
    memcpy(result,last_error,sizeof(result));last_error[0]=0;return result;
}
struct handle {void *value;unsigned references;struct handle *next;};
static struct handle *handles;
static int trusted(const char *path) {
    struct stat st;
    return !stat(path,&st)&&S_ISREG(st.st_mode)&&st.st_uid==0&&!(st.st_mode&022);
}
static void initialize(void) {
    if(!trusted(SD_HOST_LOADER_LIBRARY)||!trusted(SD_HOST_VNDK_LIBRARY))return;
    void *library=dlopen(SD_HOST_LOADER_LIBRARY,RTLD_NOW|RTLD_LOCAL);
    if(!library)return;
    host_open=dlsym(library,"android_dlopen");
    host_symbol=dlsym(library,"android_dlsym");
    host_close=dlsym(library,"android_dlclose");
    host_addr=dlsym(library,"android_dladdr");
    host_error=dlsym(library,"android_dlerror");
    if(!host_open||!host_symbol||!host_close||!host_addr||!host_error)return;
    host_vndk=host_open(SD_HOST_VNDK_LIBRARY,RTLD_NOW);
    if(!host_vndk)return;
    host_sphal_open=host_symbol(host_vndk,"android_load_sphal_library");
    host_sphal_close=host_symbol(host_vndk,"android_unload_sphal_library");
}
static struct handle **find(void *value) {
    struct handle **entry=&handles;
    while(*entry&&(*entry)->value!=value)entry=&(*entry)->next;
    return entry;
}
void *bionic_android_load_sphal_library(const char *name,int flags) {
    pthread_once(&once,initialize);last_error[0]=0;
    if(!name||!host_sphal_open||!host_sphal_close){
        remember_error("Host SP-HAL API unavailable");
        fputs("SDHARDWARE_LOADER=unavailable|reason=host-sphal-api\n",stderr);return NULL;
    }
    pthread_mutex_lock(&lock);
    void *value=host_sphal_open(name,flags);
    if(value){
        struct handle **entry=find(value);
        if(!*entry){*entry=calloc(1,sizeof(**entry));if(!*entry){host_sphal_close(value);value=NULL;}else(*entry)->value=value;}
        if(value)(*entry)->references++;
    }
    const char *error=value?NULL:host_error();
    if(!value)remember_error(error);
    fprintf(stderr,"SDHARDWARE_LOADER=%s|library=%s|source=host-sphal-api%s%s\n",
            value?"loaded":"failed",name,value?"":"|error=",value?"":error?error:"unavailable");
    pthread_mutex_unlock(&lock);
    return value;
}
/* Called by the private linker before it interprets an opaque handle. Return
 * zero only when this registry does not own the handle. NULL symbol results
 * and close failures remain actual host results, rather than glibc fallbacks. */
int sd_hardware_symbol(void *handle,const char *name,void **result) {
    pthread_mutex_lock(&lock);struct handle **entry=find(handle);
    int found=*entry!=NULL;
    if(found){last_error[0]=0;*result=name?host_symbol(handle,name):NULL;if(!*result)remember_error(name?host_error():"NULL hardware symbol name");}
    pthread_mutex_unlock(&lock);return found;
}
int sd_hardware_close(void *handle,int *result) {
    pthread_mutex_lock(&lock);struct handle **entry=find(handle);
    int found=*entry!=NULL;
    if(found){last_error[0]=0;*result=host_sphal_close(handle);if(*result)remember_error(host_error());if(!*result&&!--(*entry)->references){struct handle *old=*entry;*entry=old->next;free(old);}}
    pthread_mutex_unlock(&lock);return found;
}
int bionic_android_unload_sphal_library(void *handle) {
    int result=-1;return sd_hardware_close(handle,&result)?result:-1;
}
/* dladdr and cross-DSO CFI use the same real Android link map. The host API
 * can also recognize glibc objects; leave those to the private linker's normal
 * glibc fallback, and never declare a private Android mapping to be foreign. */
int sd_hardware_address(const void *target,Dl_info *owner) {
    pthread_once(&once,initialize);
    if(!host_addr||!host_addr(target,owner)||!owner->dli_fname)return 0;
    const char *name=owner->dli_fname;
    return !strncmp(name,"/system/lib64/",14)||!strncmp(name,"/vendor/lib64/",14)||!strncmp(name,"/odm/lib64/",11);
}
int sd_hardware_cfi(uint64_t type,void *target,void *diagnostic) {
    Dl_info owner={0},checker={0};
    if(!sd_hardware_address(target,&owner))return 0;
    void *handle=host_open(owner.dli_fname,RTLD_NOW|RTLD_NOLOAD);
    if(!handle)return -1;
    void *check=host_symbol(handle,"__cfi_check");
    if(check&&host_addr(check,&checker)&&checker.dli_fbase==owner.dli_fbase)
        ((void (*)(uint64_t,void *,void *))check)(type,target,diagnostic);
    host_close(handle);return 1;
}
