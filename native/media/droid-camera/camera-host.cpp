#include "protocol.h"
#include "headers/droidmediacamera.h"
#include <jni.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <dirent.h>
#include <spawn.h>
#include <poll.h>
#include <unistd.h>
#include <signal.h>
#include <dlfcn.h>
#include <atomic>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <map>
#include <deque>
#include <memory>
#include <vector>
#include <string>
#include <cstring>
#include <cstdio>
#include <cerrno>
#include <algorithm>
using namespace sd_camera;
extern char**environ;
static JavaVM*vm;
static jclass camera_class,access_class;
static jfieldID context_field;
static jmethodID post_event,access_check;
struct WindowBuffer{int32_t width,height,stride,format;void*bits;uint32_t reserved[6];};
static void*(*from_surface)(JNIEnv*,jobject);
static void(*window_release)(void*);
static int(*window_geometry)(void*,int32_t,int32_t,int32_t);
static int(*window_lock)(void*,WindowBuffer*,void*);
static int(*window_post)(void*);
static jfieldID texture_context_field,texture_listener_field;
static void*(*texture_notifications)(void*,void*);
static void(*release_texture_notifications)(void*);
static void fail(JNIEnv*e,const char*kind,const char*message){jclass c=e->FindClass(kind);if(c){e->ThrowNew(c,message);e->DeleteLocalRef(c);}}
struct Env{JNIEnv*e=nullptr;bool attached=false;Env(){if(vm->GetEnv((void**)&e,JNI_VERSION_1_6)==JNI_EDETACHED)attached=vm->AttachCurrentThreadAsDaemon((void**)&e,nullptr)==JNI_OK;}~Env(){if(attached)vm->DetachCurrentThread();}};
#include "hwui-sink.h"
struct Reply{Header h;std::vector<unsigned char>data;};
struct Client{
 int fd=-1;pid_t child=-1;std::thread reader;std::atomic<bool>quit{false},previewing{false},callback{false},manual{false};
 std::atomic<int>rotation{0};std::atomic<uint64_t>frames{0},callbacks{0};long id=0;bool mirror=false;jobject weak=nullptr;std::unique_ptr<GpuSurface>gpu;
 std::mutex request_mutex,reply_mutex,surface_mutex,buffer_mutex;std::condition_variable reply_ready;uint32_t sequence=0;std::map<uint32_t,Reply>replies;std::deque<jbyteArray>buffers;void*window=nullptr;void*notifications=nullptr;
 bool exact(void*dst,size_t size){char*p=(char*)dst;while(size&&!quit){ssize_t n=recv(fd,p,size,0);if(n<0&&errno==EINTR)continue;if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK)){pollfd poller{fd,POLLIN,0};poll(&poller,1,100);continue;}if(n<=0)return false;p+=n;size-=n;}return !size;}
 bool write_all(const void*src,size_t size){const char*p=(const char*)src;while(size&&!quit){ssize_t n=send(fd,p,size,MSG_NOSIGNAL);if(n<0&&errno==EINTR)continue;if(n<=0)return false;p+=n;size-=n;}return !size;}
 bool spawn(){
  int pair[2];if(socketpair(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0,pair))return false;
  fd=pair[0];timeval timeout{3,0};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
  const char*root=getenv("ANDROID_ROOT");if(!root){close(pair[0]);close(pair[1]);fd=-1;return false;}
  std::string executable=std::string(root)+"/libexec/sdcamera-helper";
  posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);posix_spawn_file_actions_adddup2(&actions,pair[1],3);
  DIR*directory=opendir("/proc/self/fd");if(!directory){close(pair[0]);close(pair[1]);fd=-1;posix_spawn_file_actions_destroy(&actions);return false;}
  for(dirent*entry;(entry=readdir(directory));){int n=atoi(entry->d_name);if(n>=4&&n!=dirfd(directory))posix_spawn_file_actions_addclose(&actions,n);}closedir(directory);
  std::vector<std::string>values;for(char**p=environ;*p;p++){
   std::string value=*p;auto equal=value.find('=');std::string key=value.substr(0,equal);
   if(key=="LD_LIBRARY_PATH"||key=="LD_PRELOAD"||key=="ANDROID_ROOT"||key=="ANDROID_DATA"||key=="ANDROID_ART_ROOT"||key=="ANDROID_RUNTIME_ROOT"||key=="ANDROID_I18N_ROOT"||key=="CLASSPATH"||key=="BOOTCLASSPATH")continue;
   values.push_back(value);
  }
  std::vector<char*>environment;for(auto&value:values)environment.push_back(value.data());environment.push_back(nullptr);char*argv[]={executable.data(),nullptr};
  posix_spawnattr_t attr;posix_spawnattr_init(&attr);posix_spawnattr_setflags(&attr,POSIX_SPAWN_SETPGROUP);posix_spawnattr_setpgroup(&attr,0);
  int rc=posix_spawn(&child,executable.c_str(),&actions,&attr,argv,environment.data());posix_spawnattr_destroy(&attr);posix_spawn_file_actions_destroy(&actions);close(pair[1]);
  if(rc){fprintf(stderr,"SDCAMERA=helper_spawn_failed|error=%d\n",rc);close(fd);fd=-1;child=-1;return false;}
  reader=std::thread([this]{loop();});return true;
 }
 bool call(uint32_t type,Reply&reply,int a=0,int b=0,const char*data=nullptr){
  std::lock_guard<std::mutex>serial(request_mutex);if(quit||fd<0)return false;Header h;h.type=type;h.sequence=++sequence;h.a=a;h.b=b;h.size=data?strlen(data):0;
  if(!write_all(&h,sizeof(h))||(h.size&&!write_all(data,h.size)))return false;
  std::unique_lock<std::mutex>guard(reply_mutex);if(!reply_ready.wait_for(guard,std::chrono::seconds(8),[&]{return quit||replies.count(h.sequence);}))return false;
  auto it=replies.find(h.sequence);if(it==replies.end())return false;reply=std::move(it->second);replies.erase(it);return true;
 }
 void event(JNIEnv*e,int what,int a,int b,jobject data=nullptr){if(!weak||quit)return;e->CallStaticVoidMethod(camera_class,post_event,weak,what,a,b,data);if(e->ExceptionCheck()){e->ExceptionDescribe();e->ExceptionClear();}}
 void frame(JNIEnv*e,const Header&h,const std::vector<unsigned char>&data){
  if(h.a<=0||h.b<=0||h.a>4096||h.b>4096||h.a%2||h.b%2||h.c!=17||data.size()<size_t(h.a)*h.b*3/2)return;
  uint64_t hash=1469598103934665603ULL;for(size_t i=0;i<data.size();i+=997)hash=(hash^data[i])*1099511628211ULL;bool posted=false;
  {std::lock_guard<std::mutex>g(surface_mutex);if(window&&!quit){
   int angle=rotation.load(),w=angle%180?h.b:h.a,height=angle%180?h.a:h.b;
   bool hardware=gpu_api().ready&&gpu_api().frames(window)>=0;
   if(hardware){int rows=height,cols=w;std::vector<unsigned char>rgba(size_t(w)*height*4);WindowBuffer out{w,height,w,1,rgba.data(),{}};
    for(int y=0;y<rows;y++)for(int x=0;x<cols;x++){
     int display_x=mirror?w-1-x:x;int sx=display_x,sy=y;if(angle==90){sx=y;sy=h.b-1-display_x;}else if(angle==180){sx=h.a-1-display_x;sy=h.b-1-y;}else if(angle==270){sx=h.a-1-y;sy=display_x;}
     int yy=int(data[size_t(sy)*h.a+sx])-16;size_t uv=size_t(h.a)*h.b+(sy/2)*h.a+(sx&~1);int v=int(data[uv])-128,u=int(data[uv+1])-128;
     auto clamp=[](int value){return (unsigned char)std::max(0,std::min(255,value));};unsigned char*dst=(unsigned char*)out.bits+(size_t(y)*out.stride+x)*4;
     dst[0]=clamp((298*yy+409*v+128)>>8);dst[1]=clamp((298*yy-100*u-208*v+128)>>8);dst[2]=clamp((298*yy+516*u+128)>>8);dst[3]=255;
    }
    if(!gpu||gpu->window!=window)gpu.reset(new GpuSurface(window));posted=gpu->pixels(rgba.data(),w,height);
   }else if(window_geometry(window,w,height,1)==0){WindowBuffer out{};if(window_lock(window,&out,nullptr)==0){
    int rows=std::min(height,out.height),cols=std::min(w,out.width);
    for(int y=0;y<rows;y++)for(int x=0;x<cols;x++){
     int display_x=mirror?w-1-x:x;int sx=display_x,sy=y;if(angle==90){sx=y;sy=h.b-1-display_x;}else if(angle==180){sx=h.a-1-display_x;sy=h.b-1-y;}else if(angle==270){sx=h.a-1-y;sy=display_x;}
     int yy=int(data[size_t(sy)*h.a+sx])-16;size_t uv=size_t(h.a)*h.b+(sy/2)*h.a+(sx&~1);int v=int(data[uv])-128,u=int(data[uv+1])-128;
     auto clamp=[](int value){return (unsigned char)std::max(0,std::min(255,value));};unsigned char*dst=(unsigned char*)out.bits+(size_t(y)*out.stride+x)*4;
     dst[0]=clamp((298*yy+409*v+128)>>8);dst[1]=clamp((298*yy-100*u-208*v+128)>>8);dst[2]=clamp((298*yy+516*u+128)>>8);dst[3]=255;
    }
    posted=window_post(window)==0;
   }}
  }}
  uint64_t n=++frames;if(n==1||n%30==0)fprintf(stderr,"SDCAMERA=preview_frame|id=%ld|n=%llu|size=%dx%d|format=nv21|hash=%016llx|posted=%d|rotation=%d\n",id,(unsigned long long)n,h.a,h.b,(unsigned long long)hash,posted,rotation.load());
  jbyteArray array=nullptr;bool global_ref=false;
  {std::lock_guard<std::mutex>g(buffer_mutex);if(callback){if(manual){if(!buffers.empty()){array=buffers.front();buffers.pop_front();global_ref=true;if(e->GetArrayLength(array)<(jsize)data.size()){e->DeleteGlobalRef(array);array=nullptr;}}}else if(callback.exchange(false))array=e->NewByteArray(data.size());}}
  if(array){e->SetByteArrayRegion(array,0,data.size(),(const jbyte*)data.data());event(e,0x10,0,0,array);if(global_ref)e->DeleteGlobalRef(array);else e->DeleteLocalRef(array);uint64_t count=++callbacks;if(count==1||count%30==0)fprintf(stderr,"SDCAMERA=preview_callback|id=%ld|n=%llu|bytes=%zu\n",id,(unsigned long long)count,data.size());}
 }
 void faces(JNIEnv*e,const std::vector<unsigned char>&data){
  if(data.size()%sizeof(DroidMediaCameraFace)||data.size()/sizeof(DroidMediaCameraFace)>100)return;
  jclass face=e->FindClass("android/hardware/Camera$Face"),rect=e->FindClass("android/graphics/Rect"),point=e->FindClass("android/graphics/Point");if(!face||!rect||!point)return;
  jmethodID ctor=e->GetMethodID(face,"<init>","()V"),rc=e->GetMethodID(rect,"<init>","(IIII)V"),pc=e->GetMethodID(point,"<init>","(II)V");size_t count=data.size()/sizeof(DroidMediaCameraFace);jobjectArray array=e->NewObjectArray(count,face,nullptr);
  for(size_t i=0;i<count;i++){DroidMediaCameraFace f;memcpy(&f,data.data()+i*sizeof(f),sizeof(f));jobject value=e->NewObject(face,ctor),bounds=e->NewObject(rect,rc,f.left,f.top,f.right,f.bottom);e->SetObjectField(value,e->GetFieldID(face,"rect","Landroid/graphics/Rect;"),bounds);e->DeleteLocalRef(bounds);e->SetIntField(value,e->GetFieldID(face,"score","I"),f.score);e->SetIntField(value,e->GetFieldID(face,"id","I"),f.id);
   if(f.id>=0){const char*names[]={"leftEye","rightEye","mouth"};int32_t*positions[]={f.left_eye,f.right_eye,f.mouth};for(int k=0;k<3;k++){jobject coordinate=e->NewObject(point,pc,positions[k][0],positions[k][1]);e->SetObjectField(value,e->GetFieldID(face,names[k],"Landroid/graphics/Point;"),coordinate);e->DeleteLocalRef(coordinate);}}
   e->SetObjectArrayElement(array,i,value);e->DeleteLocalRef(value);
  }
  event(e,0x400,0,0,array);e->DeleteLocalRef(array);e->DeleteLocalRef(face);e->DeleteLocalRef(rect);e->DeleteLocalRef(point);
 }
 void loop(){
  Env env;Header h;while(!quit&&exact(&h,sizeof(h))){if(h.magic!=magic||h.size>max_payload)break;std::vector<unsigned char>data(h.size);if(h.size&&!exact(data.data(),h.size))break;
   if(h.type&response){std::lock_guard<std::mutex>guard(reply_mutex);replies[h.sequence]=Reply{h,std::move(data)};reply_ready.notify_all();}
   else if((h.type&sd_camera::event)&&env.e){int type=h.type&~sd_camera::event;if(type==0x10)frame(env.e,h,data);else if(type==0x400)faces(env.e,data);else{jbyteArray array=nullptr;if(h.size){array=env.e->NewByteArray(data.size());if(array)env.e->SetByteArrayRegion(array,0,data.size(),(const jbyte*)data.data());}this->event(env.e,type,h.a,h.b,array);if(array)env.e->DeleteLocalRef(array);}}
  }
  quit=true;reply_ready.notify_all();
 }
 void shutdown(){
  if(!quit&&fd>=0){Reply reply;call(CLOSE,reply);}quit=true;if(fd>=0)::shutdown(fd,SHUT_RDWR);reply_ready.notify_all();if(reader.joinable())reader.join();if(fd>=0){close(fd);fd=-1;}
  if(child>0){int status;bool exited=false;for(int i=0;i<20;i++){pid_t rc=waitpid(child,&status,WNOHANG);if(rc==child||(rc<0&&errno==ECHILD)){exited=true;break;}usleep(10000);}if(!exited){kill(child,SIGTERM);for(int i=0;i<30;i++){if(waitpid(child,&status,WNOHANG)==child){exited=true;break;}usleep(10000);}if(!exited){kill(child,SIGKILL);waitpid(child,&status,0);}}child=-1;}
  {std::lock_guard<std::mutex>g(surface_mutex);if(notifications){release_texture_notifications(notifications);notifications=nullptr;}if(window){window_release(window);window=nullptr;}}
  Env env;if(env.e){std::lock_guard<std::mutex>g(buffer_mutex);for(auto array:buffers)env.e->DeleteGlobalRef(array);buffers.clear();if(weak){env.e->DeleteGlobalRef(weak);weak=nullptr;}}
 }
 ~Client(){shutdown();}
};
static std::mutex registry_mutex,metadata_mutex;static std::atomic<long>next_id{1};static std::map<long,std::shared_ptr<Client>>registry;
struct Info{int facing,orientation,host_id;};static std::vector<Info>camera_info,legacy_camera_info;static bool metadata_known=false;
static int count(JNIEnv*,jclass){
 std::lock_guard<std::mutex>guard(metadata_mutex);if(metadata_known)return camera_info.size();
 Client client;Reply reply;if(!client.spawn()||!client.call(COUNT,reply)||reply.h.a||reply.h.b<0||reply.h.b>8){fprintf(stderr,"SDCAMERA=enumerate|exposed=0|backend=droidmedia|reason=metadata-query-failed\n");return 0;}
 int size=reply.h.b;std::vector<Info>items,aliases;bool exposed[2]={false,false};
 for(int i=0;i<size;i++){
  if(!client.call(INFO,reply,i)||reply.h.a)return 0;
  Info value{reply.h.b==1?0:1,reply.h.c,i};aliases.push_back(value);
  // Camera1 uses the primary route for each facing. Hybris can also expose
  // auxiliary IDs which connect successfully but cannot start a Camera1 preview.
  if(!exposed[value.facing]){items.push_back(value);exposed[value.facing]=true;}
 }
 // Older applications can have cached the auxiliary IDs. Keep those IDs
 // usable as aliases to the corresponding primary route without advertising
 // extra cameras to new callers.
 for(auto&alias:aliases){auto primary=std::find_if(items.begin(),items.end(),[&](const Info&value){return value.facing==alias.facing;});alias=*primary;}
 client.shutdown();camera_info=items;legacy_camera_info=aliases;metadata_known=true;fprintf(stderr,"SDCAMERA=enumerate|exposed=%zu|backend=droidmedia|host_camera_count=%d\n",items.size(),size);return items.size();
}
static const Info*camera_metadata(JNIEnv*e,int id){
 count(e,nullptr);if(id<0)return nullptr;
 if(size_t(id)<camera_info.size())return &camera_info[id];
 if(size_t(id)<legacy_camera_info.size())return &legacy_camera_info[id];
 return nullptr;
}
static void info(JNIEnv*e,jclass,jint id,jobject object){const Info*value=camera_metadata(e,id);if(!value||!object){fail(e,"java/lang/RuntimeException","Invalid camera ID or CameraInfo");return;}jclass type=e->GetObjectClass(object);e->SetIntField(object,e->GetFieldID(type,"facing","I"),value->facing);e->SetIntField(object,e->GetFieldID(type,"orientation","I"),value->orientation);e->DeleteLocalRef(type);}
static std::shared_ptr<Client>get(JNIEnv*e,jobject self){long id=e->GetLongField(self,context_field);std::lock_guard<std::mutex>guard(registry_mutex);auto it=registry.find(id);if(it!=registry.end())return it->second;fail(e,"java/lang/RuntimeException","Camera is released");return{};}
static bool call(JNIEnv*e,std::shared_ptr<Client>client,uint32_t type,int a=0,int b=0,const char*data=nullptr,Reply*out=nullptr){if(!client)return false;Reply reply;if(!client->call(type,reply,a,b,data)||reply.h.a){fprintf(stderr,"SDCAMERA=command_failed|id=%ld|op=%u|status=%d\n",client->id,type,reply.h.a);fail(e,"java/lang/RuntimeException","Physical camera command failed");return false;}if(out)*out=std::move(reply);return true;}
static jint setup(JNIEnv*e,jobject self,jobject weak,jint id,jint,jstring){
 e->CallStaticVoidMethod(access_class,access_check);if(e->ExceptionCheck())return -13;const Info*value=camera_metadata(e,id);if(!value)return -19;
 auto client=std::make_shared<Client>();client->id=next_id++;if(!client->spawn())return -19;Reply reply;if(!client->call(OPEN,reply,value->host_id)||reply.h.a)return -13;
 client->mirror=value->facing==1;client->weak=e->NewGlobalRef(weak);{std::lock_guard<std::mutex>g(registry_mutex);registry[client->id]=client;}e->SetLongField(self,context_field,client->id);
 fprintf(stderr,"SDCAMERA=opened|id=%ld|camera=%d|host_camera=%d|facing=%d|helper_pid=%d|backend=droidmedia\n",client->id,id,value->host_id,value->facing,client->child);return 0;
}
static void release(JNIEnv*e,jobject self){long id=e->GetLongField(self,context_field);e->SetLongField(self,context_field,0);std::shared_ptr<Client>client;{std::lock_guard<std::mutex>g(registry_mutex);auto it=registry.find(id);if(it!=registry.end()){client=it->second;registry.erase(it);}}if(client){client->shutdown();fprintf(stderr,"SDCAMERA=released|id=%ld|frames=%llu|callbacks=%llu|helper_remaining=0\n",id,(unsigned long long)client->frames.load(),(unsigned long long)client->callbacks.load());}}
static void attach_surface(JNIEnv*e,jobject self,jobject value,jobject texture=nullptr){
 auto client=get(e,self);if(!client)return;
 void*window=value?from_surface(e,value):nullptr;
 if(value&&!window){if(!e->ExceptionCheck())fail(e,"java/io/IOException","Invalid camera preview surface");return;}
 std::lock_guard<std::mutex>g(client->surface_mutex);
 if(client->notifications){release_texture_notifications(client->notifications);client->notifications=nullptr;}
 if(client->window)window_release(client->window);
 client->window=window;
 if(texture){
  void*consumer=(void*)(intptr_t)e->GetLongField(texture,texture_context_field);
  void*listener=(void*)(intptr_t)e->GetLongField(texture,texture_listener_field);
  client->notifications=texture_notifications(consumer,listener);
  if(!client->notifications){window_release(window);client->window=nullptr;fail(e,"java/io/IOException","Camera texture listener is unavailable");return;}
  fprintf(stderr,"SDCAMERA=texture_notifications|id=%ld|frame_replaced=forwarded\n",client->id);
 }
 fprintf(stderr,"SDCAMERA=surface|id=%ld|attached=%d\n",client->id,window!=nullptr);
}
static void surface(JNIEnv*e,jobject self,jobject value){attach_surface(e,self,value);}
static void texture(JNIEnv*e,jobject self,jobject value){if(!value){surface(e,self,nullptr);return;}jclass type=e->FindClass("android/view/Surface");jmethodID ctor=e->GetMethodID(type,"<init>","(Landroid/graphics/SurfaceTexture;)V"),close=e->GetMethodID(type,"release","()V");jobject object=e->NewObject(type,ctor,value);if(!e->ExceptionCheck()){attach_surface(e,self,object,value);e->CallVoidMethod(object,close);e->DeleteLocalRef(object);}e->DeleteLocalRef(type);}
static void start(JNIEnv*e,jobject self){auto c=get(e,self);if(call(e,c,START)){c->previewing=true;fprintf(stderr,"SDCAMERA=preview_started|id=%ld\n",c->id);}}
static void stop(JNIEnv*e,jobject self){auto c=get(e,self);if(call(e,c,STOP)){c->previewing=false;fprintf(stderr,"SDCAMERA=preview_stopped|id=%ld\n",c->id);}}
static jboolean preview_enabled(JNIEnv*e,jobject self){auto c=get(e,self);return c&&c->previewing;}
static void callback(JNIEnv*e,jobject self,jboolean installed,jboolean manual){auto c=get(e,self);if(!c)return;std::lock_guard<std::mutex>g(c->buffer_mutex);c->manual=manual;c->callback=installed;if(!installed||!manual){for(auto array:c->buffers)e->DeleteGlobalRef(array);c->buffers.clear();}}
static void buffer(JNIEnv*e,jobject self,jbyteArray value,jint type){auto c=get(e,self);if(!c)return;if(type!=0x10){fail(e,"java/lang/UnsupportedOperationException","Raw callback buffers are unavailable");return;}if(!value)return;std::lock_guard<std::mutex>g(c->buffer_mutex);if(c->buffers.size()>=64){fail(e,"java/lang/IllegalStateException","Too many camera callback buffers");return;}c->buffers.push_back((jbyteArray)e->NewGlobalRef(value));}
static void parameters(JNIEnv*e,jobject self,jstring value){if(!value){fail(e,"java/lang/IllegalArgumentException","Null camera parameters");return;}auto c=get(e,self);const char*text=e->GetStringUTFChars(value,nullptr);if(text){call(e,c,SET_PARAMETERS,0,0,text);e->ReleaseStringUTFChars(value,text);}}
static jstring get_parameters(JNIEnv*e,jobject self){Reply reply;if(!call(e,get(e,self),PARAMETERS,0,0,nullptr,&reply))return nullptr;std::string text(reply.data.begin(),reply.data.end());return e->NewStringUTF(text.c_str());}
static void lock_camera(JNIEnv*e,jobject self){call(e,get(e,self),LOCK);}static void unlock_camera(JNIEnv*e,jobject self){call(e,get(e,self),UNLOCK);}static void reconnect(JNIEnv*e,jobject self){call(e,get(e,self),RECONNECT);}
static void focus(JNIEnv*e,jobject self){call(e,get(e,self),FOCUS);}static void cancel_focus(JNIEnv*e,jobject self){call(e,get(e,self),CANCEL_FOCUS);}static void focus_move(JNIEnv*e,jobject self,jint enable){call(e,get(e,self),FOCUS_MOVE,enable);}
static void take(JNIEnv*e,jobject self,jint flags){auto c=get(e,self);if(call(e,c,TAKE,flags)){c->previewing=false;fprintf(stderr,"SDCAMERA=capture_requested|id=%ld|messages=%d\n",c->id,flags);}}
static void orientation(JNIEnv*e,jobject self,jint degrees){if(degrees!=0&&degrees!=90&&degrees!=180&&degrees!=270){fail(e,"java/lang/IllegalArgumentException","Invalid display orientation");return;}auto c=get(e,self);if(!c)return;c->rotation=degrees;fprintf(stderr,"SDCAMERA=orientation|id=%ld|degrees=%d\n",c->id,degrees);}
static void zoom(JNIEnv*e,jobject self,jint value){call(e,get(e,self),ZOOM,value,0);}static void stop_zoom(JNIEnv*e,jobject self){call(e,get(e,self),ZOOM,0,1);}static jboolean shutter(JNIEnv*e,jobject self,jboolean enabled){return call(e,get(e,self),SHUTTER_SOUND,enabled);}
static void face_start(JNIEnv*e,jobject self,jint type){call(e,get(e,self),FACE,type,1);}static void face_stop(JNIEnv*e,jobject self){call(e,get(e,self),FACE,0,0);}
static void allocation_surface(JNIEnv*e,jobject self,jobject value){if(!get(e,self))return;if(value)fail(e,"java/lang/UnsupportedOperationException","Camera RenderScript callback surface is unavailable");}
#define METHOD(name,signature,function) {(char*)name,(char*)signature,(void*)function}
static JNINativeMethod methods[]={
 METHOD("getNumberOfCameras","()I",count),METHOD("_getCameraInfo","(ILandroid/hardware/Camera$CameraInfo;)V",info),METHOD("native_setup","(Ljava/lang/Object;IILjava/lang/String;)I",setup),METHOD("native_release","()V",release),
 METHOD("unlock","()V",unlock_camera),METHOD("lock","()V",lock_camera),METHOD("reconnect","()V",reconnect),METHOD("setPreviewSurface","(Landroid/view/Surface;)V",surface),METHOD("setPreviewTexture","(Landroid/graphics/SurfaceTexture;)V",texture),METHOD("startPreview","()V",start),METHOD("_stopPreview","()V",stop),METHOD("previewEnabled","()Z",preview_enabled),
 METHOD("setHasPreviewCallback","(ZZ)V",callback),METHOD("_addCallbackBuffer","([BI)V",buffer),METHOD("setPreviewCallbackSurface","(Landroid/view/Surface;)V",allocation_surface),METHOD("native_autoFocus","()V",focus),METHOD("native_cancelAutoFocus","()V",cancel_focus),METHOD("enableFocusMoveCallback","(I)V",focus_move),METHOD("native_takePicture","(I)V",take),METHOD("startSmoothZoom","(I)V",zoom),METHOD("stopSmoothZoom","()V",stop_zoom),METHOD("setDisplayOrientation","(I)V",orientation),METHOD("_enableShutterSound","(Z)Z",shutter),METHOD("_startFaceDetection","(I)V",face_start),METHOD("_stopFaceDetection","()V",face_stop),METHOD("native_setParameters","(Ljava/lang/String;)V",parameters),METHOD("native_getParameters","()Ljava/lang/String;",get_parameters)
};
extern "C" JNIEXPORT jint JNICALL Java_SdCamera_nativeCount(JNIEnv*e,jclass c){return count(e,c);}
extern "C" JNIEXPORT void JNICALL Java_SdCamera_nativeInstall(JNIEnv*e,jclass type){
 e->GetJavaVM(&vm);jclass local=e->FindClass("android/hardware/Camera");if(!local)return;camera_class=(jclass)e->NewGlobalRef(local);e->DeleteLocalRef(local);access_class=(jclass)e->NewGlobalRef(type);access_check=e->GetStaticMethodID(type,"enforceAccess","()V");context_field=e->GetFieldID(camera_class,"mNativeContext","J");post_event=e->GetStaticMethodID(camera_class,"postEventFromNative","(Ljava/lang/Object;IIILjava/lang/Object;)V");
 void*linker=dlopen("libdl_bio.so.0",RTLD_NOW|RTLD_GLOBAL);auto open=linker?(void*(*)(const char*,int))dlsym(linker,"bionic_dlopen"):nullptr;auto symbol=linker?(void*(*)(void*,const char*))dlsym(linker,"bionic_dlsym"):nullptr;const char*root=getenv("ANDROID_ROOT");
 if(open&&symbol&&root){std::string path=std::string(root)+"/android-libs/libandroid.so";void*lib=open(path.c_str(),RTLD_NOW);if(lib){from_surface=(decltype(from_surface))symbol(lib,"ANativeWindow_fromSurface");window_release=(decltype(window_release))symbol(lib,"ANativeWindow_release");window_geometry=(decltype(window_geometry))symbol(lib,"ANativeWindow_setBuffersGeometry");window_lock=(decltype(window_lock))symbol(lib,"ANativeWindow_lock");window_post=(decltype(window_post))symbol(lib,"ANativeWindow_unlockAndPost");}}
 if(open&&symbol&&root){std::string path=std::string(root)+"/android-libs/libsdtexture-android.so";void*lib=open(path.c_str(),RTLD_NOW);if(lib){texture_notifications=(decltype(texture_notifications))symbol(lib,"sd_texture_camera_notifications");release_texture_notifications=(decltype(release_texture_notifications))symbol(lib,"sd_texture_release_camera_notifications");}}
 jclass texture_type=e->FindClass("android/graphics/SurfaceTexture");if(texture_type){texture_context_field=e->GetFieldID(texture_type,"mSurfaceTexture","J");texture_listener_field=e->GetFieldID(texture_type,"mFrameAvailableListener","J");e->DeleteLocalRef(texture_type);}
 if(e->ExceptionCheck())return;
 if(!from_surface||!window_release||!window_geometry||!window_lock||!window_post||!texture_notifications||!release_texture_notifications||!texture_context_field||!texture_listener_field||!context_field||!post_event||!access_check){fail(e,"java/lang/IllegalStateException","Camera native window bridge is unavailable");return;}
 if(e->RegisterNatives(camera_class,methods,sizeof(methods)/sizeof(methods[0]))<0)return;
 fprintf(stderr,"SDCAMERA=installed|backend=droidmedia-helper|native_methods=%zu|surface=android-bufferqueue\n",sizeof(methods)/sizeof(methods[0]));
}

#include "surface-views-host.h"
