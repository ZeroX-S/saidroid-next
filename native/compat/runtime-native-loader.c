#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

struct sd_dlextinfo {
    uint64_t flags;void *reserved_addr;size_t reserved_size;int relro_fd;
    int library_fd;off64_t library_fd_offset;void *library_namespace;
};
enum { SD_USE_LIBRARY_FD=0x10,SD_FORCE_LOAD=0x40 };
static _Thread_local char local_error[256];
static pthread_once_t once=PTHREAD_ONCE_INIT;
static void *(*guest_open)(const char*,int);
static const char *(*guest_error)(void);
static int (*guest_add_path)(const char*);
static void initialize(void){
    void *loader=dlopen("libdl_bio.so.0",RTLD_NOW|RTLD_NOLOAD);
    if(loader){guest_open=dlsym(loader,"bionic_dlopen");guest_error=dlsym(loader,"bionic_dlerror");guest_add_path=dlsym(loader,"bionic_add_library_path");}
}
static void *failure(int error,const char *message){
    errno=error;snprintf(local_error,sizeof(local_error),"Android native FD loader: %s",message);return NULL;
}
const char *bionic_dlerror(void){
    pthread_once(&once,initialize);
    const char *(*hardware_error)(void)=dlsym(RTLD_DEFAULT,"sd_hardware_error");
    const char *hardware=hardware_error?hardware_error():NULL;
    if(hardware)return hardware;
    if(local_error[0]){static _Thread_local char result[256];memcpy(result,local_error,sizeof(result));local_error[0]=0;return result;}
    return guest_error?guest_error():NULL;
}
static int art_owned_library(const char *filename){
    if(!filename)return 0;
    const char *name=strrchr(filename,'/');name=name?name+1:filename;
    return!strcmp(name,"libjavacore.so")||!strcmp(name,"libopenjdk.so")||
           !strcmp(name,"libopenjdkjvm.so")||!strcmp(name,"libopenjdkjvmti.so");
}
static int api28_base(void){
    return access("/system/etc/ld.config.28.txt",F_OK)==0;
}
void *bionic_dlopen(const char *filename,int flags){
    pthread_once(&once,initialize);
    if(api28_base()&&art_owned_library(filename)){
        void *handle=dlopen(filename,flags);
        if(handle){local_error[0]=0;return handle;}
        const char *error=dlerror();
        snprintf(local_error,sizeof(local_error),"glibc loader: %s",error?error:"unavailable");
        return NULL;
    }
    local_error[0]=0;
    if(!guest_open)return failure(ENOSYS,"Android linker unavailable");
    return guest_open(filename,flags);
}
/* AOSP FORCE_LOAD requires distinct mutable globals even for the same input
 * inode. Copy exact FD bytes to a private, unique file, load it through the
 * existing Android linker, then unlink. ELF mappings remain until dlclose.
 * Never use the glibc linker to execute this Android object. */
void *bionic_android_dlopen_ext(const char *filename,int flags,const struct sd_dlextinfo *info){
    pthread_once(&once,initialize);local_error[0]=0;
    if(!guest_open||!guest_add_path)return failure(ENOSYS,"Android linker unavailable");
    if(!info||!info->flags)return guest_open(filename,flags);
    if(info->flags!=(SD_USE_LIBRARY_FD|SD_FORCE_LOAD)||info->library_fd_offset)
        return failure(ENOTSUP,"only zero-offset USE_LIBRARY_FD plus FORCE_LOAD is implemented");
    const char *root=getenv("SAILDROID_DATA_DIR");
    if(!root||root[0]!='/'||!filename||filename[0]!='/')return failure(EINVAL,"private application identity required");
    char canonical[PATH_MAX],parent[PATH_MAX],expected[PATH_MAX],temporary[PATH_MAX];
    if(!realpath(root,canonical)||strcmp(root,canonical))return failure(EPERM,"application root is not canonical");
    struct stat source,before,after;
    if(stat(root,&before)||!S_ISDIR(before.st_mode)||before.st_uid!=getuid())return failure(EPERM,"application data ownership differs");
    size_t length=strlen(filename);if(length>=sizeof(parent))return failure(ENAMETOOLONG,"library name too long");
    memcpy(parent,filename,length+1);char *slash=strrchr(parent,'/');if(!slash)return failure(EINVAL,"absolute library name required");*slash=0;
    char resolved[PATH_MAX];if(!realpath(parent,resolved))return failure(errno,"library parent does not exist");
    int matched=0;
    for(int device=0;device<2;device++)for(int cache=0;cache<2;cache++){
        int n=snprintf(expected,sizeof(expected),"%s/%s%s",root,device?"device-protected/":"",cache?"cache":"code_cache");
        if(n<0||(size_t)n>=sizeof(expected))return failure(ENAMETOOLONG,"cache path too long");
        size_t prefix=strlen(expected);
        if(!strncmp(resolved,expected,prefix)&&(resolved[prefix]==0||resolved[prefix]=='/'))matched=1;
    }
    if(!matched||strcmp(parent,resolved))return failure(EPERM,"FD library name escaped private code cache");
    if(fstat(info->library_fd,&source)||!S_ISREG(source.st_mode)||source.st_size<64||source.st_size>32*1024*1024)
        return failure(EINVAL,"regular ELF input of at most 32 MiB required");
    unsigned char elf[5];if(pread(info->library_fd,elf,sizeof(elf),0)!=sizeof(elf)||memcmp(elf,"\177ELF\2",5))return failure(ENOEXEC,"ELF64 input required");
    int n=snprintf(temporary,sizeof(temporary),"%s/.saildroid-fd-XXXXXX.so",resolved);
    /* The accepted Android linker has a 256-byte library-name boundary. */
    if(n<0||n>256)return failure(ENAMETOOLONG,"private ELF filename exceeds linker boundary");
    int fd=mkostemps(temporary,3,O_CLOEXEC);if(fd<0)return failure(errno,"cannot create private FD load copy");
    void *handle=NULL;int error=0;char buffer[16384];off_t offset=0;
    while(offset<source.st_size){
        size_t count=(size_t)(source.st_size-offset);if(count>sizeof(buffer))count=sizeof(buffer);
        ssize_t got=pread(info->library_fd,buffer,count,offset);
        if(got<0&&errno==EINTR)continue;
        if(got<=0){error=EIO;goto done;}
        size_t written=0;while(written<(size_t)got){ssize_t size=write(fd,buffer+written,(size_t)got-written);if(size<0&&errno==EINTR)continue;if(size<=0){error=EIO;goto done;}written+=(size_t)size;}
        offset+=got;
    }
    if(fstat(info->library_fd,&after)||source.st_dev!=after.st_dev||source.st_ino!=after.st_ino||source.st_size!=after.st_size||source.st_mtim.tv_sec!=after.st_mtim.tv_sec||source.st_mtim.tv_nsec!=after.st_mtim.tv_nsec){error=ESTALE;goto done;}
    if(fchmod(fd,0400)){error=errno;goto done;}
    if(guest_add_path(resolved)){error=ENOSYS;goto done;}
    handle=guest_open(temporary,flags);
done:
    close(fd);unlink(temporary);
    if(error)return failure(error,"FD copy or path registration failed");
    if(handle)fprintf(stderr,"SDNATIVE_LOADER=fd-force-loaded|bytes=%lld|copy=private-unlinked|globals=independent\n",(long long)source.st_size);
    return handle;
}