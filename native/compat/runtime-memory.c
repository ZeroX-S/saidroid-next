/* SPDX-License-Identifier: Apache-2.0
 * MemoryInfo's category/metric layout follows AOSP android-10.0.0_r1
 * frameworks/base/core/jni/android_os_Debug.cpp (Copyright The Android Open
 * Source Project). Measurements come from Linux smaps; no Android memtrack
 * service, host servicemanager, or device driver is queried.
 */
#define _GNU_SOURCE
#include <jni.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <limits.h>
#include <unistd.h>
#include <errno.h>

enum { UNKNOWN,DALVIK,NATIVE,DALVIK_OTHER,STACK,CURSOR,ASHMEM,GL_DEV,UNKNOWN_DEV,
    SO,JAR,APK,TTF,DEX,OAT,ART,UNKNOWN_MAP,GRAPHICS,GL,MEMTRACK,
    DALVIK_NORMAL,DALVIK_LARGE,DALVIK_ZYGOTE,DALVIK_NON_MOVING,LINEAR,
    ACCOUNTING,CODE_CACHE,COMPILER,INDIRECT,BOOT_VDEX,APP_DEX,APP_VDEX,APP_ART,BOOT_ART,HEAPS };
enum { PSS,SWAPPABLE,RSS,PRIVATE_DIRTY,SHARED_DIRTY,PRIVATE_CLEAN,SHARED_CLEAN,SWAP,SWAP_PSS,METRICS };
struct memory {uint64_t heap[HEAPS][METRICS];int swap_pss;};
static jfieldID fields[3][METRICS],other_stats,has_swap_pss;
static int ends(const char *name,const char *suffix){size_t n=strlen(name),s=strlen(suffix);return n>=s&&!strcmp(name+n-s,suffix);}
static int classify(char *name,int *sub,int *swappable){
    *sub=-1;*swappable=0;name[strcspn(name,"\n")]=0;
    if(ends(name," (deleted)"))name[strlen(name)-10]=0;
    if(!strncmp(name,"[heap]",6)||!strncmp(name,"[anon:libc_malloc",17))return NATIVE;
    if(!strncmp(name,"[stack",6))return STACK;
    int type=UNKNOWN;
    if(strstr(name,".so"))type=SO;
    else if(ends(name,".jar"))type=JAR;
    else if(ends(name,".apk"))type=APK;
    else if(ends(name,".ttf")||ends(name,".otf"))type=TTF;
    else if(ends(name,".vdex")){type=DEX;*sub=strstr(name,"@boot")||strstr(name,"/boot")?BOOT_VDEX:APP_VDEX;}
    else if(strstr(name,".dex")||ends(name,".odex")){type=DEX;*sub=APP_DEX;}
    else if(ends(name,".oat"))type=OAT;
    else if(ends(name,".art")||ends(name,".art]")){type=ART;*sub=strstr(name,"@boot")||strstr(name,"/boot")?BOOT_ART:APP_ART;}
    if(type!=UNKNOWN){*swappable=1;return type;}
    if(!strncmp(name,"/dev/kgsl-3d0",13))return GL_DEV;
    if(!strncmp(name,"/dev/ashmem/CursorWindow",23))return CURSOR;
    if(!strncmp(name,"/dev/ashmem",11))return ASHMEM;
    if(!strncmp(name,"/dev/",5))return UNKNOWN_DEV;
    if(!strncmp(name,"[anon:dalvik-",13)){
        if(strstr(name,"alloc space")||strstr(name,"main space")){*sub=DALVIK_NORMAL;return DALVIK;}
        if(strstr(name,"large object space")){*sub=DALVIK_LARGE;return DALVIK;}
        if(strstr(name,"non moving space")){*sub=DALVIK_NON_MOVING;return DALVIK;}
        if(strstr(name,"zygote space")){*sub=DALVIK_ZYGOTE;return DALVIK;}
        *sub=strstr(name,"LinearAlloc")?LINEAR:strstr(name,"indirect ref")?INDIRECT:
            strstr(name,"code-cache")?CODE_CACHE:strstr(name,"CompilerMetadata")?COMPILER:ACCOUNTING;
        return DALVIK_OTHER;
    }
    return name[0]&&strncmp(name,"[anon:",6)?UNKNOWN_MAP:UNKNOWN;
}
static void add_mapping(struct memory *out,uint64_t *values,int heap,int sub,int swappable){
    if(swappable){
        uint64_t shared=values[SHARED_CLEAN]+values[SHARED_DIRTY],uss=values[PRIVATE_CLEAN]+values[PRIVATE_DIRTY];
        values[SWAPPABLE]=values[PRIVATE_CLEAN]+(shared&&values[PSS]>uss?(values[PSS]-uss)*values[SHARED_CLEAN]/shared:0);
    }
    for(int i=0;i<METRICS;i++){out->heap[heap][i]+=values[i];if(sub>=0)out->heap[sub][i]+=values[i];}
}
static int measure(int pid,struct memory *out){
    memset(out,0,sizeof(*out));if(pid<=0){errno=EINVAL;return -1;}
    char path[64],line[4096];snprintf(path,sizeof(path),"/proc/%d/smaps",pid);FILE *stream=fopen(path,"re");if(!stream)return -1;
    uint64_t values[METRICS]={0};int heap=UNKNOWN,sub=-1,swappable=0,have=0,pss_seen=0;
    while(fgets(line,sizeof(line),stream)){
        unsigned long start,end,offset,inode;char permissions[5],device[32];int consumed=0;
        if(sscanf(line,"%lx-%lx %4s %lx %31s %lu %n",&start,&end,permissions,&offset,device,&inode,&consumed)==6&&consumed>0){
            if(have)add_mapping(out,values,heap,sub,swappable);
            memset(values,0,sizeof(values));char *name=line+consumed;while(*name==' '||*name=='\t')name++;heap=classify(name,&sub,&swappable);have=1;continue;
        }
        char key[64];unsigned long long value;
        if(sscanf(line,"%63[^:]: %llu kB",key,&value)!=2)continue;
        int metric=!strcmp(key,"Pss")?PSS:!strcmp(key,"Rss")?RSS:!strcmp(key,"Private_Dirty")?PRIVATE_DIRTY:
            !strcmp(key,"Shared_Dirty")?SHARED_DIRTY:!strcmp(key,"Private_Clean")?PRIVATE_CLEAN:
            !strcmp(key,"Shared_Clean")?SHARED_CLEAN:!strcmp(key,"Swap")?SWAP:!strcmp(key,"SwapPss")?SWAP_PSS:-1;
        if(metric>=0)values[metric]=value;
        if(metric==PSS)pss_seen=1;
        if(metric==SWAP_PSS)out->swap_pss=1;
    }
    int error=ferror(stream);fclose(stream);if(error||!have||!pss_seen){errno=EIO;return -1;}
    add_mapping(out,values,heap,sub,swappable);
    for(int h=3;h<=MEMTRACK;h++)for(int m=0;m<METRICS;m++)out->heap[UNKNOWN][m]+=out->heap[h][m];
    return 0;
}
static jint integer(uint64_t value){return value>INT_MAX?INT_MAX:(jint)value;}
static void memory_info_pid(JNIEnv *env,jclass type,jint pid,jobject info){
    (void)type;if(!info){(*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/NullPointerException"),"MemoryInfo required");return;}
    struct memory data;if(measure(pid,&data)<0){(*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/IllegalStateException"),"Process smaps unavailable");return;}
    for(int h=0;h<3;h++)for(int m=0;m<METRICS;m++)(*env)->SetIntField(env,info,fields[h][m],integer(data.heap[h][m]));
    (*env)->SetBooleanField(env,info,has_swap_pss,data.swap_pss?JNI_TRUE:JNI_FALSE);
    jintArray array=(*env)->GetObjectField(env,info,other_stats);if(!array)return;
    jint extra[(HEAPS-3)*METRICS];for(int h=3;h<HEAPS;h++)for(int m=0;m<METRICS;m++)extra[(h-3)*METRICS+m]=integer(data.heap[h][m]);
    if((*env)->GetArrayLength(env,array)<(HEAPS-3)*METRICS){(*env)->ThrowNew(env,(*env)->FindClass(env,"java/lang/IllegalStateException"),"MemoryInfo ABI differs from API29");return;}
    (*env)->SetIntArrayRegion(env,array,0,(HEAPS-3)*METRICS,extra);
}
static void memory_info(JNIEnv *env,jclass type,jobject info){memory_info_pid(env,type,getpid(),info);}
static jlong pss_pid(JNIEnv *env,jclass type,jint pid,jlongArray output,jlongArray memtrack){
    (void)type;struct memory data;if(measure(pid,&data)<0)return 0;
    uint64_t totals[METRICS]={0};for(int h=0;h<3;h++)for(int m=0;m<METRICS;m++)totals[m]+=data.heap[h][m];
    jlong values[]={totals[PRIVATE_CLEAN]+totals[PRIVATE_DIRTY],totals[SWAP_PSS],totals[RSS]};
    if(output){jsize size=(*env)->GetArrayLength(env,output);if(size>3)size=3;if(size)(*env)->SetLongArrayRegion(env,output,0,size,values);}
    // Same fallback as AOSP when memtrack is unavailable. Only kernel-accounted
    // memory is reported; no graphics HAL is contacted from an app process.
    if(memtrack&&(*env)->GetArrayLength(env,memtrack)>0){jlong unavailable=0;(*env)->SetLongArrayRegion(env,memtrack,0,1,&unavailable);}
    return totals[PSS]+totals[SWAP_PSS];
}
static jlong pss(JNIEnv *env,jclass type){return pss_pid(env,type,getpid(),NULL,NULL);}
int sd_memory_install(JNIEnv *env){
    jclass info=(*env)->FindClass(env,"android/os/Debug$MemoryInfo");if(!info)return -1;
    const char *prefix[]={"other","dalvik","native"},*suffix[]={"Pss","SwappablePss","Rss","PrivateDirty","SharedDirty","PrivateClean","SharedClean","SwappedOut","SwappedOutPss"};
    for(int h=0;h<3;h++)for(int m=0;m<METRICS;m++){char name[80];snprintf(name,sizeof(name),"%s%s",prefix[h],suffix[m]);fields[h][m]=(*env)->GetFieldID(env,info,name,"I");if(!fields[h][m])return -1;}
    other_stats=(*env)->GetFieldID(env,info,"otherStats","[I");has_swap_pss=(*env)->GetFieldID(env,info,"hasSwappedOutPss","Z");if(!other_stats||!has_swap_pss)return -1;
    JNINativeMethod methods[]={{"getMemoryInfo","(Landroid/os/Debug$MemoryInfo;)V",memory_info},{"getMemoryInfo","(ILandroid/os/Debug$MemoryInfo;)V",memory_info_pid},{"getPss","()J",pss},{"getPss","(I[J[J)J",pss_pid}};
    return (*env)->RegisterNatives(env,(*env)->FindClass(env,"android/os/Debug"),methods,4);
}
