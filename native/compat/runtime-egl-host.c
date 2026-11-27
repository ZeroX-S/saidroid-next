#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <stdio.h>

typedef void *EGLDisplay;typedef void *EGLConfig;typedef void *EGLContext;typedef void *EGLSurface;typedef void *EGLSync;typedef void *EGLImage;typedef void *EGLClientBuffer;
typedef unsigned EGLBoolean;typedef unsigned EGLenum;typedef int EGLint;typedef intptr_t EGLAttrib;typedef uint64_t EGLTime;
typedef unsigned GLenum;typedef unsigned GLuint;typedef int GLint;typedef int GLsizei;typedef unsigned char GLboolean;typedef float GLfloat;typedef char GLchar;typedef intptr_t GLintptr;typedef intptr_t GLsizeiptr;typedef int64_t GLint64;
_Static_assert(sizeof(void*)==8&&sizeof(EGLint)==4,"API29 ARM64 EGL ABI");
static pthread_once_t once=PTHREAD_ONCE_INIT;
static void *egl_library,*gles_library;
static void *(*get_proc)(const char*);
static _Thread_local EGLint egl_error;
static _Thread_local GLenum gl_error;
static void *(*hwui_display)(void);
static void *(*hwui_window)(int);
static int (*hwui_identify)(void *);
static void (*hwui_presented)(void);
void sd_hwui_register_host(void *(*display)(void),void *(*window)(int),int (*identify)(void *),void (*presented)(void)) {
    hwui_display=display;hwui_window=window;hwui_identify=identify;hwui_presented=presented;
}
static void initialize(void){egl_library=dlopen("libEGL.so.1",RTLD_NOW|RTLD_LOCAL);gles_library=dlopen("libGLESv2.so.2",RTLD_NOW|RTLD_LOCAL);if(egl_library)get_proc=dlsym(egl_library,"eglGetProcAddress");}
static void *entry(const char *name){pthread_once(&once,initialize);void *result=egl_library?dlsym(egl_library,name):NULL;if(!result&&gles_library)result=dlsym(gles_library,name);return result?result:get_proc?get_proc(name):NULL;}
static EGLBoolean unsupported(EGLint error){egl_error=error;return 0;}
EGLint bionic_eglGetError(void){if(egl_error){EGLint result=egl_error;egl_error=0;return result;}EGLint(*fn)(void)=entry("eglGetError");return fn?fn():0x3001;}
GLenum bionic_glGetError(void){if(gl_error){GLenum result=gl_error;gl_error=0;return result;}GLenum(*fn)(void)=entry("glGetError");return fn?fn():0x0502;}

/* Host EGL and Android's raster Surface store have different native-window and
 * AHardwareBuffer representations. Expose the actual offscreen API, and exclude
 * native-buffer extensions instead of advertising an unusable producer. */
struct extension_string {char *text;struct extension_string *next;};
static pthread_mutex_t strings_lock=PTHREAD_MUTEX_INITIALIZER;
static struct extension_string *strings;
const char *bionic_eglQueryString(EGLDisplay display,EGLint name){
    const char *(*fn)(EGLDisplay,EGLint)=entry("eglQueryString");if(!fn){unsupported(0x3001);return NULL;}
    const char *original=fn(display,name);if(!original||name!=0x3055)return original;
    char *filtered=malloc(strlen(original)+1);if(!filtered){unsupported(0x3003);return NULL;}
    size_t used=0;const char *at=original;
    while(*at){while(*at==' ')at++;const char *end=strchr(at,' ');size_t size=end?(size_t)(end-at):strlen(at);
        int hidden=(size==strlen("EGL_ANDROID_image_native_buffer")&&!memcmp(at,"EGL_ANDROID_image_native_buffer",size))||(size==strlen("EGL_ANDROID_get_native_client_buffer")&&!memcmp(at,"EGL_ANDROID_get_native_client_buffer",size));
        if(size&&!hidden){if(used)filtered[used++]=' ';memcpy(filtered+used,at,size);used+=size;}at+=size;
    }filtered[used]=0;
    if(!strcmp(filtered,original)){free(filtered);return original;}
    pthread_mutex_lock(&strings_lock);for(struct extension_string *s=strings;s;s=s->next)if(!strcmp(s->text,filtered)){free(filtered);pthread_mutex_unlock(&strings_lock);return s->text;}
    struct extension_string *saved=malloc(sizeof(*saved));if(!saved){free(filtered);pthread_mutex_unlock(&strings_lock);unsupported(0x3003);return NULL;}
    saved->text=filtered;saved->next=strings;strings=saved;pthread_mutex_unlock(&strings_lock);return filtered;
}
const char *bionic_eglQueryStringImplementationANDROID(EGLDisplay display,EGLint name){return bionic_eglQueryString(display,name);}
EGLBoolean bionic_eglGetConfigAttrib(EGLDisplay d,EGLConfig c,EGLint attr,EGLint *value){EGLBoolean(*fn)(EGLDisplay,EGLConfig,EGLint,EGLint*)=entry("eglGetConfigAttrib");return fn?fn(d,c,attr,value):unsupported(0x3001);}
EGLBoolean bionic_eglGetConfigs(EGLDisplay d,EGLConfig *configs,EGLint size,EGLint *count){EGLBoolean(*fn)(EGLDisplay,EGLConfig*,EGLint,EGLint*)=entry("eglGetConfigs");return fn?fn(d,configs,size,count):unsupported(0x3001);}
EGLBoolean bionic_eglChooseConfig(EGLDisplay d,const EGLint *attrs,EGLConfig *configs,EGLint size,EGLint *count){EGLBoolean(*fn)(EGLDisplay,const EGLint*,EGLConfig*,EGLint,EGLint*)=entry("eglChooseConfig");return fn?fn(d,attrs,configs,size,count):unsupported(0x3001);}
struct display_state {EGLDisplay display;int initialized;struct display_state *next;};
static pthread_mutex_t displays_lock=PTHREAD_MUTEX_INITIALIZER;
static struct display_state *displays;
static void initialized(EGLDisplay display,int state){pthread_mutex_lock(&displays_lock);struct display_state *found=displays;while(found&&found->display!=display)found=found->next;if(!found){found=calloc(1,sizeof(*found));if(found){found->display=display;found->next=displays;displays=found;}}if(found)found->initialized=state;pthread_mutex_unlock(&displays_lock);}
EGLBoolean bionic_eglInitialize(EGLDisplay d,EGLint *major,EGLint *minor){EGLBoolean(*fn)(EGLDisplay,EGLint*,EGLint*)=entry("eglInitialize");if(!fn)return unsupported(0x3001);EGLBoolean result=fn(d,major,minor);if(result)initialized(d,1);return result;}
EGLBoolean bionic_eglTerminate(EGLDisplay d){EGLBoolean(*fn)(EGLDisplay)=entry("eglTerminate");if(!fn)return unsupported(0x3001);EGLBoolean result=fn(d);if(result)initialized(d,0);return result;}
/* Android's EGLImpl asks for display initialization references. The host API
 * initializes a display idempotently; expose its actual initialized state. */
int bionic__ZN7android18egl_get_init_countEPv(void *d){int result=0;pthread_mutex_lock(&displays_lock);for(struct display_state *s=displays;s;s=s->next)if(s->display==d){result=s->initialized;break;}pthread_mutex_unlock(&displays_lock);return result;}
/* This Android-only hint selects Android's disk shader cache. Host drivers
 * manage their own caches; never pass Android cache files into libhybris. */
void bionic__ZN7android22egl_set_cache_filenameEPKc(const char *filename){(void)filename;fprintf(stderr,"SAILDROID_EGL_CACHE=host-managed|android-cache-file=unused\n");}
EGLDisplay bionic_eglGetDisplay(void *native) {
    EGLDisplay(*fn)(void*)=entry("eglGetDisplay");
    if(!fn){unsupported(0x3001);return NULL;}
    if(!native&&hwui_display)native=hwui_display();
    return fn(native);
}
EGLSurface bionic_eglCreateWindowSurface(EGLDisplay d,EGLConfig c,void *window,const EGLint *attrs){
    int id=hwui_identify?hwui_identify(window):0;
    void *native=id&&hwui_window?hwui_window(id):NULL;
    if(!native){unsupported(0x300b);return NULL;}
    EGLSurface(*fn)(EGLDisplay,EGLConfig,void*,const EGLint*)=entry("eglCreateWindowSurface");
    EGLSurface result=fn?fn(d,c,native,attrs):NULL;
    fprintf(stderr,"SDHWUI=egl_window_surface|id=%d|result=%p|queue=libhybris|cpu_readback=0\n",id,result);
    return result;
}
EGLSurface bionic_eglCreatePlatformWindowSurface(EGLDisplay d,EGLConfig c,void *window,const EGLAttrib *attrs){(void)d;(void)c;(void)window;(void)attrs;unsupported(0x300b);return NULL;}
EGLClientBuffer bionic_eglGetNativeClientBufferANDROID(const void *buffer){(void)buffer;unsupported(0x300c);return NULL;}

#define EGL_FORWARD(result,name,decl,args,failure) result bionic_##name decl {result(*fn)decl=entry(#name);if(!fn){unsupported(0x3009);return failure;}return fn args;}
EGL_FORWARD(EGLSync,eglCreateSyncKHR,(EGLDisplay d,EGLenum type,const EGLint *attrs),(d,type,attrs),NULL)
EGL_FORWARD(EGLBoolean,eglDestroySyncKHR,(EGLDisplay d,EGLSync sync),(d,sync),0)
EGL_FORWARD(EGLint,eglClientWaitSyncKHR,(EGLDisplay d,EGLSync sync,EGLint flags,EGLTime timeout),(d,sync,flags,timeout),0)
EGL_FORWARD(EGLBoolean,eglWaitSyncKHR,(EGLDisplay d,EGLSync sync,EGLint flags),(d,sync,flags),0)
EGL_FORWARD(EGLBoolean,eglDestroyImageKHR,(EGLDisplay d,EGLImage image),(d,image),0)
EGL_FORWARD(EGLint,eglDupNativeFenceFDANDROID,(EGLDisplay d,EGLSync sync),(d,sync),-1)
EGL_FORWARD(EGLBoolean,eglSetDamageRegionKHR,(EGLDisplay d,EGLSurface surface,const EGLint *rects,EGLint count),(d,surface,rects,count),0)
static EGLBoolean hwui_swapped(EGLBoolean result) {
    if(result&&hwui_presented)hwui_presented();
    static unsigned count;
    if(hwui_window && (count<3 || !result)) {
        const unsigned char *(*renderer)(GLenum)=entry("glGetString");
        fprintf(stderr,"SDHWUI=gpu_swap|count=%u|success=%u|renderer=%s|cpu_readback=0\n",
            ++count,result,renderer?(const char*)renderer(0x1f01):"unavailable");
    }
    return result;
}
EGLBoolean bionic_eglSwapBuffers(EGLDisplay d,EGLSurface surface) {
    EGLBoolean(*fn)(EGLDisplay,EGLSurface)=entry("eglSwapBuffers");
    return fn?hwui_swapped(fn(d,surface)):unsupported(0x3001);
}
EGLBoolean bionic_eglSwapBuffersWithDamageKHR(EGLDisplay d,EGLSurface surface,const EGLint *rects,EGLint count) {
    /* libhybris wraps EXT to run Wayland prepareSwap/finishSwap, but its KHR
     * lookup returns the vendor function. Calling that bypasses wl_surface
     * attach/commit and exhausts all three GPU buffers. Route the equivalent
     * KHR contract through its platform-aware EXT wrapper. */
    EGLBoolean(*fn)(EGLDisplay,EGLSurface,const EGLint*,EGLint)=entry("eglSwapBuffersWithDamageEXT");
    return fn?hwui_swapped(fn(d,surface,rects,count)):bionic_eglSwapBuffers(d,surface);
}
EGL_FORWARD(EGLBoolean,eglPresentationTimeANDROID,(EGLDisplay d,EGLSurface surface,int64_t time),(d,surface,time),0)
EGLImage bionic_eglCreateImageKHR(EGLDisplay d,EGLContext context,EGLenum target,EGLClientBuffer buffer,const EGLint *attrs){if(target==0x3140){unsupported(0x300c);return NULL;}EGLImage(*fn)(EGLDisplay,EGLContext,EGLenum,EGLClientBuffer,const EGLint*)=entry("eglCreateImageKHR");if(!fn){unsupported(0x3009);return NULL;}return fn(d,context,target,buffer,attrs);}
static int narrow(const EGLAttrib *attrs,EGLint *out){if(!attrs){out[0]=0x3038;return 1;}for(size_t i=0;i<510;i+=2){if(attrs[i]==0x3038){out[i]=0x3038;return 1;}if(attrs[i]<INT_MIN||attrs[i]>INT_MAX||attrs[i+1]<INT_MIN||attrs[i+1]>INT_MAX){unsupported(0x3004);return 0;}out[i]=(EGLint)attrs[i];out[i+1]=(EGLint)attrs[i+1];}unsupported(0x3004);return 0;}
EGLSync bionic_eglCreateSync(EGLDisplay d,EGLenum type,const EGLAttrib *attrs){EGLSync(*fn)(EGLDisplay,EGLenum,const EGLAttrib*)=entry("eglCreateSync");if(fn)return fn(d,type,attrs);EGLint copy[512];return narrow(attrs,copy)?bionic_eglCreateSyncKHR(d,type,copy):NULL;}
EGLBoolean bionic_eglDestroySync(EGLDisplay d,EGLSync sync){EGLBoolean(*fn)(EGLDisplay,EGLSync)=entry("eglDestroySync");return fn?fn(d,sync):bionic_eglDestroySyncKHR(d,sync);}
EGLint bionic_eglClientWaitSync(EGLDisplay d,EGLSync sync,EGLint flags,EGLTime timeout){EGLint(*fn)(EGLDisplay,EGLSync,EGLint,EGLTime)=entry("eglClientWaitSync");return fn?fn(d,sync,flags,timeout):bionic_eglClientWaitSyncKHR(d,sync,flags,timeout);}
EGLBoolean bionic_eglWaitSync(EGLDisplay d,EGLSync sync,EGLint flags){EGLBoolean(*fn)(EGLDisplay,EGLSync,EGLint)=entry("eglWaitSync");return fn?fn(d,sync,flags):bionic_eglWaitSyncKHR(d,sync,flags);}
EGLImage bionic_eglCreateImage(EGLDisplay d,EGLContext context,EGLenum target,EGLClientBuffer buffer,const EGLAttrib *attrs){if(target==0x3140){unsupported(0x300c);return NULL;}EGLImage(*fn)(EGLDisplay,EGLContext,EGLenum,EGLClientBuffer,const EGLAttrib*)=entry("eglCreateImage");if(fn)return fn(d,context,target,buffer,attrs);EGLint copy[512];return narrow(attrs,copy)?bionic_eglCreateImageKHR(d,context,target,buffer,copy):NULL;}
EGLBoolean bionic_eglDestroyImage(EGLDisplay d,EGLImage image){EGLBoolean(*fn)(EGLDisplay,EGLImage)=entry("eglDestroyImage");return fn?fn(d,image):bionic_eglDestroyImageKHR(d,image);}
EGLBoolean bionic_eglGetSyncAttrib(EGLDisplay d,EGLSync sync,EGLint attr,EGLAttrib *value){EGLBoolean(*fn)(EGLDisplay,EGLSync,EGLint,EGLAttrib*)=entry("eglGetSyncAttrib");if(fn)return fn(d,sync,attr,value);EGLBoolean(*khr)(EGLDisplay,EGLSync,EGLint,EGLint*)=entry("eglGetSyncAttribKHR");if(!khr)return unsupported(0x3009);EGLint small;EGLBoolean result=khr(d,sync,attr,&small);if(result&&value)*value=small;return result;}

#define GL_FORWARD(name,decl,args) void bionic_##name decl {void(*fn)decl=entry(#name);if(!fn){gl_error=0x0502;return;}fn args;}
GL_FORWARD(glBeginQueryEXT,(GLenum target,GLuint id),(target,id))
GL_FORWARD(glBlendBarrierKHR,(void),())
GL_FORWARD(glBlendEquationSeparateiEXT,(GLuint b,GLenum rgb,GLenum alpha),(b,rgb,alpha))
GL_FORWARD(glBlendEquationiEXT,(GLuint b,GLenum mode),(b,mode))
GL_FORWARD(glBlendFuncSeparateiEXT,(GLuint b,GLenum sr,GLenum dr,GLenum sa,GLenum da),(b,sr,dr,sa,da))
GL_FORWARD(glBlendFunciEXT,(GLuint b,GLenum src,GLenum dst),(b,src,dst))
GL_FORWARD(glColorMaskiEXT,(GLuint b,GLboolean r,GLboolean g,GLboolean blue,GLboolean a),(b,r,g,blue,a))
GL_FORWARD(glCopyImageSubDataEXT,(GLuint sn,GLenum st,GLint sl,GLint sx,GLint sy,GLint sz,GLuint dn,GLenum dt,GLint dl,GLint dx,GLint dy,GLint dz,GLsizei w,GLsizei h,GLsizei depth),(sn,st,sl,sx,sy,sz,dn,dt,dl,dx,dy,dz,w,h,depth))
GL_FORWARD(glDebugMessageControlKHR,(GLenum s,GLenum t,GLenum severity,GLsizei n,const GLuint *ids,GLboolean enabled),(s,t,severity,n,ids,enabled))
GL_FORWARD(glDebugMessageInsertKHR,(GLenum s,GLenum t,GLuint id,GLenum severity,GLsizei n,const GLchar *text),(s,t,id,severity,n,text))
GL_FORWARD(glDisableiEXT,(GLenum target,GLuint index),(target,index))
GL_FORWARD(glEnableiEXT,(GLenum target,GLuint index),(target,index))
GL_FORWARD(glEndQueryEXT,(GLenum target),(target))
GL_FORWARD(glFramebufferTextureEXT,(GLenum target,GLenum attachment,GLuint texture,GLint level),(target,attachment,texture,level))
GL_FORWARD(glGenQueriesEXT,(GLsizei n,GLuint *ids),(n,ids))
GL_FORWARD(glGetQueryObjecti64vEXT,(GLuint id,GLenum pname,GLint64 *params),(id,pname,params))
GL_FORWARD(glGetQueryObjectivEXT,(GLuint id,GLenum pname,GLint *params),(id,pname,params))
GL_FORWARD(glGetSamplerParameterIivEXT,(GLuint s,GLenum pname,GLint *params),(s,pname,params))
GL_FORWARD(glGetSamplerParameterIuivEXT,(GLuint s,GLenum pname,GLuint *params),(s,pname,params))
GL_FORWARD(glGetTexParameterIivEXT,(GLenum target,GLenum pname,GLint *params),(target,pname,params))
GL_FORWARD(glGetTexParameterIuivEXT,(GLenum target,GLenum pname,GLuint *params),(target,pname,params))
GLboolean bionic_glIsEnablediEXT(GLenum target,GLuint index){GLboolean(*fn)(GLenum,GLuint)=entry("glIsEnablediEXT");if(!fn){gl_error=0x0502;return 0;}return fn(target,index);}
GL_FORWARD(glMinSampleShadingOES,(GLfloat value),(value))
GL_FORWARD(glObjectLabelKHR,(GLenum type,GLuint name,GLsizei n,const GLchar *label),(type,name,n,label))
GL_FORWARD(glPatchParameteriEXT,(GLenum pname,GLint value),(pname,value))
GL_FORWARD(glPopDebugGroupKHR,(void),())
GL_FORWARD(glPrimitiveBoundingBoxEXT,(GLfloat x,GLfloat y,GLfloat z,GLfloat w,GLfloat X,GLfloat Y,GLfloat Z,GLfloat W),(x,y,z,w,X,Y,Z,W))
GL_FORWARD(glPushDebugGroupKHR,(GLenum source,GLuint id,GLsizei n,const GLchar *text),(source,id,n,text))
GL_FORWARD(glSamplerParameterIivEXT,(GLuint s,GLenum pname,const GLint *params),(s,pname,params))
GL_FORWARD(glSamplerParameterIuivEXT,(GLuint s,GLenum pname,const GLuint *params),(s,pname,params))
GL_FORWARD(glTexBufferEXT,(GLenum target,GLenum format,GLuint buffer),(target,format,buffer))
GL_FORWARD(glTexBufferRangeEXT,(GLenum target,GLenum format,GLuint buffer,GLintptr offset,GLsizeiptr size),(target,format,buffer,offset,size))
GL_FORWARD(glTexParameterIivEXT,(GLenum target,GLenum pname,const GLint *params),(target,pname,params))
GL_FORWARD(glTexParameterIuivEXT,(GLenum target,GLenum pname,const GLuint *params),(target,pname,params))
GL_FORWARD(glTexStorage3DMultisampleOES,(GLenum target,GLsizei samples,GLenum format,GLsizei w,GLsizei h,GLsizei depth,GLboolean fixed),(target,samples,format,w,h,depth,fixed))

void *bionic_eglGetProcAddress(const char *name){if(!name){unsupported(0x300c);return NULL;}
#define OVERRIDE(symbol) if(!strcmp(name,#symbol))return (void*)bionic_##symbol;
OVERRIDE(eglChooseConfig)
OVERRIDE(eglClientWaitSync)
OVERRIDE(eglClientWaitSyncKHR)
OVERRIDE(eglCreateImage)
OVERRIDE(eglCreateImageKHR)
OVERRIDE(eglCreatePlatformWindowSurface)
OVERRIDE(eglCreateSync)
OVERRIDE(eglCreateSyncKHR)
OVERRIDE(eglCreateWindowSurface)
OVERRIDE(eglDestroyImage)
OVERRIDE(eglDestroyImageKHR)
OVERRIDE(eglDestroySync)
OVERRIDE(eglDestroySyncKHR)
OVERRIDE(eglDupNativeFenceFDANDROID)
OVERRIDE(eglGetConfigAttrib)
OVERRIDE(eglGetConfigs)
OVERRIDE(eglGetDisplay)
OVERRIDE(eglGetError)
OVERRIDE(eglGetNativeClientBufferANDROID)
OVERRIDE(eglGetSyncAttrib)
OVERRIDE(eglInitialize)
OVERRIDE(eglPresentationTimeANDROID)
OVERRIDE(eglQueryString)
OVERRIDE(eglQueryStringImplementationANDROID)
OVERRIDE(eglSetDamageRegionKHR)
OVERRIDE(eglSwapBuffers)
OVERRIDE(eglSwapBuffersWithDamageKHR)
OVERRIDE(eglTerminate)
OVERRIDE(eglWaitSync)
OVERRIDE(eglWaitSyncKHR)
OVERRIDE(glBeginQueryEXT)
OVERRIDE(glBlendBarrierKHR)
OVERRIDE(glBlendEquationSeparateiEXT)
OVERRIDE(glBlendEquationiEXT)
OVERRIDE(glBlendFuncSeparateiEXT)
OVERRIDE(glBlendFunciEXT)
OVERRIDE(glColorMaskiEXT)
OVERRIDE(glCopyImageSubDataEXT)
OVERRIDE(glDebugMessageControlKHR)
OVERRIDE(glDebugMessageInsertKHR)
OVERRIDE(glDisableiEXT)
OVERRIDE(glEnableiEXT)
OVERRIDE(glEndQueryEXT)
OVERRIDE(glFramebufferTextureEXT)
OVERRIDE(glGenQueriesEXT)
OVERRIDE(glGetError)
OVERRIDE(glGetQueryObjecti64vEXT)
OVERRIDE(glGetQueryObjectivEXT)
OVERRIDE(glGetSamplerParameterIivEXT)
OVERRIDE(glGetSamplerParameterIuivEXT)
OVERRIDE(glGetTexParameterIivEXT)
OVERRIDE(glGetTexParameterIuivEXT)
OVERRIDE(glIsEnablediEXT)
OVERRIDE(glMinSampleShadingOES)
OVERRIDE(glObjectLabelKHR)
OVERRIDE(glPatchParameteriEXT)
OVERRIDE(glPopDebugGroupKHR)
OVERRIDE(glPrimitiveBoundingBoxEXT)
OVERRIDE(glPushDebugGroupKHR)
OVERRIDE(glSamplerParameterIivEXT)
OVERRIDE(glSamplerParameterIuivEXT)
OVERRIDE(glTexBufferEXT)
OVERRIDE(glTexBufferRangeEXT)
OVERRIDE(glTexParameterIivEXT)
OVERRIDE(glTexParameterIuivEXT)
OVERRIDE(glTexStorage3DMultisampleOES)
#undef OVERRIDE
 return entry(name);
}
