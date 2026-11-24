#define _GNU_SOURCE
#include <stdbool.h>
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#ifndef SD_RS_TIMEOUT_MS
#define SD_RS_TIMEOUT_MS 30000
#endif

/* Android's RS utility launches the real platform compiler/linker. They run in
 * their own Bionic process, with a matching private library closure. No shell,
 * rewritten bitcode, fake exit status, or mutation of the host /system paths. */
static long long milliseconds(void) {
    struct timespec time;clock_gettime(CLOCK_MONOTONIC,&time);
    return (long long)time.tv_sec*1000+time.tv_nsec/1000000;
}
static char *join(const char *root,const char *suffix) {
    char *result=NULL;
    if(asprintf(&result,"%s%s",root,suffix)<0)return NULL;
    return result;
}
static char *argument(const char *root,const char *value) {
    const char *suffix=NULL,*prefix="";
    if(!strncmp(value,"--library-path=/system/",23)){
        char *result=NULL;if(asprintf(&result,"--library-path=%s/rs/lib",root)<0)return NULL;
        return result;
    }
    if(!strncmp(value,"/system/lib64/",14)){prefix="/rs/lib/";suffix=value+14;}
    else if(!strcmp(value,"/system/bin/bcc")){prefix="/rs/bin/";suffix="bcc";}
    else if(!strcmp(value,"/system/bin/ld.mc")){prefix="/rs/bin/";suffix="ld.mc";}
    if(suffix){
        if(strchr(suffix,'/')||!strcmp(suffix,"..")){errno=EINVAL;return NULL;}
        char *result=NULL;if(asprintf(&result,"%s%s%s",root,prefix,suffix)<0)return NULL;
        return result;
    }
    return strdup(value);
}
bool bionic__ZN7android12renderscript17rsuExecuteCommandEPKciPKS2_(const char *exe,int count,const char *const *args) {
    const char *root=getenv("ANDROID_ROOT");
    const char *tool=exe&&!strcmp(exe,"/system/bin/bcc")?"bcc":exe&&!strcmp(exe,"/system/bin/ld.mc")?"ld.mc":NULL;
    if(!tool||!root||root[0]!='/'||strstr(root,"/../")||count<1||count>512||!args||!args[0]||strcmp(args[0],exe)){errno=EINVAL;return false;}
    char *linker=join(root,"/rs/bin/linker64"),*binary=NULL,*libpath=join(root,"/rs/lib");
    if(asprintf(&binary,"%s/rs/bin/%s",root,tool)<0)binary=NULL;
    char **argv=calloc((size_t)count+2,sizeof(char*)),**environment=calloc(8,sizeof(char*));
    bool success=false;pid_t child=-1;
    if(!linker||!binary||!libpath||!argv||!environment)goto done;
    /* API29's linker executable accepts the absolute program path, not the
     * glibc linker's --library-path option. LD_LIBRARY_PATH below supplies it. */
    argv[0]=linker;argv[1]=binary;
    for(int i=1;i<count;i++){
        if(!args[i]||strlen(args[i])>PATH_MAX*4){errno=EINVAL;goto done;}
        argv[i+1]=argument(root,args[i]);if(!argv[i+1])goto done;
    }
    /* Compiler processes must never inherit the glibc host's LD_PRELOAD. */
    if(asprintf(&environment[0],"ANDROID_ROOT=%s",root)<0)goto done;
    environment[1]=strdup("PATH=/usr/bin:/bin");environment[2]=strdup("TMPDIR=/tmp");
    if(asprintf(&environment[3],"LD_LIBRARY_PATH=%s",libpath)<0)goto done;
    if(!environment[1]||!environment[2])goto done;
    pid_t parent=getpid();child=fork();
    if(child==0){
        /* Only system calls between fork and exec: ART has other live threads. */
        if(prctl(PR_SET_PDEATHSIG,SIGKILL)<0||getppid()!=parent)_exit(127);
        if(setpgid(0,0)<0)_exit(127);
        execve(linker,argv,environment);_exit(127);
    }
    if(child<0)goto done;
    long long until=milliseconds()+SD_RS_TIMEOUT_MS;int status=0;pid_t waited;
    for(;;){
        waited=waitpid(child,&status,WNOHANG);
        if(waited==child){success=WIFEXITED(status)&&WEXITSTATUS(status)==0;break;}
        if(waited<0&&errno!=EINTR)break;
        if(milliseconds()>=until){kill(child,SIGKILL);while(waitpid(child,&status,0)<0&&errno==EINTR){}errno=ETIMEDOUT;break;}
        struct timespec pause={0,10000000};nanosleep(&pause,NULL);
    }
    fprintf(stderr,"SDRENDERSCRIPT=tool-exit|tool=%s|pid=%d|success=%d|status=%d\n",tool,(int)child,success,status);
done:
    if(argv){for(int i=1;i<count;i++)free(argv[i+1]);free(argv);}
    if(environment){for(int i=0;i<8;i++)free(environment[i]);free(environment);}
    free(linker);free(binary);free(libpath);return success;
}
