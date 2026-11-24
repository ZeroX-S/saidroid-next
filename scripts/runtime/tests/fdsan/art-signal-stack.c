#define _GNU_SOURCE
#include <jni.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <errno.h>

typedef struct { JavaVM *vm; int checks; int error; } Context;
static int has_perms(uintptr_t first,uintptr_t last,const char *expected){
    FILE *f=fopen("/proc/self/maps","r"); if(!f)return 0;
    char line[1024],perms[5];unsigned long a,b;uintptr_t covered=first;
    while(fgets(line,sizeof(line),f)){
        if(sscanf(line,"%lx-%lx %4s",&a,&b,perms)!=3)continue;
        if(a<=covered&&b>covered){
            if(strncmp(perms,expected,3)){fclose(f);return 0;}
            covered=b;if(covered>=last){fclose(f);return 1;}
        }
    }
    fclose(f);return 0;
}
static void *exercise(void *opaque){
    Context *c=opaque;JNIEnv *env=NULL;stack_t ss;
    if((*c->vm)->AttachCurrentThread(c->vm,(void **)&env,NULL)!=JNI_OK){c->error=1;return NULL;}
    long page=sysconf(_SC_PAGESIZE);
    if(page<=0||sigaltstack(NULL,&ss)||ss.ss_flags&SS_DISABLE||ss.ss_size<256*1024||ss.ss_size%(size_t)page){c->error=2;goto detach;}
    c->checks++;
    uintptr_t base=(uintptr_t)ss.ss_sp;size_t size=ss.ss_size;
    if(!has_perms(base,base+size,"rw-")){c->error=3;goto detach;}c->checks++;
    if(!has_perms(base-page,base,"---")||!has_perms(base+size,base+size+page,"---")){c->error=4;goto detach;}c->checks++;
    if((*c->vm)->DetachCurrentThread(c->vm)!=JNI_OK){c->error=5;return NULL;}
    if(sigaltstack(NULL,&ss)||!(ss.ss_flags&SS_DISABLE)){c->error=6;return NULL;}c->checks++;
    for(uintptr_t p=base-page;p<base+size+page;p+=page){
        unsigned char resident;errno=0;
        if(mincore((void *)p,page,&resident)!=-1||errno!=ENOMEM){c->error=7;return NULL;}
    }
    c->checks++;return NULL;
detach:
    (*c->vm)->DetachCurrentThread(c->vm);return NULL;
}
JNIEXPORT jint JNICALL Java_ArtSignalStackContract_exerciseNativeThreads(JNIEnv *env,jclass type){
    (void)type;Context c={0};if((*env)->GetJavaVM(env,&c.vm)!=JNI_OK)return -1;
    for(int i=0;i<64;i++){
        pthread_t thread;if(pthread_create(&thread,NULL,exercise,&c))return -2;
        if(pthread_join(thread,NULL))return -3;if(c.error)return -100-c.error;
    }
    return c.checks;
}
