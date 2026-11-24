#include <jni.h>
#include <gst/gst.h>
#include <gst/app/gstappsink.h>
#include <gst/app/gstappsrc.h>
#include <gst/video/video.h>
#include <dlfcn.h>
#include <unistd.h>
#include <sys/stat.h>
#include <atomic>
#include <thread>
#include <mutex>
#include <map>
#include <memory>
#include <string>
#include <vector>
#include <cstring>
#include <cstdio>
#include <algorithm>

// NDK's stable C ABI; the actual Surface/BufferQueue remains Android-owned.
struct WindowBuffer { int32_t width,height,stride,format; void*bits; uint32_t reserved[6]; };
static void*(*from_surface)(JNIEnv*,jobject);
static void(*window_release)(void*);
static int(*window_geometry)(void*,int32_t,int32_t,int32_t);
static int(*window_lock)(void*,WindowBuffer*,void*);
static int(*window_post)(void*);
static JavaVM*vm;
static jclass mp_class;
static jfieldID context_field;
static jmethodID post_event;
static std::mutex registry_lock;
static std::atomic<long> next_id{1};
struct Player;
static std::map<long,std::shared_ptr<Player>> registry;
static void fail(JNIEnv*e,const char*type,const char*message){e->ThrowNew(e->FindClass(type),message);}
static void unsupported(JNIEnv*e,const char*name){fprintf(stderr,"SDMEDIA=unsupported|method=%s\n",name);fail(e,"java/lang/UnsupportedOperationException",name);}
struct Env {
 JNIEnv*e=nullptr;bool attached=false;
 Env(){if(vm->GetEnv((void**)&e,JNI_VERSION_1_6)==JNI_EDETACHED){attached=vm->AttachCurrentThreadAsDaemon((void**)&e,nullptr)==JNI_OK;}}
 ~Env(){if(attached)vm->DetachCurrentThread();}
};
struct Player {
 long id; jobject weak=nullptr,java_source=nullptr;jmethodID source_read=nullptr,source_size=nullptr,source_close=nullptr; GstElement*pipe=nullptr,*sink=nullptr,*audio=nullptr;GstBus*bus=nullptr;
 std::thread worker;std::atomic<bool>quit{false},prepared{false},playing{false},loop{false};
 std::atomic<int64_t>notify_us{-1};
 std::atomic<int>width{0},height{0};std::atomic<uint64_t>frames{0};
 std::mutex surface_mutex,source_mutex;void*window=nullptr;int fd=-1;int64_t offset=0,length=0,cursor=0;
 int stream=3,session=0;float left=1,right=1;bool async_prepare=false;bool configured=false;std::atomic<bool>pending_seek{false},completed{false},prepare_queued{false},error_sent{false};
 Player(long n):id(n){}
 void event(int what,int a=0,int b=0){
  if(quit||!weak)return;
  Env env;if(!env.e)return;
  env.e->CallStaticVoidMethod(mp_class,post_event,weak,what,a,b,nullptr);
  if(env.e->ExceptionCheck()){env.e->ExceptionDescribe();env.e->ExceptionClear();}
 }
 void error(int extra=-1004){playing=false;if(!error_sent.exchange(true))event(100,1,extra);}
 void shutdown(){
  quit=true;
  if(pipe)gst_element_set_state(pipe,GST_STATE_NULL);
  if(worker.joinable())worker.join();
  {std::lock_guard<std::mutex>g(surface_mutex);if(window){window_release(window);window=nullptr;}}
  if(bus){gst_object_unref(bus);bus=nullptr;}
  if(pipe){gst_object_unref(pipe);pipe=nullptr;sink=nullptr;}
  if(fd>=0){close(fd);fd=-1;}
  Env env;if(java_source&&env.e){env.e->CallVoidMethod(java_source,source_close);if(env.e->ExceptionCheck()){env.e->ExceptionDescribe();env.e->ExceptionClear();}env.e->DeleteGlobalRef(java_source);java_source=nullptr;}if(weak&&env.e){env.e->DeleteGlobalRef(weak);weak=nullptr;}
 }
 ~Player(){shutdown();}
 void bus_loop(){
  while(!quit){if(prepare_queued.exchange(false)){GstStateChangeReturn rc=gst_element_set_state(pipe,GST_STATE_PAUSED);if(rc==GST_STATE_CHANGE_FAILURE)error();}if(playing&&notify_us.load()>=0){gint64 pos=0;if(gst_element_query_position(pipe,GST_FORMAT_TIME,&pos)&&pos/GST_USECOND>=notify_us.load()){notify_us=-1;event(98);}}GstMessage*m=gst_bus_timed_pop(bus,100*GST_MSECOND);if(!m)continue;
   switch(GST_MESSAGE_TYPE(m)){
    case GST_MESSAGE_ERROR:{GError*err=nullptr;gchar*debug=nullptr;gst_message_parse_error(m,&err,&debug);fprintf(stderr,"SDMEDIA=error|id=%ld|domain=%s|code=%d|message=%s|debug=%s\n",id,err?g_quark_to_string(err->domain):"",err?err->code:0,err?err->message:"",debug?debug:"");error();g_clear_error(&err);g_free(debug);break;}
    case GST_MESSAGE_ASYNC_DONE:
     if(!prepared.exchange(true)){fprintf(stderr,"SDMEDIA=prepared|id=%ld|video=%dx%d\n",id,width.load(),height.load());if(async_prepare)event(1);}
     else if(pending_seek.exchange(false)){event(4);fprintf(stderr,"SDMEDIA=seek_complete|id=%ld\n",id);}
     break;
    case GST_MESSAGE_EOS:
     if(audio){GstStructure*stats=nullptr;g_object_get(audio,"stats",&stats,nullptr);if(stats){guint64 rendered=0;gst_structure_get_uint64(stats,"rendered",&rendered);fprintf(stderr,"SDMEDIA=audio_sink|id=%ld|backend=pulseaudio|rendered_buffers=%llu\n",id,(unsigned long long)rendered);gst_structure_free(stats);}}
     fprintf(stderr,"SDMEDIA=eos|id=%ld|frames=%llu\n",id,(unsigned long long)frames.load());
     if(loop){gst_element_seek_simple(pipe,GST_FORMAT_TIME,(GstSeekFlags)(GST_SEEK_FLAG_FLUSH|GST_SEEK_FLAG_KEY_UNIT),0);gst_element_set_state(pipe,GST_STATE_PLAYING);}
     else {playing=false;completed=true;event(2);}break;
    case GST_MESSAGE_DURATION_CHANGED:break;
    default:break;
   }
   gst_message_unref(m);
  }
 }
};
static std::shared_ptr<Player>get(JNIEnv*e,jobject self){long id=e->GetLongField(self,context_field);std::lock_guard<std::mutex>g(registry_lock);auto it=registry.find(id);if(it!=registry.end())return it->second;fail(e,"java/lang/IllegalStateException","MediaPlayer is released");return {};}
static void read_data(GstAppSrc*src,guint requested,gpointer data){
 Player*p=(Player*)data;std::lock_guard<std::mutex>g(p->source_mutex);if(p->quit)return;
 int64_t remaining=p->length<0?262144:p->length-p->cursor;
 size_t n=(size_t)std::min<int64_t>(requested==G_MAXUINT||requested==0?65536:std::min<guint>(requested,262144),remaining);
 if(!n){gst_app_src_end_of_stream(src);return;}
 GstBuffer*b=gst_buffer_new_allocate(nullptr,n,nullptr);GstMapInfo map;
 if(!gst_buffer_map(b,&map,GST_MAP_WRITE)){gst_buffer_unref(b);return;}
 ssize_t got=-1;
 if(p->java_source){Env env;if(env.e){jbyteArray bytes=env.e->NewByteArray(n);if(bytes){got=env.e->CallIntMethod(p->java_source,p->source_read,(jlong)p->cursor,bytes,0,(jint)n);if(!env.e->ExceptionCheck()&&got>0&&got<=(ssize_t)n)env.e->GetByteArrayRegion(bytes,0,got,(jbyte*)map.data);env.e->DeleteLocalRef(bytes);}if(env.e->ExceptionCheck()){env.e->ExceptionDescribe();env.e->ExceptionClear();got=-2;}}}
 else {got=pread(p->fd,map.data,n,p->offset+p->cursor);if(got==0)got=-1;else if(got<0)got=-2;}
 gst_buffer_unmap(b,&map);
 if(got<=0||got>(ssize_t)n){gst_buffer_unref(b);if(got==-1)gst_app_src_end_of_stream(src);else GST_ELEMENT_ERROR(src,RESOURCE,READ,("MediaPlayer source read failed"),("result=%lld errno=%d",(long long)got,errno));return;}
 gst_buffer_resize(b,0,got);GST_BUFFER_OFFSET(b)=p->cursor;p->cursor+=got;gst_app_src_push_buffer(src,b);
}

static gboolean seek_data(GstAppSrc*,guint64 pos,gpointer data){Player*p=(Player*)data;std::lock_guard<std::mutex>g(p->source_mutex);if(p->length>=0&&pos>(guint64)p->length)return FALSE;p->cursor=pos;return TRUE;}
static void source_setup(GstElement*,GstElement*src,gpointer data){Player*p=(Player*)data;if(p->fd<0&&!p->java_source)return;if(!GST_IS_APP_SRC(src)){fprintf(stderr,"SDMEDIA=error|source=expected-appsrc\n");return;}if(p->java_source){Env env;if(!env.e)return;p->length=env.e->CallLongMethod(p->java_source,p->source_size);if(env.e->ExceptionCheck()){env.e->ExceptionDescribe();env.e->ExceptionClear();p->error();GST_ELEMENT_ERROR(src,RESOURCE,OPEN_READ,("MediaPlayer data source could not open"),("Java getSize failed"));return;}}GstAppSrcCallbacks cb{};cb.need_data=read_data;cb.seek_data=seek_data;gst_app_src_set_callbacks(GST_APP_SRC(src),&cb,p,nullptr);gst_app_src_set_size(GST_APP_SRC(src),p->length);gst_app_src_set_stream_type(GST_APP_SRC(src),GST_APP_STREAM_TYPE_SEEKABLE);g_object_set(src,"format",GST_FORMAT_BYTES,nullptr);}
static GstFlowReturn render(GstAppSink*sink,void*data,bool preroll){
 Player*p=(Player*)data;GstSample*sample=preroll?gst_app_sink_pull_preroll(sink):gst_app_sink_pull_sample(sink);if(!sample)return GST_FLOW_EOS;
 GstVideoInfo info;GstCaps*caps=gst_sample_get_caps(sample);GstBuffer*buffer=gst_sample_get_buffer(sample);GstVideoFrame frame;
 if(!gst_video_info_from_caps(&info,caps)||!gst_video_frame_map(&frame,&info,buffer,GST_MAP_READ)){gst_sample_unref(sample);return GST_FLOW_ERROR;}
 int w=GST_VIDEO_INFO_WIDTH(&info),h=GST_VIDEO_INFO_HEIGHT(&info);bool changed=p->width.exchange(w)!=w;changed=(p->height.exchange(h)!=h)||changed;if(changed)p->event(5,w,h);
 bool posted=false;uint64_t hash=1469598103934665603ULL;
 {std::lock_guard<std::mutex>g(p->surface_mutex);if(p->window&&!p->quit){
  if(window_geometry(p->window,w,h,1)==0){WindowBuffer out{};int rc=window_lock(p->window,&out,nullptr);
   if(rc==0){int rows=std::min(h,out.height),cols=std::min(w,out.width);for(int y=0;y<rows;y++){const unsigned char*src=(const unsigned char*)GST_VIDEO_FRAME_PLANE_DATA(&frame,0)+y*GST_VIDEO_FRAME_PLANE_STRIDE(&frame,0);memcpy((char*)out.bits+y*out.stride*4,src,cols*4);for(int x=0;x<cols*4;x+=127)hash=(hash^src[x])*1099511628211ULL;}posted=window_post(p->window)==0;}
   else fprintf(stderr,"SDMEDIA=surface_lock_error|id=%ld|code=%d\n",p->id,rc);
  }
 }}
 if(posted){uint64_t n=++p->frames;if(n==1){p->event(200,3);fprintf(stderr,"SDMEDIA=first_frame|id=%ld|size=%dx%d|queue=android-native-window\n",p->id,w,h);}if(n==1||n%30==0)fprintf(stderr,"SDMEDIA=frame|id=%ld|n=%llu|pts_ns=%llu|hash=%016llx|preroll=%d\n",p->id,(unsigned long long)n,(unsigned long long)GST_BUFFER_PTS(buffer),(unsigned long long)hash,preroll);}
 gst_video_frame_unmap(&frame);gst_sample_unref(sample);return GST_FLOW_OK;
}
static GstFlowReturn sample_cb(GstAppSink*s,gpointer p){return render(s,p,false);}static GstFlowReturn preroll_cb(GstAppSink*s,gpointer p){return render(s,p,true);}
static bool configure(JNIEnv*e,std::shared_ptr<Player>p,const char*uri,bool retrieve=false){
 if(p->configured){fail(e,"java/lang/IllegalStateException","Data source already set");return false;}
 p->pipe=gst_element_factory_make("playbin",nullptr);p->sink=gst_element_factory_make("appsink",nullptr);p->audio=gst_element_factory_make(retrieve?"fakesink":"pulsesink",nullptr);GstElement*audio=p->audio;
 if(!p->pipe||!p->sink||!audio){fail(e,"java/io/IOException","GStreamer playbin/appsink/pulsesink unavailable");return false;}
 GstCaps*caps=gst_caps_new_simple("video/x-raw","format",G_TYPE_STRING,"RGBA",nullptr);gst_app_sink_set_caps(GST_APP_SINK(p->sink),caps);gst_caps_unref(caps);
 g_object_set(p->sink,"sync",!retrieve,"max-buffers",2,"drop",TRUE,"enable-last-sample",FALSE,nullptr);GstAppSinkCallbacks cb{};if(!retrieve){cb.new_sample=sample_cb;cb.new_preroll=preroll_cb;}gst_app_sink_set_callbacks(GST_APP_SINK(p->sink),&cb,p.get(),nullptr);
 g_object_set(p->pipe,"video-sink",p->sink,"audio-sink",audio,"uri",uri,"volume",(double)((p->left+p->right)/2),nullptr);
 g_signal_connect(p->pipe,"source-setup",G_CALLBACK(source_setup),p.get());p->bus=gst_element_get_bus(p->pipe);p->configured=true;p->worker=std::thread([raw=p.get()]{raw->bus_loop();});
 fprintf(stderr,"SDMEDIA=data_source|id=%ld|kind=%s|length=%lld|backend=gstreamer|purpose=%s\n",p->id,p->fd>=0?"bounded-fd":p->java_source?"android-media-data-source":"uri",(long long)p->length,retrieve?"metadata":"playback");return true;
}
static void setup(JNIEnv*e,jobject self,jobject weak){long id=next_id++;auto p=std::make_shared<Player>(id);p->weak=e->NewGlobalRef(weak);{std::lock_guard<std::mutex>g(registry_lock);registry[id]=p;}e->SetLongField(self,context_field,id);fprintf(stderr,"SDMEDIA=setup|id=%ld|backend=gstreamer|android_media_server=unused\n",id);}
static void release(JNIEnv*e,jobject self){long id=e->GetLongField(self,context_field);std::shared_ptr<Player>p;{std::lock_guard<std::mutex>g(registry_lock);auto it=registry.find(id);if(it!=registry.end()){p=it->second;registry.erase(it);}}e->SetLongField(self,context_field,0);if(p){p->shutdown();fprintf(stderr,"SDMEDIA=released|id=%ld|frames=%llu\n",id,(unsigned long long)p->frames.load());}}
static void reset(JNIEnv*e,jobject self){auto p=get(e,self);if(!p)return;jobject weak=e->NewLocalRef(p->weak);release(e,self);setup(e,self,weak);e->DeleteLocalRef(weak);}
static void set_surface(JNIEnv*e,jobject self,jobject surface){auto p=get(e,self);if(!p)return;void*w=surface?from_surface(e,surface):nullptr;if(surface&&!w){fail(e,"java/lang/IllegalArgumentException","Invalid Surface");return;}std::lock_guard<std::mutex>g(p->surface_mutex);if(p->window)window_release(p->window);p->window=w;fprintf(stderr,"SDMEDIA=surface|id=%ld|attached=%d\n",p->id,w!=nullptr);}
static void source_fd(JNIEnv*e,jobject self,jobject fd,jlong offset,jlong length){auto p=get(e,self);if(!p)return;if(p->configured){fail(e,"java/lang/IllegalStateException","Data source already set");return;}int n=e->GetIntField(fd,e->GetFieldID(e->GetObjectClass(fd),"descriptor","I"));struct stat st{};if(offset<0||length<0||fstat(n,&st)||!S_ISREG(st.st_mode)||offset>st.st_size){fail(e,"java/io/IOException","MediaPlayer needs a valid seekable fd range");return;}p->fd=dup(n);p->offset=offset;p->length=std::min<int64_t>(length,st.st_size-offset);if(p->fd<0){fail(e,"java/io/IOException","dup failed");return;}configure(e,p,"appsrc://");}
static void source_callback(JNIEnv*e,jobject self,jobject source){auto p=get(e,self);if(!p)return;if(p->configured){fail(e,"java/lang/IllegalStateException","Data source already set");return;}if(!source){fail(e,"java/lang/IllegalArgumentException","Null MediaDataSource");return;}jclass cls=e->GetObjectClass(source);p->source_read=e->GetMethodID(cls,"readAt","(J[BII)I");p->source_size=e->GetMethodID(cls,"getSize","()J");p->source_close=e->GetMethodID(cls,"close","()V");if(e->ExceptionCheck())return;p->java_source=e->NewGlobalRef(source);p->length=-1;configure(e,p,"appsrc://");}
static void source_uri(JNIEnv*e,jobject self,jobject,jstring uri,jobjectArray keys,jobjectArray values){
 auto p=get(e,self);if(!p)return;if(!uri){fail(e,"java/lang/IllegalArgumentException","Null media URI");return;}
 const char*s=e->GetStringUTFChars(uri,nullptr);bool http=!strncmp(s,"http://",7)||!strncmp(s,"https://",8);gchar*u=nullptr;if(!http){if(strstr(s,"://"))u=g_strdup(s);else u=g_filename_to_uri(s,nullptr,nullptr);}e->ReleaseStringUTFChars(uri,s);
 if(http){jclass cls=e->FindClass("SdMediaDataSource");if(!cls)return;jmethodID ctor=e->GetMethodID(cls,"<init>","(Ljava/lang/String;[Ljava/lang/String;[Ljava/lang/String;)V");jobject source=e->NewObject(cls,ctor,uri,keys,values);if(source){source_callback(e,self,source);e->DeleteLocalRef(source);}return;}
 if(!u){fail(e,"java/io/IOException","Invalid media URI");return;}configure(e,p,u);g_free(u);
}

static void prepare(JNIEnv*e,jobject self,bool async){auto p=get(e,self);if(!p)return;if(!p->configured){fail(e,"java/lang/IllegalStateException","Data source not set");return;}p->async_prepare=async;if(async){p->prepare_queued=true;return;}GstStateChangeReturn rc=gst_element_set_state(p->pipe,GST_STATE_PAUSED);if(rc==GST_STATE_CHANGE_FAILURE){fail(e,"java/io/IOException","Media prepare failed");return;}if(!async){rc=gst_element_get_state(p->pipe,nullptr,nullptr,20*GST_SECOND);if(rc!=GST_STATE_CHANGE_SUCCESS){fail(e,"java/io/IOException","Media prepare failed or timed out");return;}p->prepared=true;}}
static void prepare_sync(JNIEnv*e,jobject s){prepare(e,s,false);}static void prepare_async(JNIEnv*e,jobject s){prepare(e,s,true);}
static void change_state(JNIEnv*e,jobject self,GstState state,int event){auto p=get(e,self);if(!p)return;if(!p->pipe||!p->prepared){fail(e,"java/lang/IllegalStateException","MediaPlayer is not prepared");return;}if(state==GST_STATE_PLAYING&&p->completed.exchange(false))gst_element_seek_simple(p->pipe,GST_FORMAT_TIME,(GstSeekFlags)(GST_SEEK_FLAG_FLUSH|GST_SEEK_FLAG_KEY_UNIT),0);if(gst_element_set_state(p->pipe,state)==GST_STATE_CHANGE_FAILURE){fail(e,"java/lang/IllegalStateException","GStreamer state transition failed");return;}p->playing=state==GST_STATE_PLAYING;p->event(event);fprintf(stderr,"SDMEDIA=state|id=%ld|state=%s\n",p->id,gst_element_state_get_name(state));}
static void start(JNIEnv*e,jobject s){change_state(e,s,GST_STATE_PLAYING,6);}static void pause_player(JNIEnv*e,jobject s){change_state(e,s,GST_STATE_PAUSED,7);}static void stop(JNIEnv*e,jobject s){change_state(e,s,GST_STATE_READY,8);auto p=get(e,s);if(p)p->prepared=false;}
static jint width(JNIEnv*e,jobject s){auto p=get(e,s);return p?p->width.load():0;}static jint height(JNIEnv*e,jobject s){auto p=get(e,s);return p?p->height.load():0;}
static jint query(JNIEnv*e,jobject s,bool duration){auto p=get(e,s);if(!p||!p->pipe)return -1;gint64 n=0;bool ok=duration?gst_element_query_duration(p->pipe,GST_FORMAT_TIME,&n):gst_element_query_position(p->pipe,GST_FORMAT_TIME,&n);return ok?(jint)(n/GST_MSECOND):-1;}
static jint position(JNIEnv*e,jobject s){return query(e,s,false);}static jint duration(JNIEnv*e,jobject s){return query(e,s,true);}static jboolean isplaying(JNIEnv*e,jobject s){auto p=get(e,s);return p&&p->playing;}
static void seek(JNIEnv*e,jobject s,jlong ms,jint mode){auto p=get(e,s);if(!p)return;if(ms<0)ms=0;GstSeekFlags flags=(GstSeekFlags)(GST_SEEK_FLAG_FLUSH|(mode==3?GST_SEEK_FLAG_ACCURATE:GST_SEEK_FLAG_KEY_UNIT));p->pending_seek=true;if(!p->pipe||!gst_element_seek_simple(p->pipe,GST_FORMAT_TIME,flags,ms*GST_MSECOND)){p->pending_seek=false;fail(e,"java/lang/IllegalStateException","Media is not seekable");}else fprintf(stderr,"SDMEDIA=seek|id=%ld|ms=%lld\n",p->id,(long long)ms);}
static void looping(JNIEnv*e,jobject s,jboolean v){auto p=get(e,s);if(p)p->loop=v;}static jboolean islooping(JNIEnv*e,jobject s){auto p=get(e,s);return p&&p->loop;}
static void volume(JNIEnv*e,jobject s,jfloat l,jfloat r){auto p=get(e,s);if(p){p->left=l;p->right=r;if(p->pipe)g_object_set(p->pipe,"volume",(double)((l+r)/2),nullptr);}}
static void stream(JNIEnv*e,jobject s,jint n){auto p=get(e,s);if(p)p->stream=n;}static jint getstream(JNIEnv*e,jobject s){auto p=get(e,s);return p?p->stream:3;}
static void session(JNIEnv*e,jobject s,jint n){auto p=get(e,s);if(p)p->session=n;}static jint getsession(JNIEnv*e,jobject s){auto p=get(e,s);return p?p->session:0;}
// Android's Java MediaPlayer automatically queries in-band tracks after prepare.
// Populate the real discovered audio/video streams using its existing Parcel ABI.
static jint invoke(JNIEnv*e,jobject s,jobject req,jobject reply){auto p=get(e,s);if(!p)return -38;jclass pc=e->GetObjectClass(req);auto pos=e->GetMethodID(pc,"setDataPosition","(I)V");auto read=e->GetMethodID(pc,"readInt","()I");auto write=e->GetMethodID(pc,"writeInt","(I)V");auto text=e->GetMethodID(pc,"writeString","(Ljava/lang/String;)V");auto enforce=e->GetMethodID(pc,"enforceInterface","(Ljava/lang/String;)V");e->CallVoidMethod(req,pos,0);jstring token=e->NewStringUTF("android.media.IMediaPlayer");e->CallVoidMethod(req,enforce,token);e->DeleteLocalRef(token);if(e->ExceptionCheck())return -22;int op=e->CallIntMethod(req,read);
 if(op==1){gint nv=0,na=0;if(p->pipe)g_object_get(p->pipe,"n-video",&nv,"n-audio",&na,nullptr);e->CallVoidMethod(reply,write,nv+na);for(int kind=1;kind<=2;kind++)for(int i=0;i<(kind==1?nv:na);i++){e->CallVoidMethod(reply,write,1);e->CallVoidMethod(reply,write,kind);jstring mime=e->NewStringUTF(kind==1?"video/raw":"audio/raw"),lang=e->NewStringUTF("und");e->CallVoidMethod(reply,text,mime);e->CallVoidMethod(reply,text,lang);e->DeleteLocalRef(mime);e->DeleteLocalRef(lang);}return 0;}
 if(op==6){int mode=e->CallIntMethod(req,read);if(mode==1)return 0;return -38;}
 if(op==7){int kind=e->CallIntMethod(req,read),n=-1,nv=0;if(p->pipe&&kind==1)g_object_get(p->pipe,"current-video",&n,nullptr);if(p->pipe&&kind==2){g_object_get(p->pipe,"current-audio",&n,"n-video",&nv,nullptr);if(n>=0)n+=nv;}e->CallVoidMethod(reply,write,n);return 0;}
 fprintf(stderr,"SDMEDIA=unsupported|invoke=%d\n",op);return -38;
}
static jboolean parameter(JNIEnv*,jobject,jint,jobject){return JNI_FALSE;}
static jboolean metadata(JNIEnv*,jobject,jboolean,jboolean,jobject){return JNI_FALSE;}
static jint filter(JNIEnv*,jobject,jobject){return -38;}
static void no_init(JNIEnv*,jclass){}
static jint list_product_strategies(JNIEnv*e,jclass,jobject list){
 if(!list){fail(e,"java/lang/IllegalArgumentException","Null audio product strategy list");return -22;}
 // The host has PulseAudio routes but no Android AudioPolicy product strategy
 // inventory. Report ENOSYS; AudioAttributes then uses its legacy stream map.
 fprintf(stderr,"SDAUDIO=product_strategies|status=-38|reason=android-policy-unavailable|host_routes=unchanged\n");return -38;
}
static void notify(JNIEnv*e,jobject s,jlong us){auto p=get(e,s);if(p)p->notify_us=us;}
static void next_player(JNIEnv*e,jobject,jobject next){if(next)unsupported(e,"MediaPlayer chaining");}
static void aux(JNIEnv*e,jobject,jint effect){if(effect)unsupported(e,"Audio auxiliary effect");}
static void aux_level(JNIEnv*e,jobject,jfloat level){if(level!=0)unsupported(e,"Audio auxiliary effect send");}
#include "registration.inc"
#include "retriever-host.inc"
extern "C" JNIEXPORT void JNICALL Java_SdMediaPlayer_nativeInstall(JNIEnv*e,jclass){
 e->GetJavaVM(&vm);jclass local=e->FindClass("android/media/MediaPlayer");if(!local)return;mp_class=(jclass)e->NewGlobalRef(local);context_field=e->GetFieldID(mp_class,"mNativeContext","J");post_event=e->GetStaticMethodID(mp_class,"postEventFromNative","(Ljava/lang/Object;IIILjava/lang/Object;)V");
 void*linker=dlopen("libdl_bio.so.0",RTLD_NOW|RTLD_GLOBAL);auto open=linker?(void*(*)(const char*,int))dlsym(linker,"bionic_dlopen"):nullptr;auto symbol=linker?(void*(*)(void*,const char*))dlsym(linker,"bionic_dlsym"):nullptr;
 const char*root=getenv("ANDROID_ROOT");char path[1024];if(!open||!symbol||!root)goto failed;
 snprintf(path,sizeof(path),"%s/android-libs/libandroid.so",root);
 {void*lib=open(path,RTLD_NOW);if(!lib)goto failed;
 from_surface=(decltype(from_surface))symbol(lib,"ANativeWindow_fromSurface");window_release=(decltype(window_release))symbol(lib,"ANativeWindow_release");window_geometry=(decltype(window_geometry))symbol(lib,"ANativeWindow_setBuffersGeometry");window_lock=(decltype(window_lock))symbol(lib,"ANativeWindow_lock");window_post=(decltype(window_post))symbol(lib,"ANativeWindow_unlockAndPost");}
 if(!from_surface||!window_release||!window_geometry||!window_lock||!window_post||!context_field||!post_event)goto failed;
 {GError*error=nullptr;if(!gst_init_check(nullptr,nullptr,&error)){fprintf(stderr,"SDMEDIA=init_error|message=%s\n",error?error->message:"");g_clear_error(&error);goto failed;}
  // Process-local preference avoids a second Android media-service dependency.
  const char*decoders[]={"avdec_h264","avdec_hevc","avdec_mpeg4","avdec_aac",nullptr};for(int i=0;decoders[i];i++){GstPluginFeature*f=gst_registry_find_feature(gst_registry_get(),decoders[i],GST_TYPE_ELEMENT_FACTORY);if(f){gst_plugin_feature_set_rank(f,GST_RANK_PRIMARY+100);gst_object_unref(f);}}
 }
 if(e->RegisterNatives(mp_class,methods,sizeof(methods)/sizeof(methods[0]))<0)return;
 if(!install_retriever(e))return;
 {jclass version=e->FindClass("android/os/Build$VERSION");if(!version)return;
  jint sdk=e->GetStaticIntField(version,e->GetStaticFieldID(version,"SDK_INT","I"));
  e->DeleteLocalRef(version);
  if(sdk>=29){
   jclass strategy=e->FindClass("android/media/audiopolicy/AudioProductStrategy");if(!strategy)return;
   JNINativeMethod policy[]={ {(char*)"native_list_audio_product_strategies",(char*)"(Ljava/util/ArrayList;)I",(void*)list_product_strategies} };
   int registered=e->RegisterNatives(strategy,policy,1);e->DeleteLocalRef(strategy);
   if(registered<0)return;
  }
 }
 fprintf(stderr,"SDMEDIA=installed|backend=gstreamer|native_methods=%zu|surface=android-bufferqueue|audio=pulseaudio\n",sizeof(methods)/sizeof(methods[0]));return;
failed:if(!e->ExceptionCheck())fail(e,"java/lang/IllegalStateException","MediaPlayer host backend installation failed");
}
