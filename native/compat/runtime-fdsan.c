#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/syscall.h>

/* Process-private implementation of Android 10's fdsan ownership contract.
 * Host glibc closes retire the entry; Android closes also enforce its tag.
 * No state is shared with Sailfish or with other application processes. */
struct owned_fd { int fd;uint64_t tag;struct owned_fd *next; };
static struct owned_fd *buckets[257];
static pthread_mutex_t fd_lock=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int error_level=1;
static void fork_prepare(void){pthread_mutex_lock(&fd_lock);}
static void fork_finished(void){pthread_mutex_unlock(&fd_lock);}
__attribute__((constructor)) static void register_fork_handlers(void){
    int result=pthread_atfork(fork_prepare,fork_finished,fork_finished);
    if(result){fputs("fdsan: cannot install process fork handlers\n",stderr);abort();}
}
static struct owned_fd **entry(int fd){struct owned_fd **p=&buckets[(unsigned)fd%257];while(*p&&(*p)->fd!=fd)p=&(*p)->next;return p;}
static void set_tag_locked(int fd,uint64_t tag){
    struct owned_fd **p=entry(fd);
    if(!tag){if(*p){struct owned_fd *old=*p;*p=old->next;free(old);}return;}
    if(!*p){*p=calloc(1,sizeof(**p));if(!*p){fputs("fdsan: ownership allocation failed\n",stderr);abort();}(*p)->fd=fd;}
    (*p)->tag=tag;
}
static void mismatch(int fd,uint64_t expected,uint64_t actual){
    int level=atomic_load(&error_level);if(!level)return;
    fprintf(stderr,"fdsan: descriptor %d owner mismatch: expected %016llx, actual %016llx\n",fd,(unsigned long long)expected,(unsigned long long)actual);
    if(level==1)atomic_compare_exchange_strong(&error_level,&level,0);
    if(level==3)abort();
}
uint64_t bionic_android_fdsan_create_owner_tag(int type,uint64_t value){return value?((uint64_t)(uint8_t)type<<56)|(value&UINT64_C(0x00ffffffffffffff)):0;}
uint64_t bionic_android_fdsan_get_tag_value(uint64_t tag){return tag&UINT64_C(0x00ffffffffffffff);}
const char *bionic_android_fdsan_get_tag_type(uint64_t tag){
    switch(tag>>56){
        case 0:case 255:return "generic";case 1:return "FILE*";case 2:return "DIR*";
        case 3:return "unique_fd";case 4:return "sqlite";case 5:return "FileInputStream";
        case 6:return "FileOutputStream";case 7:return "RandomAccessFile";case 8:return "ParcelFileDescriptor";
        case 9:return "ART FdFile";case 10:return "DatagramSocketImpl";case 11:return "SocketImpl";
        case 12:return "ZipArchive";default:return "unknown";
    }
}
uint64_t bionic_android_fdsan_get_owner_tag(int fd){
    if(fd<0)return 0;
    pthread_mutex_lock(&fd_lock);
    if(fcntl(fd,F_GETFD)<0&&errno==EBADF){set_tag_locked(fd,0);pthread_mutex_unlock(&fd_lock);return 0;}
    struct owned_fd *value=*entry(fd);uint64_t tag=value?value->tag:0;pthread_mutex_unlock(&fd_lock);return tag;
}
void bionic_android_fdsan_exchange_owner_tag(int fd,uint64_t expected,uint64_t tag){
    if(fd<0)return;
    pthread_mutex_lock(&fd_lock);struct owned_fd *value=*entry(fd);uint64_t actual=value?value->tag:0;
    if(actual!=expected)mismatch(fd,expected,actual);
    set_tag_locked(fd,tag);pthread_mutex_unlock(&fd_lock);
}
int bionic_android_fdsan_close_with_tag(int fd,uint64_t tag){
    if(fd<0)return (int)syscall(SYS_close,fd);
    pthread_mutex_lock(&fd_lock);struct owned_fd *value=*entry(fd);uint64_t actual=value?value->tag:0;
    if(actual!=tag)mismatch(fd,tag,actual);
    set_tag_locked(fd,0);
    int result=(int)syscall(SYS_close,fd);pthread_mutex_unlock(&fd_lock);return result;
}
int bionic_android_fdsan_get_error_level(void){return atomic_load(&error_level);}
int bionic_android_fdsan_set_error_level(int level){if(level<0||level>3){errno=EINVAL;return atomic_load(&error_level);}return atomic_exchange(&error_level,level);}
int bionic_close(int fd){return bionic_android_fdsan_close_with_tag(fd,0);}
int close(int fd){
    if(fd<0)return (int)syscall(SYS_close,fd);
    pthread_mutex_lock(&fd_lock);set_tag_locked(fd,0);int result=(int)syscall(SYS_close,fd);pthread_mutex_unlock(&fd_lock);return result;
}
#define ALIAS(name) __typeof__(bionic_##name) name __attribute__((alias("bionic_" #name)));
ALIAS(android_fdsan_create_owner_tag)
ALIAS(android_fdsan_get_tag_value)
ALIAS(android_fdsan_get_tag_type)
ALIAS(android_fdsan_get_owner_tag)
ALIAS(android_fdsan_exchange_owner_tag)
ALIAS(android_fdsan_close_with_tag)
ALIAS(android_fdsan_get_error_level)
ALIAS(android_fdsan_set_error_level)
