#define _GNU_SOURCE
#include <jni.h>
#include <dlfcn.h>
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include "surface-extension-client-protocol.h"
#include <pthread.h>
#include <sys/mman.h>
#include <sys/eventfd.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <errno.h>
#include <stdatomic.h>
#include "native-display-events.h"
void sd_control_install(JNIEnv *env);
int sd_activation_start(const char *path,int (*request)(void),int (*close_request)(void),int (*open_request)(const char *),int (*dump_request)(void));
void sd_activation_stop(void);
static JavaVM *vm;
static _Atomic int callbacks_ready;
static _Atomic int early_window;
static int early_gpu,cached_focus=-1,cached_visibility=-1;
static int callbacks_available(void);
static void emit_focus(int value);
static void wake_host(void);
static void (*native_host_event)(const char*,int);
static void (*native_host_ready)(void);
void sd_window_bind_host_hooks(void (*event)(const char*,int),void (*ready_hook)(void)){native_host_event=event;native_host_ready=ready_hook;}
static void host_window_event(const char *event,int value){if(native_host_event)native_host_event(event,value);}
static jclass host_class,frame_class,surface_class,diagnostics_class;
static jmethodID dump_method;
static jmethodID frame_done,input_event,focus_event,visibility_event,closed_event,open_event;
static pthread_t thread;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ready_condition=PTHREAD_COND_INITIALIZER;
static int wake_fd=-1,ready,want_frame,dirty,want_raise;
static _Atomic int running;
static int source_w,source_h,width,height,configured;
static uint32_t *latest;
static char title[256],app_id[256],failure[256];
static struct wl_display *display;
static struct wl_compositor *compositor;
static struct wl_shm *shm;
static struct wl_seat *seat;
static struct wl_keyboard *keyboard;
static int keyboard_focus_known;
static int last_xdg_active=-1;
static struct wl_surface *surface;
static void *gpu_background_window;
int sd_hwui_background_create(void *native_display,void *native_window);
void sd_hwui_background_destroy(void);
int sd_hwui_background_present(void);
int sd_hwui_background_startup(const char*,int,int);
static int gpu_first_frame_pending,gpu_parent_mapped,gpu_startup_mapped;
static uint64_t gpu_present_count;
static int gpu_timing_enabled(void){static int enabled=-1;if(enabled<0)enabled=getenv("SAILDROID_GPU_TIMING")!=NULL;return enabled;}
static int64_t gpu_clock_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (int64_t)t.tv_sec*1000000000+t.tv_nsec;}

static int64_t bootstrap_next_ns;
static unsigned bootstrap_frames;
static int software_first_frame;
static int create_gpu_background(void) {
    void *library=dlopen("libwayland-egl.so.1",RTLD_NOW|RTLD_GLOBAL);
    void *(*create)(struct wl_surface*,int,int)=library?dlsym(library,"wl_egl_window_create"):NULL;
    if(!create)return -1;
    gpu_background_window=create(surface,source_w,source_h);
    return gpu_background_window?sd_hwui_background_create(display,gpu_background_window):-1;
}
static _Atomic int selected_hardware=-1;
static int hardware_mode(void){int value=atomic_load(&selected_hardware);if(value>=0)return value;const char *mode=getenv("SAILDROID_HWUI");return mode&&!strcmp(mode,"1");}
struct gpu_layer {
    int id,x,y,width,height,visible,pending,z,retired;
    int color_layer,color_pending;uint32_t color;unsigned color_frames;struct color_buffer *color_buffer;
    unsigned stack_order,retire_epoch;int retire_stage;
    struct wl_surface *surface;
    struct wl_subsurface *subsurface;
    void *window;
    struct gpu_layer *next;
};
static struct gpu_layer *gpu_layers;
static unsigned gpu_stack_order;
static int legacy_subsurface_stack;
static struct wl_subcompositor *subcompositor;
static struct gpu_layer *gpu_layer(int id) {
    for(struct gpu_layer *p=gpu_layers;p;p=p->next)if(p->id==id)return p;
    struct gpu_layer *p=calloc(1,sizeof(*p));if(!p)return NULL;
    p->id=id;p->width=source_w;p->height=source_h;p->visible=1;p->next=gpu_layers;gpu_layers=p;return p;
}
/* A service can initialize EGL before it receives its first Activity. Reserve
 * one process-owned Wayland connection at that point, without creating or
 * mapping a toplevel, and reuse it when the first window is started. */
void *sd_window_gpu_display(void){
 if(!hardware_mode())return NULL;
 pthread_mutex_lock(&lock);
 if(!display){display=wl_display_connect(NULL);if(display)fprintf(stderr,"SDHWUI=headless_display_reserved|toplevel=false\n");}
 void *result=display;pthread_mutex_unlock(&lock);return result;
}
/* Keep a hidden layer's last GPU buffer. Detaching NULL loses its content,
 * and a resumed unchanged HWUI tree need not submit another frame. Moving the
 * subsurface outside the parent preserves that buffer for a correct reveal. */
void sd_window_gpu_presented(void) {
    pthread_mutex_lock(&lock);
    if(gpu_timing_enabled()&&gpu_present_count<10000)fprintf(stderr,"SDGPU=swap_done|sequence=%llu|time_ns=%lld\n",(unsigned long long)++gpu_present_count,(long long)gpu_clock_ns());
    if(gpu_parent_mapped||gpu_first_frame_pending){pthread_mutex_unlock(&lock);return;}
    gpu_first_frame_pending=1;pthread_mutex_unlock(&lock);
    if(wake_fd>=0){uint64_t one=1;(void)write(wake_fd,&one,sizeof(one));}
}
void sd_window_gpu_z(int id,int z){
 pthread_mutex_lock(&lock);struct gpu_layer *p=gpu_layer(id);if(p&&p->z!=z){p->z=z;p->pending=1;}pthread_mutex_unlock(&lock);wake_host();
}
/* A removed SurfaceControl can retain live producer references. Unmap its
 * compositor role now, keeping its wl_surface / EGL queue valid for those
 * references. A late swap cannot remap a surface with no role. */
void sd_window_gpu_retire(int id){
 pthread_mutex_lock(&lock);struct gpu_layer *p=gpu_layer(id);
 if(p&&!p->retired){p->retired=1;p->visible=0;p->pending=1;}
 pthread_mutex_unlock(&lock);wake_host();
}
/* Solid SurfaceControl layers have no GLES producer. Use a real wl_shm
 * buffer for their pixels; camera/HWUI layers keep their existing EGL queues.
 * Every allocation stays mapped until the compositor releases it. */
struct color_buffer {struct wl_buffer *buffer;uint32_t *pixels;size_t size;int width,height,busy,current;};
static void color_buffer_free(struct color_buffer *b){if(!b)return;wl_buffer_destroy(b->buffer);munmap(b->pixels,b->size);free(b);}
static void color_buffer_release(void *data,struct wl_buffer *buffer){(void)buffer;struct color_buffer *b=data;b->busy=0;if(!b->current)color_buffer_free(b);}
static const struct wl_buffer_listener color_buffer_listener={color_buffer_release};
static void color_buffer_drop(struct gpu_layer *p){struct color_buffer *b=p->color_buffer;p->color_buffer=NULL;if(b){b->current=0;if(!b->busy)color_buffer_free(b);}}
int sd_window_color(int id,float red,float green,float blue){
 if(id<=0)return -1;
 pthread_mutex_lock(&lock);struct gpu_layer *p=gpu_layer(id);
 if(!p||p->retired||p->window){pthread_mutex_unlock(&lock);return -1;}
 p->color_layer=1;p->color=0xff000000u|((uint32_t)(red*255.f+.5f)<<16)|((uint32_t)(green*255.f+.5f)<<8)|(uint32_t)(blue*255.f+.5f);p->color_pending=1;p->pending=1;
 pthread_mutex_unlock(&lock);wake_host();return 0;
}
static int color_present(struct gpu_layer *p){
 if(p->width<1||p->height<1||p->width>8192||p->height>8192)return -1;
 struct color_buffer *b=calloc(1,sizeof(*b));if(!b)return -1;
 b->width=p->width;b->height=p->height;b->size=(size_t)b->width*b->height*4;
 int fd=memfd_create("saildroid-solid-layer",MFD_CLOEXEC);if(fd<0){free(b);return -1;}
 if(ftruncate(fd,b->size)<0){close(fd);free(b);return -1;}
 b->pixels=mmap(NULL,b->size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);if(b->pixels==MAP_FAILED){close(fd);free(b);return -1;}
 struct wl_shm_pool *pool=wl_shm_create_pool(shm,fd,b->size);close(fd);
 b->buffer=wl_shm_pool_create_buffer(pool,0,b->width,b->height,b->width*4,WL_SHM_FORMAT_ARGB8888);wl_shm_pool_destroy(pool);
 wl_buffer_add_listener(b->buffer,&color_buffer_listener,b);for(size_t i=0;i<b->size/4;i++)b->pixels[i]=p->color;
 if(!p->surface){p->surface=wl_compositor_create_surface(compositor);p->subsurface=wl_subcompositor_get_subsurface(subcompositor,p->surface,surface);p->stack_order=++gpu_stack_order;wl_subsurface_set_desync(p->subsurface);}
 color_buffer_drop(p);p->color_buffer=b;b->current=1;b->busy=1;
 wl_surface_attach(p->surface,b->buffer,0,0);wl_surface_damage(p->surface,0,0,b->width,b->height);wl_surface_commit(p->surface);p->color_pending=0;p->color_frames++;
 fprintf(stderr,"SDSURFACEVIEW=color_shm|id=%d|frame=%u|size=%dx%d|egl_queue=false\n",p->id,p->color_frames,b->width,b->height);return 0;
}
/* Keep retired child roles outside the parent until connection teardown.
 * A frame callback is a pacing event, not a GPU texture lifetime fence. Legacy
 * Qt/Adreno may still reference imported textures after that callback. */
static void gpu_apply_layout(void) {
    if(!hardware_mode())return;
    int changed=0;
    for(struct gpu_layer *p=gpu_layers;p;p=p->next)if(p->color_layer&&!p->retired&&p->color_pending){if(color_present(p)!=0){fprintf(stderr,"SDSURFACEVIEW=color_shm_failed|id=%d\n",p->id);_exit(125);}p->pending=1;}
    for(struct gpu_layer *p=gpu_layers;p;p=p->next)if(p->pending&&p->surface){
        if(p->retired){
            if(p->subsurface)wl_subsurface_set_position(p->subsurface,-4*source_w,-4*source_h);
            if(p->retire_stage==0){
                p->retire_stage=3;
                fprintf(stderr,"SDHWUI=layer_retired|id=%d|producer_queue=retained|compositor_role=offscreen-until-disconnect\n",p->id);
            }
            p->pending=0;changed=1;continue;
        }
        if(p->subsurface)wl_subsurface_set_position(p->subsurface,p->visible?p->x:-4*source_w,p->visible?p->y:-4*source_h);
        if(p->window){
            void (*resize)(void*,int,int,int,int)=dlsym(RTLD_DEFAULT,"wl_egl_window_resize");
            if(resize)resize(p->window,p->width,p->height,0,0);
        }
        changed=1;p->pending=0;
    }
    if(gpu_first_frame_pending&&!gpu_parent_mapped){
        gpu_first_frame_pending=0;
        /* Native hosts keep their startup buffer beneath Android layers. During
         * an Activity replacement Android can hide its old surface before the
         * next surface has a buffer; retaining this parent prevents a blank
         * interval without covering or reading back the real application. */
        if(gpu_startup_mapped||sd_hwui_background_present()==0){if(gpu_startup_mapped)wl_surface_commit(surface);gpu_parent_mapped=1;host_window_event("first-frame",1);fprintf(stderr,"SDHWUI=first_app_frame_presented|parent_mapped=true\n");}
    }
    if(changed){
        /* Android may render an alert before its base Activity. Wayland's
         * creation order must not determine which of them is visible. */
        size_t count=0;for(struct gpu_layer *p=gpu_layers;p;p=p->next)if(p->subsurface)count++;
        struct gpu_layer **ordered=calloc(count?count:1,sizeof(*ordered));
        if(!ordered){fprintf(stderr,"SDHWUI=layer_stack_failed|reason=allocation\n");return;}
        struct gpu_layer *previous=NULL;size_t used=0;int reorder=0;
        for(;;){struct gpu_layer *next=NULL;
            for(struct gpu_layer *p=gpu_layers;p;p=p->next){
                if(!p->subsurface||p->retired)continue;
                if(previous&&(p->z<previous->z||(p->z==previous->z&&p->id<=previous->id)))continue;
                if(!next||p->z<next->z||(p->z==next->z&&p->id<next->id))next=p;
            }
            if(!next)break;
            if(previous&&previous->stack_order>next->stack_order)reorder=1;
            ordered[used++]=next;previous=next;
        }
        /* Sailfish's Qt compositor advertises wl_subcompositor but its legacy
         * implementation ignores place_above/place_below. Recreate only the
         * subsurface roles when the required order changes. The wl_surface,
         * EGL window and GPU buffer queue remain the same. Qt creates its child
         * views in role creation order, with no compositor or renderer restart. */
        if(legacy_subsurface_stack&&reorder){
            /* Keep the longest desired prefix already in creation order.
             * Removing/re-appending only its suffix yields the required order,
             * and preserves live SurfaceView roles/queues in the prefix while
             * their render threads are submitting buffers. Recreating every
             * role needlessly tears down those active compositor views. */
            size_t keep=used?1:0;
            while(keep<used&&ordered[keep-1]->stack_order<ordered[keep]->stack_order)keep++;
            for(size_t i=keep;i<used;i++){wl_subsurface_destroy(ordered[i]->subsurface);ordered[i]->subsurface=NULL;}
            for(size_t i=keep;i<used;i++){
                struct gpu_layer *p=ordered[i];
                p->subsurface=wl_subcompositor_get_subsurface(subcompositor,p->surface,surface);
                p->stack_order=++gpu_stack_order;
                wl_subsurface_set_desync(p->subsurface);
                wl_subsurface_set_position(p->subsurface,p->visible?p->x:-4*source_w,p->visible?p->y:-4*source_h);
                wl_surface_commit(p->surface);
                fprintf(stderr,"SDHWUI=layer_restack|id=%d|z=%d|mode=qt-role-order|retained_prefix=%zu\n",p->id,p->z,keep);
            }
        }else if(!legacy_subsurface_stack){
            for(size_t i=0;i<used;i++)wl_subsurface_place_above(ordered[i]->subsurface,i?ordered[i-1]->surface:surface);
        }
        free(ordered);
    }
    // Subsurface positions become current with the parent's commit, including
    // a reveal with no new Android draw or Choreographer request.
    if(changed)wl_surface_commit(surface);
}
void sd_window_gpu_layout(int id,int x,int y,int w,int h,int visible) {
    pthread_mutex_lock(&lock);struct gpu_layer *p=gpu_layer(id);
    if(p){if(p->color_layer&&(p->width!=w||p->height!=h))p->color_pending=1;p->x=x;p->y=y;p->width=w;p->height=h;p->visible=p->retired?0:visible;p->pending=1;}
    pthread_mutex_unlock(&lock);
    if(wake_fd>=0){uint64_t one=1;(void)write(wake_fd,&one,sizeof(one));}
}
void *sd_window_gpu_window(int id){
    if(!hardware_mode()||id<1||!surface)return NULL;
    pthread_mutex_lock(&lock);struct gpu_layer *p=gpu_layer(id);
    if(p&&p->color_layer){pthread_mutex_unlock(&lock);return NULL;}
    if(p&&!p->window){
        void *library=dlopen("libwayland-egl.so.1",RTLD_NOW|RTLD_GLOBAL);
        void *(*create)(struct wl_surface*,int,int)=library?dlsym(library,"wl_egl_window_create"):NULL;
        if(subcompositor){
            p->surface=wl_compositor_create_surface(compositor);
            if(!p->retired){
                p->subsurface=wl_subcompositor_get_subsurface(subcompositor,p->surface,surface);p->stack_order=++gpu_stack_order;p->pending=1;
                wl_subsurface_set_desync(p->subsurface);
                wl_subsurface_set_position(p->subsurface,p->x,p->y);
            }
            wl_surface_commit(surface);
        }
        if(create&&p->surface)p->window=create(p->surface,p->width,p->height);
        fprintf(stderr,"SDHWUI=wayland_egl_window|id=%d|size=%dx%d|window=%p\n",id,p->width,p->height,p->window);
    }
    void *result=p?p->window:NULL;pthread_mutex_unlock(&lock);return result;
}
static struct xdg_wm_base *shell;
static struct xdg_surface *xdg_surface;
static struct xdg_toplevel *toplevel;
static struct wl_shell *native_shell;
static struct wl_shell_surface *native_shell_surface;
static struct qt_surface_extension *surface_extension;
static struct qt_extended_surface *extended_surface;
static struct wl_callback *frame_callback;
/* Diagnostic switches for the "the app is starved of frame callbacks" question.
   Default (unset) keeps the historical behaviour: one commit is issued whenever the
   app asks for a vsync, with no buffer attached.  attach = additionally re-attach the
   buffer that is currently on screen and damage one pixel, because a commit that
   changes nothing gives the compositor no reason to composite (and the frame
   callback is only sent when it does).  empty = re-issue the bare commit. */
static int force_commit_mode,force_commit_parsed; /* 0 off, 1 attach+damage, 2 empty commit */
static struct buffer *last_attached;
static void force_commit_init(void){
    if(force_commit_parsed)return;
    force_commit_parsed=1;
    const char*v=getenv("SAILDROID_FORCE_FRAME_COMMIT");force_commit_mode=1; /* mark parsed */
    if(!v||!*v){force_commit_mode=0;return;}
    if(!strcmp(v,"attach")||!strcmp(v,"1")){force_commit_mode=1;return;}
    if(!strcmp(v,"empty")){force_commit_mode=2;return;}
    force_commit_mode=0;
}
struct buffer{struct wl_buffer*object;uint32_t*pixels;size_t size;int busy;int ready;int reserved;int src_w,src_h;int64_t perf_sample;};
static struct buffer cover_buffers[2];
static uint32_t *cover_pixels;
static int cover_width,cover_height,cover_pending;

/* Direct-to-shm mode (SAILDROID_DIRECT_SHM=1): the UI thread copies the Java pixel
   array straight into the spare wl_shm buffer instead of into a staging array that
   the window thread then copies again. Same output, one full-screen copy less. The
   staging array stays for the default path, so the change is opt-in and A/B-able. */
static int direct_shm;
/* Direct copy: Java copies Bitmap pixels straight into the spare shm buffer
   (SAILDROID_DIRECT_COPY). Bitmap ARGB_8888 memory is RGBA byte order, i.e.
   the wl_shm format WL_SHM_FORMAT_ABGR8888; if Lipstick does not advertise it
   the path stays off and Java falls back to the int[] staging path. */
static int direct_copy;
static int shm_has_abgr8888;
/* Opaque layers may also use XBGR8888: same RGBA byte order, alpha ignored. */
static int shm_has_xbgr8888;
static int direct_target = -1;
/* sizeof-check: copies that come from an int[] carry 0xAARRGGBB words. When the
   buffers are ABGR8888 (direct-copy mode) the memory order is R,G,B,A, so a word
   written by the staging path has to swap red and blue; the direct path already
   writes RGBA bytes and must not be swizzled. */
static int abgr_buffers(void);
static inline uint32_t swizzle_if_needed(uint32_t pixel){
    if(!abgr_buffers())return pixel;
    return (pixel&0xff00ff00u)|((pixel&0x00ff0000u)>>16)|((pixel&0x000000ffu)<<16);
}
static void copy_scaled(uint32_t*dst,const uint32_t*src,int sw,int sh,int dw,int dh){
    if(sw==dw&&sh==dh){
        if(!abgr_buffers()){memcpy(dst,src,(size_t)dw*dh*4);return;}
        for(size_t i=0;i<(size_t)dw*dh;i++)dst[i]=swizzle_if_needed(src[i]);
        return;
    }
    for(int y=0;y<dh;y++){int sy=(int)((int64_t)y*sh/dh);
        for(int x=0;x<dw;x++)dst[(size_t)y*dw+x]=swizzle_if_needed(src[(size_t)sy*sw+(int)((int64_t)x*sw/dw)]);}
}
#define MAX_BUFFERS 3
static struct buffer buffers[MAX_BUFFERS];
static int buffer_count=2; /* SAILDROID_TRIPLE_BUFFER gives the UI one more frame in flight */
static float pointer_x,pointer_y;
static JNIEnv *thread_env;
static int64_t monotonic_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return(int64_t)t.tv_sec*1000000000+t.tv_nsec;}
/* ------------------------------------------------------------------------
 * Optional per-frame performance sampling.
 *
 * Enabled only by the environment (SAILDROID_PERF=1) so the normal product
 * path is unchanged. Records are appended in memory and written out once when
 * the window thread stops; nothing is logged per frame.
 *
 * Timeline per committed frame (all CLOCK_MONOTONIC nanoseconds):
 *   lock     - first Surface.lockCanvas after the previous vsync
 *   unlock   - Canvas.UnlockCanvasAndPost entered (View.draw/Canvas finished)
 *   present  - SdWindowHost.present entered (Java compose + getPixels done)
 *   pdone    - int[] -> native copy finished
 *   memcpy   - int[] -> wl_shm memcpy duration measured in publish()
 *   commit   - wl_surface_commit returned
 *   release  - wl_buffer.release for that buffer (compositor consumed it)
 *   vsync    - last wl frame callback before this frame's draw started
 *   input    - most recent injected touch event before this present
 *
 * The timestamps crossing the JNI boundary are written by the Android/UI
 * thread and read by the Wayland thread. They are naturally aligned 64-bit
 * values, so a race can only mix two adjacent frames; it cannot corrupt the
 * structure of a record.
 * --------------------------------------------------------------------- */
#define PERF_MAX_SAMPLES 20000
struct perf_sample{
    int64_t vsync_ns,lock_ns,lock_ret_ns,unlock_ns,present_ns,present_done_ns;
    int64_t mutex_wait_ns,memcpy_ns,commit_ns,release_ns,input_ns,draw_ns,ui_total_ns,vsync_gap_ns;
    int32_t draws,commits_in_vsync,dropped;
};
static int perf_on;
static struct perf_sample *perf_samples;
static size_t perf_count,perf_lost;
static int64_t perf_draw_start,perf_draw_ns,perf_unlock_ns,perf_lock_ret_ns,perf_present_ns,perf_present_done_ns,perf_memcpy_ns;
static int64_t perf_mutex_wait_ns;
static int perf_commits_since_vsync;
static int64_t perf_dropped_pending,perf_presents;
static jfieldID perf_compose_field,perf_erase_field,perf_draw_field,perf_pixels_field,perf_present_java_field,perf_locks_field,perf_unlocks_field,perf_transactions_field;
static jfieldID perf_direct_copies_field,perf_direct_misses_field,perf_direct_drops_field,perf_recoveries_field;
static jfieldID perf_creq_field,perf_cfall_field,perf_fast_field,perf_layers_field,perf_layer_alpha_field,perf_layer_full_field,perf_layer_ident_field;
static int perf_fields_ok=1;
/* native 侧用 GetStaticFieldID 按名字+签名取 Java 静态字段。名字/类型一旦对不上，
   GetStaticFieldID 返回 NULL 并留下 pending NoSuchFieldError；ART 会在下一个 JNI 调用
   处以 "No pending exception expected" 直接 abort 整个进程（2026-10-26 真机事故：
   lastLayerCount 在 Java 侧是 int、这里是 J，QQ 启动即 SIGSEGV）。所以这里统一检查、
   清异常、打一行能 grep 的诊断，并把采样关掉，绝不让一个计时字段打死应用。 */
static void sd_perf_fields_guard(JNIEnv*e){
  struct{const char*n;jfieldID v;} fs[]={
    {"composes",perf_compose_field},{"composeEraseNs",perf_erase_field},
    {"composeDrawNs",perf_draw_field},{"composePixelsNs",perf_pixels_field},
    {"composePresentNs",perf_present_java_field},{"locks",perf_locks_field},
    {"unlocks",perf_unlocks_field},{"draws",perf_transactions_field},
    {"composeRequests",perf_creq_field},{"composeFallbacks",perf_cfall_field},
    {"fastPathFrames",perf_fast_field},{"lastLayerCount",perf_layers_field},
    {"lastLayerAlphaMilli",perf_layer_alpha_field},{"lastLayerFull",perf_layer_full_field},
    {"lastLayerIdentity",perf_layer_ident_field}};
  unsigned i;
  for(i=0;i<sizeof(fs)/sizeof(fs[0]);i++){
    if(fs[i].v)continue;
    if((*e)->ExceptionCheck(e))(*e)->ExceptionClear(e);
    fprintf(stderr,"SDNATIVE=perf_field_missing|%s|J\n",fs[i].n);fflush(stderr);
    perf_fields_ok=0;
  }
  if(!perf_fields_ok)perf_on=0;
}
static int64_t perf_last_vsync_ns,perf_last_input_ns;
static int64_t perf_prev_frame_ns,perf_frame_gap_ns=-1;
static int perf_draws;
static int64_t perf_start_ns,perf_ready_ns,perf_alloc_ns;
static int64_t perf_dropped;
static int64_t perf_touch_events;
/* Vsync plumbing counters. The question they answer: does the app ask for a
   vsync at all, does the ask reach the window thread, does the compositor answer,
   and are we committing frames to make that answer possible? Counted without
   atomics (a lost increment on a rare race is irrelevant to a ratio); they only
   exist when SAILDROID_PERF is set. */
static int64_t perf_display_init_calls,perf_display_schedule_calls,perf_request_frame_calls,perf_frame_callbacks,perf_frame_commits,perf_empty_commits;
static int64_t perf_init_ns;
static FILE*perf_stream;
/* Frames are appended as they commit, not buffered until the window thread
   stops: a client that dies from System.exit() (QQ does) must still leave the
   samples that were already taken. Lines are flushed per frame; the cost is one
   small write per commit and it only exists when SAILDROID_PERF is set. */
static void perf_open_stream(void){
    const char*path=getenv("SAILDROID_PERF_FILE");
    if(perf_stream||!path)return;
    perf_stream=fopen(path,"w");
}
static void perf_write_frame(size_t i,const struct perf_sample*s){
    if(!perf_stream)return;
    fprintf(perf_stream,"SDPERF=frame|i=%zu|vsync=%lld|lock=%lld|lr=%lld|unlock=%lld|present=%lld|pdone=%lld|mw=%lld|memcpy=%lld|commit=%lld|release=%lld|draw=%lld|ui=%lld|gap=%lld|draws=%d|cinv=%d|drop=%d|input=%lld\n",
            i,(long long)s->vsync_ns,(long long)s->lock_ns,(long long)s->lock_ret_ns,(long long)s->unlock_ns,
            (long long)s->present_ns,(long long)s->present_done_ns,(long long)s->mutex_wait_ns,
            (long long)s->memcpy_ns,(long long)s->commit_ns,(long long)s->release_ns,
            (long long)s->draw_ns,(long long)s->ui_total_ns,(long long)s->vsync_gap_ns,
            s->draws,s->commits_in_vsync,s->dropped,(long long)s->input_ns);
    fflush(perf_stream);
}
static void perf_mark_input(void){if(!perf_on)return;perf_last_input_ns=monotonic_ns();perf_touch_events++;}
static void perf_record_commit(struct buffer*b){
    if(!perf_on)return;
    if(perf_count>=PERF_MAX_SAMPLES){perf_lost++;return;}
    struct perf_sample*s=&perf_samples[perf_count];
    memset(s,0,sizeof(*s));
    s->vsync_ns=perf_last_vsync_ns;s->lock_ns=perf_draw_start;s->lock_ret_ns=perf_lock_ret_ns;
    s->unlock_ns=perf_unlock_ns;s->present_ns=perf_present_ns;s->present_done_ns=perf_present_done_ns;
    s->mutex_wait_ns=perf_mutex_wait_ns;s->memcpy_ns=perf_memcpy_ns;s->commit_ns=monotonic_ns();
    s->input_ns=perf_last_input_ns;s->draw_ns=perf_draw_ns;s->draws=perf_draws;
    /* UI-thread time spent inside one compose/present cycle: Java lock bookkeeping,
       View.draw, compose + getPixels, and the JNI copy (including mutex wait). */
    if(perf_present_done_ns&&perf_draw_start)s->ui_total_ns=perf_present_done_ns-perf_draw_start;
    s->vsync_gap_ns=perf_frame_gap_ns;
    s->commits_in_vsync=++perf_commits_since_vsync;
    s->dropped=(int32_t)perf_dropped_pending;perf_dropped_pending=0;
    b->perf_sample=(int64_t)perf_count;
    perf_write_frame(perf_count,s);
    perf_count++;
    perf_draw_ns=0;perf_draws=0;perf_draw_start=0;perf_last_input_ns=0;
}
static void perf_dump(void){
    if(!perf_on)return;
    perf_init_ns=perf_ready_ns-perf_start_ns;
    const char*path=getenv("SAILDROID_PERF_FILE");
    perf_open_stream();
    FILE*f=perf_stream?perf_stream:(path?fopen(path,"w"):NULL);
    if(f){
        long long composes=-1;
    if(thread_env&&perf_compose_field)composes=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_compose_field);
    long long erase=-1,blit=-1,pixels=-1,jpresent=-1,creq=-1,cfall=-1,fast=-1,layers_cnt=-1,layer_alpha=-1,layer_full=-1,layer_ident=-1,java_locks=-1,java_unlocks=-1,java_draws=-1,java_direct=-1,java_dmiss=-1,java_ddrop=-1,java_drec=-1;
    if(thread_env){
        if(perf_erase_field)erase=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_erase_field);
        if(perf_draw_field)blit=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_draw_field);
        if(perf_pixels_field)pixels=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_pixels_field);
        if(perf_present_java_field)jpresent=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_present_java_field);
        if(perf_creq_field)creq=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_creq_field);
        if(perf_cfall_field)cfall=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_cfall_field);
        if(perf_fast_field)fast=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_fast_field);
        if(perf_layers_field)layers_cnt=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_layers_field);
        if(perf_layer_alpha_field)layer_alpha=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_layer_alpha_field);
        if(perf_layer_full_field)layer_full=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_layer_full_field);
        if(perf_layer_ident_field)layer_ident=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_layer_ident_field);
        if(perf_locks_field)java_locks=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_locks_field);
        if(perf_direct_copies_field)java_direct=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_direct_copies_field);
        if(perf_direct_misses_field)java_dmiss=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_direct_misses_field);
        if(perf_direct_drops_field)java_ddrop=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_direct_drops_field);
        if(perf_recoveries_field)java_drec=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_recoveries_field);
        if(perf_unlocks_field)java_unlocks=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_unlocks_field);
        if(perf_transactions_field)java_draws=(long long)(*thread_env)->GetStaticLongField(thread_env,surface_class,perf_transactions_field);
    }
    fprintf(f,"SDPERF=meta|api=5|samples=%zu|lost=%zu|dropped=%lld|touch=%lld|init_ns=%lld|alloc_ns=%lld|presents=%lld|composes=%lld|erase_ns=%lld|blit_ns=%lld|getpixels_ns=%lld|jpresent_ns=%lld|creq=%lld|cfall=%lld|fast=%lld|layers=%lld|layer_alpha=%lld|layer_full=%lld|layer_identity=%lld|locks=%lld|unlocks=%lld|jdraws=%lld|dinit=%lld|dsched=%lld|rf=%lld|fcb=%lld|fcommit=%lld|ecommit=%lld|force=%lld|direct=%d|dcopy=%lld|dmiss=%lld|ddrop=%lld|drecover=%lld\n",
                perf_count,perf_lost,(long long)perf_dropped,(long long)perf_touch_events,
                (long long)perf_init_ns,(long long)perf_alloc_ns,(long long)perf_presents,composes,
                erase,blit,pixels,jpresent,creq,cfall,fast,layers_cnt,layer_alpha,layer_full,layer_ident,
                java_locks,java_unlocks,java_draws,
                (long long)perf_display_init_calls,(long long)perf_display_schedule_calls,
                (long long)perf_request_frame_calls,(long long)perf_frame_callbacks,
                (long long)perf_frame_commits,(long long)perf_empty_commits,(long long)force_commit_mode,direct_shm,
                java_direct,java_dmiss,java_ddrop,java_drec);
        fclose(f);
        if(f==perf_stream)perf_stream=NULL;
    }
    fprintf(stderr,"SDPERF=summary|samples=%zu|lost=%zu|dropped=%lld|touch=%lld|file=%s\n",
            perf_count,perf_lost,(long long)perf_dropped,(long long)perf_touch_events,path?path:"(none)");
    fflush(stderr);
}
static void wake_host(void){uint64_t one=1;if(wake_fd>=0){ssize_t result;do{result=write(wake_fd,&one,sizeof(one));}while(result<0&&errno==EINTR);}}
static int callbacks_available(void){
 if(!atomic_load_explicit(&callbacks_ready,memory_order_acquire))return 0;
 if(!thread_env&&(*vm)->AttachCurrentThreadAsDaemon(vm,(void**)&thread_env,NULL)!=JNI_OK)return 0;
 return 1;
}
static void check_callback(void){if((*thread_env)->ExceptionCheck(thread_env)){(*thread_env)->ExceptionDescribe(thread_env);(*thread_env)->ExceptionClear(thread_env);}}
static void emit_focus(int value){if(cached_focus!=value)host_window_event("focus",value);cached_focus=value;if(callbacks_available()){(*thread_env)->CallStaticVoidMethod(thread_env,host_class,focus_event,(jboolean)value);check_callback();}}
static void emit_input(int action,int id,float x,float y){if(!callbacks_available())return;perf_mark_input();(*thread_env)->CallStaticVoidMethod(thread_env,host_class,input_event,action,id,x*(float)source_w/width,y*(float)source_h/height,(jlong)monotonic_ns());check_callback();}
static int request_activation(void){pthread_mutex_lock(&lock);int available=running&&extended_surface;if(available)want_raise=1;pthread_mutex_unlock(&lock);if(available)wake_host();return available;}
static int request_dump(void){
    if(!atomic_load(&callbacks_ready))return 0;
    JNIEnv *env=NULL;if((*vm)->AttachCurrentThreadAsDaemon(vm,(void**)&env,NULL)!=JNI_OK)return 0;
    (*env)->CallStaticVoidMethod(env,diagnostics_class,dump_method);int success=!(*env)->ExceptionCheck(env);
    if(!success){(*env)->ExceptionDescribe(env);(*env)->ExceptionClear(env);}
    (*vm)->DetachCurrentThread(vm);return success;
}
static int request_open(const char *uri){
    if(!atomic_load(&callbacks_ready)||!running||strcmp(title,"org.saildroid.manager"))return 0;
    JNIEnv *env=NULL;
    if((*vm)->AttachCurrentThreadAsDaemon(vm,(void**)&env,NULL)!=JNI_OK)return 0;
    jstring value=(*env)->NewStringUTF(env,uri);
    int success=value&&(*env)->CallStaticBooleanMethod(env,host_class,open_event,value);
    if((*env)->ExceptionCheck(env)){(*env)->ExceptionDescribe(env);(*env)->ExceptionClear(env);success=0;}
    if(value)(*env)->DeleteLocalRef(env,value);
    (*vm)->DetachCurrentThread(vm);return success;
}
static _Atomic int close_requested;
static int request_close(void){
    int active=running;
    if(!active)return 0;
    fprintf(stderr,"SDWINDOW=close_requested\n");
    if(!atomic_load(&callbacks_ready)){fprintf(stderr,"SDHOST=closed_before_art_ready\n");fflush(stderr);_exit(0);}
    if(hardware_mode()){
        /* RenderThread may be swapping on a different Wayland event queue.
         * Ask the application main loop to destroy Activities before process
         * exit; disconnecting this display here races an in-flight GPU swap. */
        if(!atomic_exchange(&close_requested,1)){
            JNIEnv *env=NULL;int attached=(*vm)->GetEnv(vm,(void**)&env,JNI_VERSION_1_6)!=JNI_OK;
            if(attached&&(*vm)->AttachCurrentThreadAsDaemon(vm,(void**)&env,NULL)!=JNI_OK)return 0;
            (*env)->CallStaticVoidMethod(env,host_class,closed_event);
            if((*env)->ExceptionCheck(env)){(*env)->ExceptionDescribe(env);(*env)->ExceptionClear(env);}
            if(attached)(*vm)->DetachCurrentThread(vm);
        }
    }else{running=0;wake_host();}
    return active;
}
static void visibility_changed(void *data,struct qt_extended_surface *ext,int32_t visible){(void)data;(void)ext;fprintf(stderr,"SDWINDOW=visibility|value=%d\n",visible);if(visible==0||visible==3){emit_focus(0);}if(cached_visibility!=visible)host_window_event("visibility",visible);cached_visibility=visible;if(callbacks_available()){(*thread_env)->CallStaticVoidMethod(thread_env,host_class,visibility_event,(jint)visible);check_callback();}}
static void generic_property(void *data,struct qt_extended_surface *ext,const char *name,struct wl_array *value){(void)data;(void)ext;(void)name;(void)value;/* No Qt QVariant property is advertised by this native client. */}
static void extended_close(void *data,struct qt_extended_surface *ext){(void)data;(void)ext;request_close();}
static const struct qt_extended_surface_listener extended_listener={visibility_changed,generic_property,extended_close};
static void ping(void*d,struct xdg_wm_base*s,uint32_t serial){(void)d;xdg_wm_base_pong(s,serial);}
static const struct xdg_wm_base_listener shell_listener={.ping=ping};
static void configure_surface(void*d,struct xdg_surface*s,uint32_t serial){(void)d;xdg_surface_ack_configure(s,serial);configured=1;}
static const struct xdg_surface_listener surface_listener={.configure=configure_surface};
static void configure_dimensions(int32_t w, int32_t h) {
    if (!width) {
        width = w > 0 ? w : (source_w > 0 ? source_w : 1080);
        height = h > 0 ? h : (source_h > 0 ? source_h : 2160);
    }
}
static void configure_top(void *data, struct xdg_toplevel *top, int32_t w,
                          int32_t h, struct wl_array *states) {
    (void)data;
    (void)top;
    configure_dimensions(w, h);
    uint32_t *state;
    int active = 0, fullscreen = 0;
    wl_array_for_each(state, states) {
        if (*state == XDG_TOPLEVEL_STATE_ACTIVATED) active = 1;
        if (*state == XDG_TOPLEVEL_STATE_FULLSCREEN) fullscreen = 1;
    }
    fprintf(stderr,"SDWINDOW=configure|size=%dx%d|fullscreen=%s|active=%s\n",w,h,
            fullscreen?"true":"false",active?"true":"false");
    if (!keyboard_focus_known && active != last_xdg_active) emit_focus(active);
    last_xdg_active = active;
}

static int prepare_display(void) {
    if (!source_w) source_w = width;
    if (!source_h) source_h = height;
    if (source_w <= 0 || source_h <= 0 ||
        (size_t)source_w > SIZE_MAX / sizeof(uint32_t) / (size_t)source_h) {
        snprintf(failure, sizeof(failure), "Invalid display dimensions");
        return -1;
    }
    latest = calloc((size_t)source_w * source_h, sizeof(uint32_t));
    if (!latest) {
        snprintf(failure, sizeof(failure), "Display allocation failed");
        return -1;
    }
    // ART starts after bootstrap returns. Java reads the same content dimensions.
    char pixels[32];
    snprintf(pixels, sizeof(pixels), "%d", source_w);
    if (setenv("SAILDROID_DISPLAY_WIDTH", pixels, 1) != 0) return -1;
    snprintf(pixels, sizeof(pixels), "%d", source_h);
    if (setenv("SAILDROID_DISPLAY_HEIGHT", pixels, 1) != 0) return -1;
    return 0;
}
static void close_top(void*d,struct xdg_toplevel*t){(void)d;(void)t;request_close();}
static const struct xdg_toplevel_listener top_listener={.configure=configure_top,.close=close_top};
static void native_shell_ping(void *data, struct wl_shell_surface *role, uint32_t serial) {
    (void)data;
    wl_shell_surface_pong(role, serial);
}
static void native_shell_configure(void *data, struct wl_shell_surface *role,
                                   uint32_t edges, int32_t w, int32_t h) {
    (void)data;
    (void)role;
    (void)edges;
    configure_dimensions(w, h);
    configured = 1;
    fprintf(stderr, "SDWINDOW=configure|shell=wl_shell|size=%dx%d|fullscreen=requested\n", w, h);
}
static void native_shell_popup_done(void *data, struct wl_shell_surface *role) {
    (void)data;
    (void)role;
}
static const struct wl_shell_surface_listener native_shell_listener = {
    .ping = native_shell_ping,
    .configure = native_shell_configure,
    .popup_done = native_shell_popup_done
};
static void create_window_role(void) {
    // Lipstick's native wrapper fills the display. Its desktop XDG wrapper
    // adds corner/cutout avoidance and applies the desktop window scale.
    if (surface_extension && native_shell) {
        native_shell_surface = wl_shell_get_shell_surface(native_shell, surface);
        wl_shell_surface_add_listener(native_shell_surface, &native_shell_listener, NULL);
        wl_shell_surface_set_title(native_shell_surface, title);
        wl_shell_surface_set_class(native_shell_surface, app_id);
        wl_shell_surface_set_toplevel(native_shell_surface);
        wl_shell_surface_set_fullscreen(native_shell_surface,
                WL_SHELL_SURFACE_FULLSCREEN_METHOD_DEFAULT, 0, NULL);
        fprintf(stderr, "SDWINDOW=role|shell=wl_shell|wrapper=native\n");
    } else {
        xdg_surface = xdg_wm_base_get_xdg_surface(shell, surface);
        xdg_surface_add_listener(xdg_surface, &surface_listener, NULL);
        toplevel = xdg_surface_get_toplevel(xdg_surface);
        xdg_toplevel_add_listener(toplevel, &top_listener, NULL);
        xdg_toplevel_set_title(toplevel, title);
        xdg_toplevel_set_app_id(toplevel, app_id);
        xdg_toplevel_set_fullscreen(toplevel, NULL);
        fprintf(stderr, "SDWINDOW=role|shell=xdg_shell|fullscreen_requested=true\n");
    }
}
/* 输入链路取证（同 `<clinit>` 一样属于"不许靠猜"的地方）：Wayland 触摸到底有没有被
   合成器投递到我们这个表面？以前只有代码路径没有证据，点了没反应只能靠推断。
   这行打在 su!=surface 的早退之前，所以"匹配失败"和"根本没收到"能被区分开。 */
struct touch_origin {int id;float x,y;int active;};
static struct touch_origin touch_origins[32];
static void gpu_surface_origin(struct wl_surface *target,float *x,float *y) {
    *x=*y=0;if(!hardware_mode())return;
    pthread_mutex_lock(&lock);
    for(struct gpu_layer *p=gpu_layers;p;p=p->next)if(p->surface==target){*x=p->x;*y=p->y;break;}
    pthread_mutex_unlock(&lock);
}
static struct touch_origin *touch_origin(int id,int create) {
    struct touch_origin *empty=NULL;
    for(unsigned i=0;i<32;i++){if(touch_origins[i].active&&touch_origins[i].id==id)return &touch_origins[i];if(!touch_origins[i].active)empty=&touch_origins[i];}
    if(create&&empty){empty->id=id;empty->active=1;empty->x=empty->y=0;return empty;}return NULL;
}
static void touch_down(void*d,struct wl_touch*t,uint32_t s,uint32_t tm,struct wl_surface*su,int32_t id,wl_fixed_t x,wl_fixed_t y){
 (void)d;(void)t;(void)s;(void)tm;
 fprintf(stderr,"SDINPUT=touch_down|match=%d|id=%d|x=%d|y=%d|su=%p|surface=%p\n",su==surface,id,wl_fixed_to_int(x),wl_fixed_to_int(y),(void*)su,(void*)surface);
 if(su!=surface&&!hardware_mode())return;
 struct touch_origin *origin=touch_origin(id,1);float ox=0,oy=0;gpu_surface_origin(su,&ox,&oy);
 if(origin){origin->x=ox;origin->y=oy;}
 emit_focus(1);
 emit_input(0,id,wl_fixed_to_double(x)+ox,wl_fixed_to_double(y)+oy);
}
static void touch_up(void*d,struct wl_touch*t,uint32_t s,uint32_t tm,int32_t id){
 (void)d;(void)t;(void)s;(void)tm;emit_input(1,id,0,0);struct touch_origin *origin=touch_origin(id,0);if(origin)origin->active=0;
}
static void touch_motion(void*d,struct wl_touch*t,uint32_t tm,int32_t id,wl_fixed_t x,wl_fixed_t y){
 (void)d;(void)t;(void)tm;struct touch_origin *origin=touch_origin(id,0);
 emit_input(2,id,wl_fixed_to_double(x)+(origin?origin->x:0),wl_fixed_to_double(y)+(origin?origin->y:0));
}
static void touch_frame(void*d,struct wl_touch*t){(void)d;(void)t;}
static void touch_cancel(void*d,struct wl_touch*t){(void)d;(void)t;emit_input(3,0,0,0);}
static const struct wl_touch_listener touch_listener={touch_down,touch_up,touch_motion,touch_frame,touch_cancel};
static float pointer_origin_x,pointer_origin_y;
static void pointer_enter(void*d,struct wl_pointer*p,uint32_t serial,struct wl_surface*s,wl_fixed_t x,wl_fixed_t y){(void)d;(void)p;(void)serial;gpu_surface_origin(s,&pointer_origin_x,&pointer_origin_y);pointer_x=wl_fixed_to_double(x)+pointer_origin_x;pointer_y=wl_fixed_to_double(y)+pointer_origin_y;}
static void pointer_leave(void*d,struct wl_pointer*p,uint32_t serial,struct wl_surface*s){(void)d;(void)p;(void)serial;(void)s;}
static void pointer_motion(void*d,struct wl_pointer*p,uint32_t tm,wl_fixed_t x,wl_fixed_t y){(void)d;(void)p;(void)tm;pointer_x=wl_fixed_to_double(x)+pointer_origin_x;pointer_y=wl_fixed_to_double(y)+pointer_origin_y;emit_input(2,0,pointer_x,pointer_y);}
static void pointer_button(void*d,struct wl_pointer*p,uint32_t serial,uint32_t tm,uint32_t button,uint32_t state){(void)d;(void)p;(void)serial;(void)tm;fprintf(stderr,"SDINPUT=pointer_button|button=%u|state=%u|x=%d|y=%d\n",button,state,wl_fixed_to_int(pointer_x),wl_fixed_to_int(pointer_y));fflush(stderr);if(button==272){if(state){emit_focus(1);}emit_input(state?0:1,0,pointer_x,pointer_y);}}
static void pointer_axis(void*d,struct wl_pointer*p,uint32_t tm,uint32_t a,wl_fixed_t v){(void)d;(void)p;(void)tm;(void)a;(void)v;}
static const struct wl_pointer_listener pointer_listener={pointer_enter,pointer_leave,pointer_motion,pointer_button,pointer_axis};
/* Sailfish can deliver keyboard focus without xdg-shell's activated state.
 * wl_keyboard enter/leave is the authoritative seat focus once observed. */
static void keyboard_keymap(void *data,struct wl_keyboard *key,uint32_t format,int fd,uint32_t size){(void)data;(void)key;(void)format;(void)size;close(fd);}
static void keyboard_enter(void *data,struct wl_keyboard *key,uint32_t serial,struct wl_surface *target,struct wl_array *keys){
    (void)data;(void)key;(void)serial;(void)keys;if(target!=surface)return;keyboard_focus_known=1;
    emit_focus(1);fprintf(stderr,"SDWINDOW=seat_focus|active=true\n");
}
static void keyboard_leave(void *data,struct wl_keyboard *key,uint32_t serial,struct wl_surface *target){
    (void)data;(void)key;(void)serial;if(target!=surface)return;keyboard_focus_known=1;
    emit_focus(0);fprintf(stderr,"SDWINDOW=seat_focus|active=false\n");
}
static void keyboard_key(void *data,struct wl_keyboard *key,uint32_t serial,uint32_t time,uint32_t code,uint32_t state){(void)data;(void)key;(void)serial;(void)time;(void)code;(void)state;/* Text input uses the Maliit InputConnection session. */}
static void keyboard_modifiers(void *data,struct wl_keyboard *key,uint32_t serial,uint32_t depressed,uint32_t latched,uint32_t locked,uint32_t group){(void)data;(void)key;(void)serial;(void)depressed;(void)latched;(void)locked;(void)group;}
static const struct wl_keyboard_listener keyboard_listener={.keymap=keyboard_keymap,.enter=keyboard_enter,.leave=keyboard_leave,.key=keyboard_key,.modifiers=keyboard_modifiers};
static void seat_caps(void*d,struct wl_seat*s,uint32_t caps){(void)d;fprintf(stderr,"SDINPUT=seat_caps|caps=%u|touch=%d|pointer=%d\n",caps,(caps&WL_SEAT_CAPABILITY_TOUCH)?1:0,(caps&WL_SEAT_CAPABILITY_POINTER)?1:0);fflush(stderr);if(caps&WL_SEAT_CAPABILITY_TOUCH){struct wl_touch*t=wl_seat_get_touch(s);wl_touch_add_listener(t,&touch_listener,NULL);}if(caps&WL_SEAT_CAPABILITY_POINTER){struct wl_pointer*p=wl_seat_get_pointer(s);wl_pointer_add_listener(p,&pointer_listener,NULL);}if((caps&WL_SEAT_CAPABILITY_KEYBOARD)&&!keyboard){keyboard=wl_seat_get_keyboard(s);wl_keyboard_add_listener(keyboard,&keyboard_listener,NULL);}else if(!(caps&WL_SEAT_CAPABILITY_KEYBOARD)&&keyboard){wl_keyboard_destroy(keyboard);keyboard=NULL;keyboard_focus_known=0;}}
static void seat_name(void*d,struct wl_seat*s,const char*n){(void)d;(void)s;(void)n;}
static const struct wl_seat_listener seat_listener={seat_caps,seat_name};
static void shm_format(void*d,struct wl_shm*s,uint32_t format){(void)d;(void)s;if(format==WL_SHM_FORMAT_ABGR8888)shm_has_abgr8888=1;else if(format==WL_SHM_FORMAT_XBGR8888)shm_has_xbgr8888=1;}
static const struct wl_shm_listener shm_listener={shm_format};
static int abgr_buffers(void){return direct_copy&&(shm_has_abgr8888||shm_has_xbgr8888);}
static uint32_t buffer_format(void){
    if(!abgr_buffers())return WL_SHM_FORMAT_ARGB8888;
    return shm_has_abgr8888?WL_SHM_FORMAT_ABGR8888:WL_SHM_FORMAT_XBGR8888;
}
static void global(void*d,struct wl_registry*r,uint32_t name,const char*iface,uint32_t version){(void)d;if(!strcmp(iface,"wl_subcompositor")){subcompositor=wl_registry_bind(r,name,&wl_subcompositor_interface,1);return;}if(!strcmp(iface,"wl_compositor"))compositor=wl_registry_bind(r,name,&wl_compositor_interface,version<3?version:3);else if(!strcmp(iface,"wl_shm")){shm=wl_registry_bind(r,name,&wl_shm_interface,1);wl_shm_add_listener(shm,&shm_listener,NULL);}else if(!strcmp(iface,"wl_shell")){native_shell=wl_registry_bind(r,name,&wl_shell_interface,1);}else if(!strcmp(iface,"xdg_wm_base")){shell=wl_registry_bind(r,name,&xdg_wm_base_interface,1);xdg_wm_base_add_listener(shell,&shell_listener,NULL);}else if(!strcmp(iface,"qt_surface_extension")){surface_extension=wl_registry_bind(r,name,&qt_surface_extension_interface,1);legacy_subsurface_stack=getenv("SAILDROID_SUBSURFACE_NATIVE_STACK")==NULL;}else if(!strcmp(iface,"wl_seat")){seat=wl_registry_bind(r,name,&wl_seat_interface,version<3?version:3);wl_seat_add_listener(seat,&seat_listener,NULL);}}
static void global_remove(void*d,struct wl_registry*r,uint32_t name){(void)d;(void)r;(void)name;}
static const struct wl_registry_listener registry_listener={global,global_remove};
static void buffer_released(void*data,struct wl_buffer*b){(void)b;struct buffer*slot=(struct buffer*)data;if(perf_on&&slot->perf_sample>=0&&(size_t)slot->perf_sample<perf_count)perf_samples[slot->perf_sample].release_ns=monotonic_ns();slot->busy=0;if(cover_pending&&(slot==&cover_buffers[0]||slot==&cover_buffers[1]))wake_host();}
static const struct wl_buffer_listener buffer_listener={buffer_released};
static int allocate_buffer(struct buffer*b){int fd=memfd_create("saildroid-window",MFD_CLOEXEC);if(fd<0)return-1;b->size=(size_t)width*height*4;if(ftruncate(fd,b->size)<0){close(fd);return-1;}b->pixels=mmap(NULL,b->size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);if(b->pixels==MAP_FAILED){close(fd);return-1;}struct wl_shm_pool*pool=wl_shm_create_pool(shm,fd,b->size);b->object=wl_shm_pool_create_buffer(pool,0,width,height,width*4,buffer_format());wl_shm_pool_destroy(pool);close(fd);wl_buffer_add_listener(b->object,&buffer_listener,b);for(size_t i=0;i<b->size/4;i++)b->pixels[i]=swizzle_if_needed(0xff101820);b->perf_sample=-1;return 0;}
static void frame_complete(void*d,struct wl_callback*callback,uint32_t time){(void)d;(void)time;wl_callback_destroy(callback);frame_callback=NULL;int64_t now=monotonic_ns();if(perf_on){perf_frame_callbacks++;perf_last_vsync_ns=now;perf_commits_since_vsync=0;perf_frame_gap_ns=perf_prev_frame_ns?now-perf_prev_frame_ns:-1;perf_prev_frame_ns=now;}sd_native_display_frame(now);if(callbacks_available()){(*thread_env)->CallStaticVoidMethod(thread_env,host_class,frame_done,(jlong)now);check_callback();}}
static const struct wl_callback_listener frame_listener={frame_complete};
static void publish(void){
 if(callbacks_available()&&early_window==1){
  early_window=2;
  if(cached_focus>=0)emit_focus(cached_focus);
  if(cached_visibility>=0){(*thread_env)->CallStaticVoidMethod(thread_env,host_class,visibility_event,(jint)cached_visibility);check_callback();}
 }
 pthread_mutex_lock(&lock);
 if(early_gpu&&!hardware_mode()){
  sd_hwui_background_destroy();early_gpu=0;
  for(int i=0;i<buffer_count;i++)if(allocate_buffer(&buffers[i])){pthread_mutex_unlock(&lock);_exit(125);}
  pthread_cond_broadcast(&ready_condition);
  fprintf(stderr,"SDHOST=backend_handoff|target=software|same_surface=true\n");
 }
 gpu_apply_layout();
 /* A stopped Android renderer can unmap its EGL buffer before the shell
  * copies a thumbnail. Commit one app-render-tree snapshot after stop settles.
  * This path is used only on background transitions, never during app draws. */
 if(cover_pending){
  if(cached_focus==1){free(cover_pixels);cover_pixels=NULL;cover_pending=0;}
  else{
   struct buffer *target=NULL;
   for(unsigned i=0;i<2;i++)if(!cover_buffers[i].busy){target=&cover_buffers[i];break;}
   if(target){
    if(!target->object&&allocate_buffer(target)!=0){fprintf(stderr,"SDCOVER=failed|reason=shm-allocation\n");free(cover_pixels);cover_pixels=NULL;cover_pending=0;}
    else{
     copy_scaled(target->pixels,cover_pixels,cover_width,cover_height,width,height);
     target->busy=1;wl_surface_attach(surface,target->object,0,0);wl_surface_damage(surface,0,0,width,height);wl_surface_commit(surface);
     fprintf(stderr,"SDCOVER=committed|source=hwui-rendernode|width=%d|height=%d|wayland=shm|buffer_slot=%ld|per_frame_readback=0\n",cover_width,cover_height,(long)(target-cover_buffers));
     free(cover_pixels);cover_pixels=NULL;cover_pending=0;
    }
   }
  }
 }
 if(want_raise&&extended_surface&&(!hardware_mode()||gpu_startup_mapped||gpu_parent_mapped)){qt_extended_surface_raise(extended_surface);want_raise=0;}
 int frame=want_frame,has_frame=0,bootstrap=0;struct buffer*b=NULL;
 /* A new unmapped parent cannot receive Wayland frame callbacks. Android's
    display vsync exists independently of window mapping, so provide a bounded
    16ms bootstrap clock until the first real HWUI buffer can map this parent.
    Never count these callbacks as presented frames. */
 if(hardware_mode()&&!gpu_parent_mapped&&frame){
  int64_t now=monotonic_ns();frame=0;
  if(now>=bootstrap_next_ns){want_frame=0;bootstrap=1;bootstrap_next_ns=now+16666667;}
 }
 /* A buffer filled directly by the UI thread (SAILDROID_DIRECT_COPY) is marked
    ready by nativeDirectCommit; publish it before the staging path, which only
    runs when the UI thread handed us an int[] instead. */
 int ready_buffer=-1;
 for(int i=0;i<buffer_count;i++)if(buffers[i].ready&&!buffers[i].busy){ready_buffer=i;break;}
 if(ready_buffer>=0){b=&buffers[ready_buffer];has_frame=1;}
 else if(direct_shm){
  /* no ready buffer: nothing to publish */
  has_frame=0;
 }else{
  int changed=dirty;
  for(int i=0;i<buffer_count;i++)if(!buffers[i].busy){b=&buffers[i];break;}
  if(changed&&b){
   int64_t copy_started=perf_on?monotonic_ns():0;
   copy_scaled(b->pixels,latest,source_w,source_h,width,height);
   if(perf_on)perf_memcpy_ns=monotonic_ns()-copy_started;
   dirty=0;has_frame=1;
  }
  if(changed&&!b){perf_dropped++;perf_dropped_pending++;}
 }
 if(frame&&!frame_callback){frame_callback=wl_surface_frame(surface);wl_callback_add_listener(frame_callback,&frame_listener,NULL);want_frame=0;}
 force_commit_init();
 if(has_frame&&b){if(early_window&&!software_first_frame){software_first_frame=1;host_window_event("first-frame",1);}b->busy=1;b->ready=0;wl_surface_attach(surface,b->object,0,0);wl_surface_damage(surface,0,0,width,height);last_attached=b;}
 int commit_needed=has_frame||frame;
 if(commit_needed){
  if(!has_frame&&force_commit_mode==1&&last_attached){wl_surface_attach(surface,last_attached->object,0,0);wl_surface_damage(surface,0,0,1,1);}
  wl_surface_commit(surface);}
 if(perf_on){if(has_frame)perf_frame_commits++;else if(commit_needed)perf_empty_commits++;}
 if(perf_on&&has_frame&&b)perf_record_commit(b);
 pthread_mutex_unlock(&lock);
 if(bootstrap){
  if(++bootstrap_frames<=3)fprintf(stderr,"SDHWUI=unmapped_vsync_bootstrap|sequence=%u|presented=false\n",bootstrap_frames);
  int64_t timestamp=monotonic_ns();
  sd_native_display_frame(timestamp);
  if(callbacks_available()){(*thread_env)->CallStaticVoidMethod(thread_env,host_class,frame_done,(jlong)timestamp);check_callback();}
 }
}
static void*run_window(void*unused){(void)unused;if(!early_window)callbacks_available();if(hardware_mode())sd_window_gpu_display();else display=wl_display_connect(NULL);if(!display){snprintf(failure,sizeof(failure),"Wayland connection failed: %s",strerror(errno));goto failed;}struct wl_registry*r=wl_display_get_registry(display);wl_registry_add_listener(r,&registry_listener,NULL);if(wl_display_roundtrip(display)<0||!compositor||!shm||(!shell&&!(surface_extension&&native_shell))){snprintf(failure,sizeof(failure),"Required Wayland globals unavailable");goto failed;}surface=wl_compositor_create_surface(compositor);if(surface_extension){extended_surface=qt_surface_extension_get_extended_surface(surface_extension,surface);qt_extended_surface_add_listener(extended_surface,&extended_listener,NULL);qt_extended_surface_set_content_orientation_mask(extended_surface,1);}create_window_role();wl_surface_commit(surface);while(!configured)if(wl_display_dispatch(display)<0)goto failed;if(prepare_display()<0)goto failed;if(hardware_mode()&&create_gpu_background()<0){snprintf(failure,sizeof(failure),"GPU host background failed");goto failed;}if(hardware_mode()){if(sd_hwui_background_startup(getenv("SAILDROID_STARTUP_ICON"),source_w,source_h)!=0){snprintf(failure,sizeof(failure),"GPU initial presentation failed");goto failed;}gpu_startup_mapped=1;early_gpu=early_window!=0;fprintf(stderr,"SDHOST=startup_mapped|pid=%d|surface=%p|android_frame=false\n",getpid(),(void*)surface);}
int64_t alloc_started=monotonic_ns();if(!hardware_mode()){for(int i=0;i<buffer_count;i++)if(allocate_buffer(&buffers[i])){snprintf(failure,sizeof(failure),"SHM allocation failed");goto failed;}if(perf_on)perf_alloc_ns=monotonic_ns()-alloc_started;buffers[0].busy=1;wl_surface_attach(surface,buffers[0].object,0,0);wl_surface_damage(surface,0,0,width,height);wl_surface_commit(surface);}wl_display_flush(display);pthread_mutex_lock(&lock);ready=1;if(perf_on)perf_ready_ns=monotonic_ns();pthread_cond_broadcast(&ready_condition);pthread_mutex_unlock(&lock);fprintf(stderr,"SDWINDOW=ready|size=%dx%d|source=%dx%d\n",width,height,source_w,source_h);while(running){publish();while(wl_display_prepare_read(display)!=0)if(wl_display_dispatch_pending(display)<0)goto done;wl_display_flush(display);struct pollfd fds[]={{wl_display_get_fd(display),POLLIN,0},{wake_fd,POLLIN,0}};int wait_ms=1000;pthread_mutex_lock(&lock);if(hardware_mode()&&!gpu_parent_mapped&&want_frame){int64_t left=bootstrap_next_ns-monotonic_ns();wait_ms=left>0?(int)((left+999999)/1000000):0;}pthread_mutex_unlock(&lock);int n=poll(fds,2,wait_ms);if(n<0&&errno==EINTR){wl_display_cancel_read(display);continue;}if(n<0){wl_display_cancel_read(display);break;}if(fds[0].revents&POLLIN){if(wl_display_read_events(display)<0)break;}else wl_display_cancel_read(display);if(fds[1].revents&POLLIN){uint64_t value;while(read(wake_fd,&value,sizeof(value))>0){}}if(wl_display_dispatch_pending(display)<0)break;}done:
    perf_dump();
    sd_activation_stop();
    if (hardware_mode() && callbacks_available()) {
        /* RenderThread owns EGL queues on this connection. Keep their Wayland
         * objects alive while the main thread destroys Activities and exits. */
        request_close();
        (*vm)->DetachCurrentThread(vm);
        return NULL;
    }
if(hardware_mode())sd_hwui_background_destroy();if(extended_surface){qt_extended_surface_destroy(extended_surface);extended_surface=NULL;}if(native_shell_surface){wl_shell_surface_destroy(native_shell_surface);native_shell_surface=NULL;}if(toplevel)xdg_toplevel_destroy(toplevel);if(xdg_surface)xdg_surface_destroy(xdg_surface);if(surface)wl_surface_destroy(surface);if(display){wl_display_flush(display);wl_display_disconnect(display);display=NULL;}if(callbacks_available()){(*thread_env)->CallStaticVoidMethod(thread_env,host_class,closed_event);check_callback();(*vm)->DetachCurrentThread(vm);}else _exit(0);return NULL;failed:perf_dump();pthread_mutex_lock(&lock);ready=-1;running=0;pthread_cond_broadcast(&ready_condition);pthread_mutex_unlock(&lock);if(display)wl_display_disconnect(display);if(thread_env)(*vm)->DetachCurrentThread(vm);return NULL;}
JNIEXPORT void JNICALL Java_SdWindowHost_nativeSelectHardware(JNIEnv*e,jclass c,jboolean enabled){
 (void)c;atomic_store(&selected_hardware,enabled?1:0);setenv("SAILDROID_HWUI",enabled?"1":"0",1);wake_host();
 pthread_mutex_lock(&lock);struct timespec deadline;clock_gettime(CLOCK_REALTIME,&deadline);deadline.tv_sec+=8;
 while(early_gpu&&!enabled){if(pthread_cond_timedwait(&ready_condition,&lock,&deadline)==ETIMEDOUT){pthread_mutex_unlock(&lock);(*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/IllegalStateException"),"Software backend handoff timed out");return;}}
 pthread_mutex_unlock(&lock);
}
static int start_window(const char *ts,const char *as,int w,int h){
 pthread_mutex_lock(&lock);if(running){pthread_mutex_unlock(&lock);return 1;}
 perf_start_ns=monotonic_ns();perf_on=getenv("SAILDROID_PERF")!=NULL;direct_shm=getenv("SAILDROID_DIRECT_SHM")!=NULL;direct_copy=getenv("SAILDROID_NO_DIRECT_COPY")==NULL;buffer_count=getenv("SAILDROID_NO_TRIPLE_BUFFER")!=NULL?2:3;if(perf_on&&!perf_samples){perf_samples=calloc(PERF_MAX_SAMPLES,sizeof(struct perf_sample));if(!perf_samples)perf_on=0;}if(perf_on)perf_open_stream();source_w=w;source_h=h;width=height=0;configured=0;snprintf(title,sizeof(title),"%s",ts);snprintf(app_id,sizeof(app_id),"%s",as);wake_fd=eventfd(0,EFD_NONBLOCK|EFD_CLOEXEC);if(wake_fd<0){pthread_mutex_unlock(&lock);return JNI_FALSE;}running=1;pthread_create(&thread,NULL,run_window,NULL);struct timespec deadline;clock_gettime(CLOCK_REALTIME,&deadline);deadline.tv_sec+=8;while(!ready){if(pthread_cond_timedwait(&ready_condition,&lock,&deadline)==ETIMEDOUT){running=0;break;}}int success=ready==1;pthread_mutex_unlock(&lock);if(success){if(early_window)host_window_event("mapped",1);const char *control=getenv("SAILDROID_CONTROL_SOCKET");if(control&&sd_activation_start(control,request_activation,request_close,request_open,request_dump)<0)fprintf(stderr,"SDWINDOW=activation_unavailable|errno=%d\n",errno);}if(!success)fprintf(stderr,"SDWINDOW=start_failed|%s\n",failure);return success;
}
int sd_window_bootstrap(const char *name,const char *identity,int w,int h){early_window=1;return start_window(name,identity,w,h);}
JNIEXPORT jboolean JNICALL Java_SdWindowHost_nativeStart(JNIEnv*e,jclass c,jstring t,jstring a,jint w,jint h){
 (void)c;atomic_store_explicit(&callbacks_ready,1,memory_order_release);
 const char *ts=(*e)->GetStringUTFChars(e,t,NULL),*as=(*e)->GetStringUTFChars(e,a,NULL);
 int success=start_window(ts,as,w,h);(*e)->ReleaseStringUTFChars(e,t,ts);(*e)->ReleaseStringUTFChars(e,a,as);wake_host();
 if(success&&native_host_ready)native_host_ready();
 fprintf(stderr,"SDHOST=java_window_bound|pid=%d|surface=%p|reused=%d\n",getpid(),(void*)surface,early_window!=0);
 return success?JNI_TRUE:JNI_FALSE;
}
JNIEXPORT void JNICALL Java_SdWindowHost_nativeCoverFrame(JNIEnv*e,jclass c,jintArray data,jint w,jint h){
 (void)c;
 if(!hardware_mode()||w<1||h<1||w>1080||h>2160||(*e)->GetArrayLength(e,data)!=w*h){(*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/IllegalArgumentException"),"Invalid cover frame");return;}
 uint32_t *pixels=malloc((size_t)w*h*4);if(!pixels)return;
 (*e)->GetIntArrayRegion(e,data,0,w*h,(jint*)pixels);
 if((*e)->ExceptionCheck(e)){free(pixels);return;}
 pthread_mutex_lock(&lock);free(cover_pixels);cover_pixels=pixels;cover_width=w;cover_height=h;cover_pending=1;pthread_mutex_unlock(&lock);wake_host();
}
int sd_window_display_available(void){return atomic_load(&running);}
void sd_window_request_display_frame(void){pthread_mutex_lock(&lock);if(perf_on)perf_request_frame_calls++;want_frame=1;pthread_mutex_unlock(&lock);wake_host();}
JNIEXPORT void JNICALL Java_SdWindowHost_nativeRequestFrame(JNIEnv*e,jclass c){(void)e;(void)c;sd_window_request_display_frame();}
JNIEXPORT void JNICALL Java_SdWindowHost_nativePresent(JNIEnv*e,jclass c,jintArray data,jint w,jint h){
    (void)c;
    if(perf_on)perf_present_ns=monotonic_ns();
    if(w!=source_w||h!=source_h||(*e)->GetArrayLength(e,data)!=w*h){(*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/IllegalArgumentException"),"Frame dimensions differ from display");return;}
    if(!direct_shm){
        pthread_mutex_lock(&lock);
        if(perf_on){perf_mutex_wait_ns=monotonic_ns()-perf_present_ns;perf_presents++;}
        (*e)->GetIntArrayRegion(e,data,0,w*h,(jint*)latest);
        if(perf_on)perf_present_done_ns=monotonic_ns();
        dirty=1;pthread_mutex_unlock(&lock);wake_host();return;
    }
    /* Reserve the spare buffer, copy straight into it outside the lock (a full-screen
       copy under the frame mutex is what the staging path costs the UI thread), then
       publish the reservation. */
    struct buffer*target=NULL;
    pthread_mutex_lock(&lock);
    if(perf_on){perf_mutex_wait_ns=monotonic_ns()-perf_present_ns;perf_presents++;}
    for(int i=0;i<buffer_count;i++)if(!buffers[i].busy&&!buffers[i].ready&&!buffers[i].reserved){target=&buffers[i];break;}
    if(target){target->reserved=1;target->src_w=w;target->src_h=h;}
    pthread_mutex_unlock(&lock);
    if(!target){perf_dropped++;perf_dropped_pending++;return;}
    int64_t copy_started=perf_on?monotonic_ns():0;
    void*java_pixels=(*e)->GetPrimitiveArrayCritical(e,data,NULL);
    if(java_pixels)copy_scaled(target->pixels,(const uint32_t*)java_pixels,w,h,width,height);
    (*e)->ReleasePrimitiveArrayCritical(e,data,java_pixels,JNI_ABORT);
    if(perf_on)perf_memcpy_ns=monotonic_ns()-copy_started;
    pthread_mutex_lock(&lock);
    target->reserved=0;
    if(java_pixels)target->ready=1;else perf_dropped++;
    if(perf_on)perf_present_done_ns=monotonic_ns();
    pthread_mutex_unlock(&lock);
    wake_host();
}
/* Hand Java a direct ByteBuffer over the spare shm buffer so Bitmap pixels can be
   copied straight into the mapped surface with one copy instead of
   getPixels -> int[] -> GetIntArrayRegion -> memcpy. Returns NULL when the direct
   path is disabled, the compositor does not accept ABGR8888, or both buffers are
   still busy; the caller then uses the staging path. */
JNIEXPORT jobject JNICALL Java_SdWindowHost_nativeDirectAcquire(JNIEnv*e,jclass c){
    (void)c;
    if(!abgr_buffers())return NULL;
    struct buffer*target=NULL;int index=-1;
    int64_t acquire_started=perf_on?monotonic_ns():0;
    pthread_mutex_lock(&lock);
    if(perf_on)perf_mutex_wait_ns=monotonic_ns()-acquire_started;
    for(int i=0;i<buffer_count;i++)if(!buffers[i].busy&&!buffers[i].ready&&!buffers[i].reserved){target=&buffers[i];index=i;break;}
    if(target){target->reserved=1;target->src_w=source_w;target->src_h=source_h;direct_target=index;}
    pthread_mutex_unlock(&lock);
    if(!target)return NULL;
    return (*e)->NewDirectByteBuffer(e,target->pixels,(jlong)target->size);
}
JNIEXPORT jboolean JNICALL Java_SdWindowHost_nativeDirectCommit(JNIEnv*e,jclass c){
    (void)e;(void)c;
    /* The pixel copy already happened in Java, straight into the mapped buffer, so
       the JNI-array-copy stage is empty here and the Java copy is timed in
       composePixelsNs instead. */
    if(perf_on){
        /* The copy happened in Java into the mapped buffer; there is no native
           memcpy and no JNI array transfer in this frame, so those stages are zero
           rather than a stale value from an earlier staging frame. */
        perf_memcpy_ns=0;
        perf_present_ns=monotonic_ns();perf_presents++;perf_present_done_ns=perf_present_ns;
    }
    int index=direct_target;direct_target=-1;
    if(index<0)return JNI_FALSE;
    pthread_mutex_lock(&lock);
    buffers[index].reserved=0;buffers[index].ready=1;
    pthread_mutex_unlock(&lock);
    wake_host();
    return JNI_TRUE;
}
JNIEXPORT void JNICALL Java_SdWindowHost_nativeStop(JNIEnv*e,jclass c){(void)e;(void)c;if(hardware_mode())return;running=0;wake_host();}
static jlong display_init(JNIEnv*e,jclass c,jobject weak,jobject queue,jint source){
    (void)c;if(perf_on)perf_display_init_calls++;if(source!=0&&source!=1){(*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/IllegalArgumentException"),"Unknown display event source");return 0;}
    return (*e)->CallStaticLongMethod(e,frame_class,(*e)->GetStaticMethodID(e,frame_class,"initialize","(Ljava/lang/ref/WeakReference;Landroid/os/MessageQueue;)J"),weak,queue);
}
static void display_dispose(JNIEnv*e,jclass c,jlong id){(void)c;(*e)->CallStaticVoidMethod(e,frame_class,(*e)->GetStaticMethodID(e,frame_class,"dispose","(J)V"),id);}
static void display_schedule(JNIEnv*e,jclass c,jlong id){(void)c;if(perf_on)perf_display_schedule_calls++;(*e)->CallStaticVoidMethod(e,frame_class,(*e)->GetStaticMethodID(e,frame_class,"schedule","(J)V"),id);}
static jlong surface_lock(JNIEnv*e,jclass c,jlong id,jobject canvas,jobject rect){(void)c;if(perf_on&&!perf_draw_start)perf_draw_start=monotonic_ns();jlong result=(*e)->CallStaticLongMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"lock","(JLandroid/graphics/Canvas;Landroid/graphics/Rect;)J"),id,canvas,rect);if(perf_on)perf_lock_ret_ns=monotonic_ns();return result;}
static void surface_unlock(JNIEnv*e,jclass c,jlong id,jobject canvas){(void)c;if(perf_on){int64_t begun=monotonic_ns();if(perf_draw_start){perf_draw_ns+=begun-perf_draw_start;perf_draws++;}perf_unlock_ns=begun;}(*e)->CallStaticVoidMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"unlock","(JLandroid/graphics/Canvas;)V"),id,canvas);}
static void surface_release(JNIEnv*e,jclass c,jlong id){(void)c;(*e)->CallStaticVoidMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"release","(J)V"),id);}
static jboolean surface_valid(JNIEnv*e,jclass c,jlong id){(void)c;return(*e)->CallStaticBooleanMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"valid","(J)Z"),id);}
static jboolean surface_behind(JNIEnv*e,jclass c,jlong id){(void)c;return(*e)->CallStaticBooleanMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"consumerBehind","(J)Z"),id);}
static jint surface_width(JNIEnv*e,jclass c,jlong id){(void)c;return(*e)->CallStaticIntMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"width","(J)I"),id);}
static jint surface_height(JNIEnv*e,jclass c,jlong id){(void)c;return(*e)->CallStaticIntMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"height","(J)I"),id);}
static void surface_allocate(JNIEnv*e,jclass c,jlong id){(void)c;(*e)->CallStaticVoidMethod(e,surface_class,(*e)->GetStaticMethodID(e,surface_class,"allocate","(J)V"),id);}
static jlong unsupported_texture(JNIEnv*e,jclass c,jobject texture){(void)c;(void)texture;(*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/UnsupportedOperationException"),"SurfaceTexture requires a native graphics producer");return 0;}
static jlong unsupported_control(JNIEnv*e,jclass c,jlong value){(void)c;(void)value;(*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/UnsupportedOperationException"),"SurfaceControl is not a local window");return 0;}
static jlong unsupported_read(JNIEnv*e,jclass c,jlong value,jobject p){(void)c;(void)value;(void)p;(*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/UnsupportedOperationException"),"Cross-process Surface parcels unavailable");return 0;}
static void unsupported_write(JNIEnv*e,jclass c,jlong value,jobject p){(void)unsupported_read(e,c,value,p);}
static jobject unsupported_egl_window(JNIEnv *e,jclass type,jobject display,jobject config,jobject window,jintArray attributes,jint offset){
    (void)type;(void)display;(void)config;(void)window;(void)attributes;(void)offset;
    (*e)->ThrowNew(e,(*e)->FindClass(e,"java/lang/UnsupportedOperationException"),"This raster Surface has no EGL native-window producer");return NULL;
}
JNIEXPORT void JNICALL Java_SdWindowHost_nativeInstall(JNIEnv*e,jclass c){host_class=(*e)->NewGlobalRef(e,c);diagnostics_class=(*e)->NewGlobalRef(e,(*e)->FindClass(e,"SdRuntimeDiagnostics"));dump_method=(*e)->GetStaticMethodID(e,diagnostics_class,"dumpThreads","()V");frame_class=(*e)->NewGlobalRef(e,(*e)->FindClass(e,"SdDisplayFrames"));surface_class=(*e)->NewGlobalRef(e,(*e)->FindClass(e,"SdSurfaceStore"));perf_compose_field=(*e)->GetStaticFieldID(e,surface_class,"composes","J");perf_erase_field=(*e)->GetStaticFieldID(e,surface_class,"composeEraseNs","J");perf_draw_field=(*e)->GetStaticFieldID(e,surface_class,"composeDrawNs","J");perf_pixels_field=(*e)->GetStaticFieldID(e,surface_class,"composePixelsNs","J");perf_present_java_field=(*e)->GetStaticFieldID(e,surface_class,"composePresentNs","J");perf_creq_field=(*e)->GetStaticFieldID(e,surface_class,"composeRequests","J");perf_cfall_field=(*e)->GetStaticFieldID(e,surface_class,"composeFallbacks","J");perf_fast_field=(*e)->GetStaticFieldID(e,surface_class,"fastPathFrames","J");perf_layers_field=(*e)->GetStaticFieldID(e,surface_class,"lastLayerCount","J");perf_layer_alpha_field=(*e)->GetStaticFieldID(e,surface_class,"lastLayerAlphaMilli","J");perf_layer_full_field=(*e)->GetStaticFieldID(e,surface_class,"lastLayerFull","J");perf_layer_ident_field=(*e)->GetStaticFieldID(e,surface_class,"lastLayerIdentity","J");perf_locks_field=(*e)->GetStaticFieldID(e,surface_class,"locks","J");perf_unlocks_field=(*e)->GetStaticFieldID(e,surface_class,"unlocks","J");perf_transactions_field=(*e)->GetStaticFieldID(e,surface_class,"draws","J");perf_direct_copies_field=(*e)->GetStaticFieldID(e,surface_class,"directCopies","J");perf_direct_misses_field=(*e)->GetStaticFieldID(e,surface_class,"directMisses","J");perf_direct_drops_field=(*e)->GetStaticFieldID(e,surface_class,"directDrops","J");perf_recoveries_field=(*e)->GetStaticFieldID(e,surface_class,"recoveries","J");sd_perf_fields_guard(e);frame_done=(*e)->GetStaticMethodID(e,c,"onNativeFrame","(J)V");input_event=(*e)->GetStaticMethodID(e,c,"onNativeInput","(IIFFJ)V");focus_event=(*e)->GetStaticMethodID(e,c,"onNativeFocus","(Z)V");closed_event=(*e)->GetStaticMethodID(e,c,"onNativeClosed","()V");visibility_event=(*e)->GetStaticMethodID(e,c,"onNativeVisibility","(I)V");open_event=(*e)->GetStaticMethodID(e,c,"onNativeOpenUri","(Ljava/lang/String;)Z");JNINativeMethod dm[]={{"nativeInit","(Ljava/lang/ref/WeakReference;Landroid/os/MessageQueue;I)J",display_init},{"nativeDispose","(J)V",display_dispose},{"nativeScheduleVsync","(J)V",display_schedule}};if((*e)->RegisterNatives(e,(*e)->FindClass(e,"android/view/DisplayEventReceiver"),dm,3)<0)return;JNINativeMethod sm[]={{"nativeLockCanvas","(JLandroid/graphics/Canvas;Landroid/graphics/Rect;)J",surface_lock},{"nativeUnlockCanvasAndPost","(JLandroid/graphics/Canvas;)V",surface_unlock},{"nativeRelease","(J)V",surface_release},{"nativeIsValid","(J)Z",surface_valid},{"nativeIsConsumerRunningBehind","(J)Z",surface_behind},{"nativeAllocateBuffers","(J)V",surface_allocate},{"nativeGetWidth","(J)I",surface_width},{"nativeGetHeight","(J)I",surface_height},{"nativeCreateFromSurfaceTexture","(Landroid/graphics/SurfaceTexture;)J",unsupported_texture},{"nativeCreateFromSurfaceControl","(J)J",unsupported_control},{"nativeReadFromParcel","(JLandroid/os/Parcel;)J",unsupported_read},{"nativeWriteToParcel","(JLandroid/os/Parcel;)V",unsupported_write}};if((*e)->RegisterNatives(e,(*e)->FindClass(e,"android/view/Surface"),sm,sizeof(sm)/sizeof(sm[0]))<0)return;JNINativeMethod ew[]={{"_eglCreateWindowSurface","(Landroid/opengl/EGLDisplay;Landroid/opengl/EGLConfig;Ljava/lang/Object;[II)Landroid/opengl/EGLSurface;",unsupported_egl_window},{"_eglCreateWindowSurfaceTexture","(Landroid/opengl/EGLDisplay;Landroid/opengl/EGLConfig;Ljava/lang/Object;[II)Landroid/opengl/EGLSurface;",unsupported_egl_window}};if((*e)->RegisterNatives(e,(*e)->FindClass(e,"android/opengl/EGL14"),ew,2)<0)return;sd_control_install(e);}
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM*v,void*r){(void)r;vm=v;return JNI_VERSION_1_6;}
/* The native per-application host loads this library before ART so it can
 * create the persistent Wayland surface. ART may later find the library
 * already resident, therefore JNI_OnLoad is not a sufficient hand-off. */
void sd_window_bind_vm(JavaVM *value){vm=value;}
JNIEXPORT jint JNICALL Java_SdWindowHost_nativeClientHeight(JNIEnv *env,jclass cls){(void)env;(void)cls;return height>0?height:source_h;}
