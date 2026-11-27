#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>

/* Cross-DSO CFI dispatch for the private Android link map. Checked DSOs own
 * their __cfi_check implementation; ordinary non-CFI DSOs are the ABI's
 * unchecked case. Anonymous/unmapped pointers are never accepted. */
static void reject(uint64_t type, void *target) {
    fprintf(stderr,"SAILDROID_CFI=invalid-target|type=%llu|target=%p\n",
            (unsigned long long)type,target);
    abort();
}
typedef int (*private_check_fn)(uint64_t,void *,void *);
typedef int (*addr_fn)(const void *,Dl_info *);
typedef void *(*open_fn)(const char *,int);
typedef void *(*symbol_fn)(void *,const char *);
typedef int (*close_fn)(void *);
static pthread_once_t loader_once=PTHREAD_ONCE_INIT;
static private_check_fn private_check,hardware_check;
static addr_fn android_addr;
static open_fn android_open;
static symbol_fn android_symbol;
static close_fn android_close;
static void resolve_loader(void) {
    /* These are component-loader entry points with process lifetime. Target
     * mappings/checkers are always resolved afresh by the locked loader API. */
    private_check=(private_check_fn)dlsym(RTLD_DEFAULT,"bionic_cfi_check");
    hardware_check=(private_check_fn)dlsym(RTLD_DEFAULT,"sd_hardware_cfi");
    android_addr=(addr_fn)dlsym(RTLD_DEFAULT,"bionic_dladdr");
    android_open=(open_fn)dlsym(RTLD_DEFAULT,"bionic_dlopen");
    android_symbol=(symbol_fn)dlsym(RTLD_DEFAULT,"bionic_dlsym");
    android_close=(close_fn)dlsym(RTLD_DEFAULT,"bionic_dlclose");
}
static void cfi_dispatch(uint64_t type, void *target, void *diagnostic) {
    Dl_info owner={0},checker={0};
    if(!target)reject(type,target);
    pthread_once(&loader_once,resolve_loader);
    if(private_check){int result=private_check(type,target,diagnostic);if(result<0)reject(type,target);if(result>0)return;}
    if(hardware_check){int result=hardware_check(type,target,diagnostic);if(result<0)reject(type,target);if(result>0)return;}

    int found=android_addr?android_addr(target,&owner):dladdr(target,&owner);
    if(!found||!owner.dli_fname||!owner.dli_fbase)reject(type,target);
    void *handle=NULL,*check=NULL;
    int android=android_open&&android_symbol&&android_close&&android_addr;
    if(android){handle=android_open(owner.dli_fname,RTLD_NOW|RTLD_NOLOAD);if(handle)check=android_symbol(handle,"__cfi_check");}
    else{handle=dlopen(owner.dli_fname,RTLD_NOW|RTLD_NOLOAD);if(handle)check=dlsym(handle,"__cfi_check");}
    if(!handle)reject(type,target);
    if(check){
        int same=android?android_addr(check,&checker):dladdr(check,&checker);
        if(same&&checker.dli_fbase==owner.dli_fbase)
            ((void (*)(uint64_t,void *,void *))check)(type,target,diagnostic);
        /* A dependency's checker does not make this DSO CFI-instrumented. */
    }
    if(android)android_close(handle);else dlclose(handle);
}
static pthread_once_t timing_once=PTHREAD_ONCE_INIT;
static int timing_enabled;
static void configure_timing(void) {
    const char *value=getenv("SAILDROID_CFI_TIMING_DIAGNOSTIC");
    timing_enabled=value&&!strcmp(value,"1");
}
void __cfi_slowpath_diag(uint64_t type, void *target, void *diagnostic) {
    pthread_once(&timing_once,configure_timing);
    if(!timing_enabled){cfi_dispatch(type,target,diagnostic);return;}
    struct timespec before,after;
    clock_gettime(CLOCK_MONOTONIC,&before);
    cfi_dispatch(type,target,diagnostic);
    clock_gettime(CLOCK_MONOTONIC,&after);
    static _Thread_local uint64_t calls,nanoseconds;
    calls++;
    nanoseconds+=(uint64_t)((after.tv_sec-before.tv_sec)*1000000000LL+after.tv_nsec-before.tv_nsec);
    if(calls==1||!(calls&4095))
        fprintf(stderr,"SAILDROID_CFI_TIMING=sample|thread=%lu|calls=%llu|dispatch_ns=%llu\n",
                (unsigned long)pthread_self(),(unsigned long long)calls,(unsigned long long)nanoseconds);
}
void __cfi_slowpath(uint64_t type, void *target) {
    __cfi_slowpath_diag(type,target,NULL);
}
