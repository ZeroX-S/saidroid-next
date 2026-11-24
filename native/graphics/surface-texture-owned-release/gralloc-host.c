#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <poll.h>
#include <unistd.h>

/* C ABI only. Android libc++ objects stay inside the Android helper. */
typedef struct { int version,numFds,numInts; int data[]; } NativeHandle;
typedef const NativeHandle *Handle;
typedef struct { int32_t left,top,right,bottom; } Rect;
typedef struct Buffer {
    Handle handle; unsigned stride; int format,allocated;
    struct Buffer *next;
} Buffer;
static pthread_once_t once=PTHREAD_ONCE_INIT;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static Buffer *buffers;
static unsigned live_buffers;
static int (*allocate_buffer)(int,int,int,int,Handle*,unsigned*);
static int (*release_buffer)(Handle,int);
static int (*import_buffer)(Handle,Handle*);
static int (*lock_buffer)(Handle,int,int,int,int,int,void**);
static int (*unlock_buffer)(Handle);
static void initialize(void) {
    void *library=dlopen("libgralloc.so.1",RTLD_NOW|RTLD_LOCAL);
    void (*initialize_gralloc)(int)=library?dlsym(library,"hybris_gralloc_initialize"):NULL;
    if(!initialize_gralloc) return;
    allocate_buffer=dlsym(library,"hybris_gralloc_allocate");
    release_buffer=dlsym(library,"hybris_gralloc_release");
    import_buffer=dlsym(library,"hybris_gralloc_import_buffer");
    lock_buffer=dlsym(library,"hybris_gralloc_lock");
    unlock_buffer=dlsym(library,"hybris_gralloc_unlock");
    initialize_gralloc(0);
}
static int remember(Handle handle,unsigned stride,int format,int allocated) {
    Buffer *entry=calloc(1,sizeof(*entry));if(!entry)return -ENOMEM;
    entry->handle=handle;entry->stride=stride;entry->format=format;entry->allocated=allocated;
    pthread_mutex_lock(&mutex);entry->next=buffers;buffers=entry;live_buffers++;pthread_mutex_unlock(&mutex);return 0;
}
static int release(Handle handle) {
    pthread_mutex_lock(&mutex);Buffer **at=&buffers,*entry=NULL;
    while(*at){if((*at)->handle==handle){entry=*at;*at=entry->next;break;}at=&(*at)->next;}
    unsigned remaining=entry?--live_buffers:live_buffers;
    pthread_mutex_unlock(&mutex);if(!entry)return -EINVAL;
    int result=release_buffer(handle,entry->allocated);
    fprintf(stderr,"SDTEXTURE=gralloc_release|status=%d|remaining=%u\n",result,remaining);
    free(entry);return result;
}
int sd_texture_allocate(unsigned w,unsigned h,int format,unsigned layers,uint64_t usage,Handle *handle,unsigned *stride) {
    pthread_once(&once,initialize);
    if(!allocate_buffer||!handle||!stride)return -ENODEV;
    if(layers!=1||!w||!h||w>16384||h>16384||(usage>>32))return -EINVAL;
    int result=allocate_buffer(w,h,format,(int)usage,handle,stride);
    if(!result){result=remember(*handle,*stride,format,1);if(result)release_buffer(*handle,1);}
    fprintf(stderr,"SDTEXTURE=gralloc_allocate|size=%ux%u|format=%d|status=%d\n",w,h,format,result);
    return result;
}
int sd_texture_free(Handle handle){return release(handle);}
int sd_texture_owns_handle(Handle handle){pthread_mutex_lock(&mutex);Buffer*entry=buffers;while(entry&&entry->handle!=handle)entry=entry->next;int found=entry!=NULL;pthread_mutex_unlock(&mutex);return found;}
int sd_texture_import(Handle raw,unsigned w,unsigned h,unsigned layers,int format,uint64_t usage,unsigned stride,Handle *out) {
    (void)w;(void)h;(void)usage;pthread_once(&once,initialize);
    if(!import_buffer||!raw||!out||layers!=1)return -EINVAL;
    int result=import_buffer(raw,out);if(!result){result=remember(*out,stride,format,0);if(result)release_buffer(*out,0);}return result;
}
static int wait_fence(int fd){if(fd<0)return 0;struct pollfd p={.fd=fd,.events=POLLIN};int result;do{result=poll(&p,1,3000);}while(result<0&&errno==EINTR);close(fd);return result>0?0:result==0?-ETIMEDOUT:-errno;}
int sd_texture_lock(Handle handle,uint64_t usage,const Rect *rect,void **out,int fence,int *pixel,int *stride) {
    int result=wait_fence(fence);if(result)return result;if(usage>>32)return -EINVAL;
    pthread_mutex_lock(&mutex);Buffer *entry=buffers;while(entry&&entry->handle!=handle)entry=entry->next;
    int format=entry?entry->format:0;unsigned row=entry?entry->stride:0;pthread_mutex_unlock(&mutex);
    if(!entry||!rect||!out)return -EINVAL;
    result=lock_buffer(handle,(int)usage,rect->left,rect->top,rect->right-rect->left,rect->bottom-rect->top,out);
    if(!result){int bpp=(format==1||format==2||format==5)?4:format==4?2:0;if(pixel)*pixel=bpp?bpp:-1;if(stride)*stride=bpp?(int)row*bpp:-1;}return result;
}
int sd_texture_unlock(Handle handle,int *fence){if(!unlock_buffer)return -ENODEV;int result=unlock_buffer(handle);if(fence)*fence=-1;return result;}
int sd_tex_supported(void*self,unsigned w,unsigned h,int format,unsigned layers,uint64_t usage,unsigned char*out)
    __asm__("bionic__ZN7android19GraphicBufferMapper11isSupportedEjjijmPb");
int sd_tex_supported(void*self,unsigned w,unsigned h,int format,unsigned layers,uint64_t usage,unsigned char*out) {
    (void)self;if(!out)return -EINVAL;
    Handle handle=NULL;unsigned stride=0;
    int result=sd_texture_allocate(w,h,format,layers,usage,&handle,&stride);
    *out=result==0;
    if(!result)return sd_texture_free(handle);
    return result==-ENODEV?result:0;
}
int sd_tex_ycbcr(void*self,Handle handle,unsigned usage,const Rect*rect,void*out)
    __asm__("bionic__ZN7android19GraphicBufferMapper9lockYCbCrEPK13native_handlejRKNS_4RectEP13android_ycbcr");
int sd_tex_ycbcr(void*self,Handle handle,unsigned usage,const Rect*rect,void*out){(void)self;(void)handle;(void)usage;(void)rect;(void)out;return -ENOTSUP;}
int sd_tex_ycbcr_async(void*self,Handle handle,unsigned usage,const Rect*rect,void*out,int fence)
    __asm__("bionic__ZN7android19GraphicBufferMapper14lockAsyncYCbCrEPK13native_handlejRKNS_4RectEP13android_ycbcri");
int sd_tex_ycbcr_async(void*self,Handle handle,unsigned usage,const Rect*rect,void*out,int fence){(void)self;(void)handle;(void)usage;(void)rect;(void)out;if(fence>=0)close(fence);return -ENOTSUP;}

/* Singleton storage holds no HAL object; all calls below route to owned buffers.
 * The Android helper defines the exact C++ constructor/allocator ABI wrappers. */
void sd_texture_transport(Handle handle,unsigned *fds,unsigned *ints){if(fds)*fds=handle?handle->numFds:0;if(ints)*ints=handle?handle->numInts:0;}

/* Imported C++ method wrappers use AArch64's C-compatible pointer/integer ABI.
 * No glibc std::string is created. A nontrivial Android requestorName parameter
 * is forwarded intact to the matching Android-ABI helper for destruction. */
static int (*android_allocate)(void*,unsigned,unsigned,int,unsigned,uint64_t,Handle*,unsigned*,uint64_t,void*);
void sd_texture_set_allocator(void *fn){android_allocate=fn;}
void sd_tex_mapper_ctor0(void *self) __asm__("bionic__ZN7android19GraphicBufferMapperC1Ev");
void sd_tex_mapper_ctor0(void *self){memset(self,0,16);}
void sd_tex_mapper_ctor1(void *self) __asm__("bionic__ZN7android19GraphicBufferMapperC2Ev");
void sd_tex_mapper_ctor1(void *self){memset(self,0,16);}
void sd_tex_allocator_ctor0(void *self) __asm__("bionic__ZN7android22GraphicBufferAllocatorC1Ev");
void sd_tex_allocator_ctor0(void *self){memset(self,0,16);}
void sd_tex_allocator_ctor1(void *self) __asm__("bionic__ZN7android22GraphicBufferAllocatorC2Ev");
void sd_tex_allocator_ctor1(void *self){memset(self,0,16);}
void sd_tex_allocator_dtor0(void *self) __asm__("bionic__ZN7android22GraphicBufferAllocatorD1Ev");
void sd_tex_allocator_dtor0(void *self){(void)self;}
void sd_tex_allocator_dtor1(void *self) __asm__("bionic__ZN7android22GraphicBufferAllocatorD2Ev");
void sd_tex_allocator_dtor1(void *self){(void)self;}
int sd_tex_allocate0(void*self,unsigned w,unsigned h,int f,unsigned layers,uint64_t usage,Handle*out,unsigned*stride,uint64_t id,void*name) __asm__("bionic__ZN7android22GraphicBufferAllocator8allocateEjjijmPPK13native_handlePjmNSt3__112basic_stringIcNS6_11char_traitsIcEENS6_9allocatorIcEEEE");
int sd_tex_allocate0(void*self,unsigned w,unsigned h,int f,unsigned layers,uint64_t usage,Handle*out,unsigned*stride,uint64_t id,void*name){return android_allocate?android_allocate(self,w,h,f,layers,usage,out,stride,id,name):-ENODEV;}
int sd_tex_free0(void*self,Handle h) __asm__("bionic__ZN7android22GraphicBufferAllocator4freeEPK13native_handle");
int sd_tex_free0(void*self,Handle h){(void)self;return sd_texture_free(h);}
int sd_tex_free1(void*self,Handle h) __asm__("bionic__ZN7android19GraphicBufferMapper10freeBufferEPK13native_handle");
int sd_tex_free1(void*self,Handle h){(void)self;return sd_texture_free(h);}
int sd_tex_import0(void*self,Handle raw,unsigned w,unsigned h,unsigned layers,int f,uint64_t usage,unsigned stride,Handle*out) __asm__("bionic__ZN7android19GraphicBufferMapper12importBufferEPK13native_handlejjjimjPS3_");
int sd_tex_import0(void*self,Handle raw,unsigned w,unsigned h,unsigned layers,int f,uint64_t usage,unsigned stride,Handle*out){(void)self;return sd_texture_import(raw,w,h,layers,f,usage,stride,out);}
void sd_tex_transport0(void*self,Handle h,unsigned*fds,unsigned*ints) __asm__("bionic__ZN7android19GraphicBufferMapper16getTransportSizeEPK13native_handlePjS4_");
void sd_tex_transport0(void*self,Handle h,unsigned*fds,unsigned*ints){(void)self;sd_texture_transport(h,fds,ints);}
int sd_tex_lock0(void*self,Handle h,unsigned usage,const Rect*r,void**out,int*pixel,int*stride) __asm__("bionic__ZN7android19GraphicBufferMapper4lockEPK13native_handlejRKNS_4RectEPPvPiS9_");
int sd_tex_lock0(void*self,Handle h,unsigned usage,const Rect*r,void**out,int*pixel,int*stride){(void)self;return sd_texture_lock(h,usage,r,out,-1,pixel,stride);}
int sd_tex_lock_async0(void*self,Handle h,unsigned usage,const Rect*r,void**out,int fence,int*pixel,int*stride) __asm__("bionic__ZN7android19GraphicBufferMapper9lockAsyncEPK13native_handlejRKNS_4RectEPPviPiS9_");
int sd_tex_lock_async0(void*self,Handle h,unsigned usage,const Rect*r,void**out,int fence,int*pixel,int*stride){(void)self;return sd_texture_lock(h,usage,r,out,fence,pixel,stride);}
int sd_tex_lock640(void*self,Handle h,uint64_t producer,uint64_t consumer,const Rect*r,void**out,int fence,int*pixel,int*stride) __asm__("bionic__ZN7android19GraphicBufferMapper9lockAsyncEPK13native_handlemmRKNS_4RectEPPviPiS9_");
int sd_tex_lock640(void*self,Handle h,uint64_t producer,uint64_t consumer,const Rect*r,void**out,int fence,int*pixel,int*stride){(void)self;return sd_texture_lock(h,producer|consumer,r,out,fence,pixel,stride);}
/* The retained API28 libui omits the optional pixel/stride output parameters. */
int sd_tex_lock_api28(void*self,Handle h,unsigned usage,const Rect*r,void**out)
    __asm__("bionic__ZN7android19GraphicBufferMapper4lockEPK13native_handlejRKNS_4RectEPPv");
int sd_tex_lock_api28(void*self,Handle h,unsigned usage,const Rect*r,void**out) {
    (void)self;return sd_texture_lock(h,usage,r,out,-1,NULL,NULL);
}
int sd_tex_lock_async_api28(void*self,Handle h,unsigned usage,const Rect*r,void**out,int fence)
    __asm__("bionic__ZN7android19GraphicBufferMapper9lockAsyncEPK13native_handlejRKNS_4RectEPPvi");
int sd_tex_lock_async_api28(void*self,Handle h,unsigned usage,const Rect*r,void**out,int fence) {
    (void)self;return sd_texture_lock(h,usage,r,out,fence,NULL,NULL);
}
int sd_tex_lock64_api28(void*self,Handle h,uint64_t producer,uint64_t consumer,const Rect*r,void**out,int fence)
    __asm__("bionic__ZN7android19GraphicBufferMapper9lockAsyncEPK13native_handlemmRKNS_4RectEPPvi");
int sd_tex_lock64_api28(void*self,Handle h,uint64_t producer,uint64_t consumer,const Rect*r,void**out,int fence) {
    (void)self;return sd_texture_lock(h,producer|consumer,r,out,fence,NULL,NULL);
}
int sd_tex_unlock0(void*self,Handle h) __asm__("bionic__ZN7android19GraphicBufferMapper6unlockEPK13native_handle");
int sd_tex_unlock0(void*self,Handle h){(void)self;return sd_texture_unlock(h,NULL);}
int sd_tex_unlock_async0(void*self,Handle h,int*fence) __asm__("bionic__ZN7android19GraphicBufferMapper11unlockAsyncEPK13native_handlePi");
int sd_tex_unlock_async0(void*self,Handle h,int*fence){(void)self;return sd_texture_unlock(h,fence);}
