#include "host-common.hpp"
#include <jni.h>
#include <pulse/pulseaudio.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
#include "audio-connection.hpp"

namespace {
struct QueryData {
  Json result = {{"outputs", Json::array()}, {"inputs", Json::array()}};
  std::string default_sink, default_source;
  struct Connection {
    uint32_t device;
    std::string address;
  };
  std::vector<Connection> connections;

  void port(const char *name, bool input, int available, bool active) {
    uint32_t type = sd_audio_connection::port_device(name ? name : "", input);
    if (type && sd_audio_connection::present(available, active))
      connections.push_back({type, ""});
  }

  void endpoint(pa_proplist *properties, bool input) {
    auto property = [properties](const char *key) {
      const char *value = properties ? pa_proplist_gets(properties, key) : nullptr;
      return std::string(value ? value : "");
    };
    std::string api = property("device.api");
    if (property("device.bus") == "usb") api = "usb";
    uint32_t type = sd_audio_connection::endpoint_device(
        api, property("bluetooth.protocol"), property("api.bluez5.profile"), input);
    std::string address = property("device.string");
    if (address.empty()) address = property("api.bluez5.address");
    if (type) connections.push_back({type, address});
  }
};

struct Query : QueryData {
  pa_mainloop *loop = pa_mainloop_new();
  pa_context *context = nullptr;

  Query(){
    if(!loop)throw std::runtime_error("PulseAudio mainloop allocation failed");
    context=pa_context_new(pa_mainloop_get_api(loop),"SailDroid audio queries");
    if(!context||pa_context_connect(context,nullptr,PA_CONTEXT_NOAUTOSPAWN,nullptr)<0)throw std::runtime_error("Host audio server unavailable");
    auto end=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    while(pa_context_get_state(context)!=PA_CONTEXT_READY){
      auto state=pa_context_get_state(context);
      if(!PA_CONTEXT_IS_GOOD(state)||std::chrono::steady_clock::now()>end)throw std::runtime_error("Host audio connection deadline");
      pa_mainloop_iterate(loop,1,nullptr);
    }
  }
  ~Query(){if(context){pa_context_disconnect(context);pa_context_unref(context);}if(loop)pa_mainloop_free(loop);}
  void wait(pa_operation *op){
    if(!op)throw std::runtime_error("Host audio operation unavailable");
    auto end=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    while(pa_operation_get_state(op)==PA_OPERATION_RUNNING){
      pa_mainloop_iterate(loop,1,nullptr);
      if(std::chrono::steady_clock::now()>end){pa_operation_cancel(op);pa_operation_unref(op);throw std::runtime_error("Host audio query deadline");}
    }
    pa_operation_unref(op);
  }
};
void server(pa_context*,const pa_server_info *info,void *data){auto&q=*static_cast<QueryData*>(data);if(info){q.default_sink=info->default_sink_name?info->default_sink_name:"";q.default_source=info->default_source_name?info->default_source_name:"";}}
std::string property(pa_proplist *properties,const char *name){
  const char *value=properties?pa_proplist_gets(properties,name):nullptr;
  return value?value:"";
}
void sink(pa_context*,const pa_sink_info *info,int end,void *data){
  if(end||!info)return;
  auto &query=*static_cast<QueryData*>(data);
  Json row={
    {"id",info->index},
    {"name",info->name?info->name:""},
    {"description",info->description?info->description:""},
    {"rate",info->sample_spec.rate},
    {"channels",info->sample_spec.channels},
    {"volume",double(pa_cvolume_avg(&info->volume))/PA_VOLUME_NORM},
    {"muted",bool(info->mute)},
    {"active",info->state==PA_SINK_RUNNING},
    {"default",query.default_sink==(info->name?info->name:"")},
    {"device_api",property(info->proplist,"device.api")},
    {"bluetooth_protocol",property(info->proplist,"bluetooth.protocol")},
    {"bluez5_profile",property(info->proplist,"api.bluez5.profile")}
  };
  query.result["outputs"].push_back(row);
}
void source(pa_context*,const pa_source_info *i,int end,void *data){if(end||!i||i->monitor_of_sink!=PA_INVALID_INDEX)return;auto&q=*static_cast<QueryData*>(data);Json row={{"id",i->index},{"name",i->name?i->name:""},{"description",i->description?i->description:""},{"rate",i->sample_spec.rate},{"channels",i->sample_spec.channels},{"muted",bool(i->mute)},{"active",i->state==PA_SOURCE_RUNNING},{"default",q.default_source==(i->name?i->name:"")},{"physical",bool(i->flags&PA_SOURCE_HARDWARE)}};q.result["inputs"].push_back(row);}
void connection_sink(pa_context *, const pa_sink_info *info, int end, void *data) {
  if (end || !info) return;
  auto &query = *static_cast<QueryData *>(data);
  query.endpoint(info->proplist, false);
  bool droid = property(info->proplist, "device.api") == "droid-hal";
  for (uint32_t index = 0; index < info->n_ports; index++) {
    auto *port = info->ports[index];
    query.port(port->name, false, droid ? 0 : port->available,
               info->active_port && std::string(info->active_port->name) == port->name);
  }
}

void connection_source(pa_context *, const pa_source_info *info, int end, void *data) {
  if (end || !info || info->monitor_of_sink != PA_INVALID_INDEX) return;
  auto &query = *static_cast<QueryData *>(data);
  query.endpoint(info->proplist, true);
  bool droid = property(info->proplist, "device.api") == "droid-hal";
  for (uint32_t index = 0; index < info->n_ports; index++) {
    auto *port = info->ports[index];
    query.port(port->name, true, droid ? 0 : port->available,
               info->active_port && std::string(info->active_port->name) == port->name);
  }
}

void connection_card(pa_context *, const pa_card_info *info, int end, void *data) {
  if (end || !info) return;
  auto &query = *static_cast<QueryData *>(data);
  bool droid = !property(info->proplist, "droid.hw_module").empty();
  for (uint32_t index = 0; index < info->n_ports; index++) {
    auto *port = info->ports[index];
    // The droid HAL catalogue includes unplugged accessories. Built-in ports
    // can exist without selection, while external routes require selection.
    if (droid) {
      uint32_t output = sd_audio_connection::port_device(port->name ? port->name : "", false);
      uint32_t input = sd_audio_connection::port_device(port->name ? port->name : "", true);
      if (output != 1 && output != 2 && input != 0x80000004u) continue;
    }
    if (port->direction & PA_DIRECTION_OUTPUT)
      query.port(port->name, false, port->available, false);
    if (port->direction & PA_DIRECTION_INPUT)
      query.port(port->name, true, port->available, false);
  }
}

class AudioMonitor {
  std::mutex mutex;
  std::condition_variable cv;
  std::string cached_snapshot;
  std::vector<QueryData::Connection> cached_connections;
  uint64_t generation = 0;
  bool running = false;
  bool ready = false;
  std::string failure_reason;
  pa_mainloop *active_loop = nullptr;
  std::atomic<bool> dirty{false};

  static bool wait_op(pa_mainloop *loop, pa_context *ctx, pa_operation *op) {
    if (!op) return false;
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (pa_operation_get_state(op) == PA_OPERATION_RUNNING) {
      if (!PA_CONTEXT_IS_GOOD(pa_context_get_state(ctx)) ||
          std::chrono::steady_clock::now() > deadline) {
        pa_operation_cancel(op);
        pa_operation_unref(op);
        return false;
      }
      if (pa_mainloop_iterate(loop, 1, nullptr) < 0) {
        pa_operation_unref(op);
        return false;
      }
    }
    pa_operation_unref(op);
    return true;
  }

  bool refresh(pa_mainloop *loop, pa_context *ctx) {
    QueryData data;
    if (!wait_op(loop, ctx, pa_context_get_server_info(ctx, server, &data)) ||
        !wait_op(loop, ctx, pa_context_get_card_info_list(ctx, connection_card, &data)) ||
        !wait_op(loop, ctx, pa_context_get_sink_info_list(ctx, sink, &data)) ||
        !wait_op(loop, ctx, pa_context_get_sink_info_list(ctx, connection_sink, &data)) ||
        !wait_op(loop, ctx, pa_context_get_source_info_list(ctx, source, &data)) ||
        !wait_op(loop, ctx, pa_context_get_source_info_list(ctx, connection_source, &data)))
      return false;
    std::string serialized = data.result.dump();
    std::lock_guard<std::mutex> lock(mutex);
    cached_snapshot = std::move(serialized);
    cached_connections = std::move(data.connections);
    ++generation;
    ready = true;
    failure_reason.clear();
    cv.notify_all();
    return true;
  }

  void worker() {
    pa_mainloop *loop = pa_mainloop_new();
    if (!loop) {
      std::lock_guard<std::mutex> lock(mutex);
      running = false;
      ready = false;
      failure_reason = "PulseAudio mainloop allocation failed";
      cv.notify_all();
      return;
    }
    pa_context *ctx = pa_context_new(pa_mainloop_get_api(loop), "SailDroid audio monitor");
    if (!ctx || pa_context_connect(ctx, nullptr, PA_CONTEXT_NOAUTOSPAWN, nullptr) < 0) {
      if (ctx) pa_context_unref(ctx);
      pa_mainloop_free(loop);
      std::lock_guard<std::mutex> lock(mutex);
      running = false;
      ready = false;
      failure_reason = "Host audio server unavailable";
      cv.notify_all();
      return;
    }
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    bool connected = false;
    while (std::chrono::steady_clock::now() <= deadline) {
      auto state = pa_context_get_state(ctx);
      if (state == PA_CONTEXT_READY) { connected = true; break; }
      if (!PA_CONTEXT_IS_GOOD(state) || pa_mainloop_iterate(loop, 1, nullptr) < 0) break;
    }
    if (!connected) {
      pa_context_disconnect(ctx);
      pa_context_unref(ctx);
      pa_mainloop_free(loop);
      std::lock_guard<std::mutex> lock(mutex);
      running = false;
      ready = false;
      failure_reason = "Host audio connection deadline";
      cv.notify_all();
      return;
    }
    pa_context_set_subscribe_callback(
        ctx,
        [](pa_context *, pa_subscription_event_type_t, uint32_t, void *userdata) {
          auto *self = static_cast<AudioMonitor *>(userdata);
          self->dirty.store(true, std::memory_order_release);
        },
        this);
    auto mask = static_cast<pa_subscription_mask_t>(
        PA_SUBSCRIPTION_MASK_SINK | PA_SUBSCRIPTION_MASK_SOURCE |
        PA_SUBSCRIPTION_MASK_CARD | PA_SUBSCRIPTION_MASK_SERVER);
    wait_op(loop, ctx, pa_context_subscribe(ctx, mask, nullptr, nullptr));
    {
      std::lock_guard<std::mutex> lock(mutex);
      active_loop = loop;
    }
    if (refresh(loop, ctx)) {
      while (PA_CONTEXT_IS_GOOD(pa_context_get_state(ctx))) {
        if (dirty.exchange(false, std::memory_order_acq_rel)) {
          if (!refresh(loop, ctx)) break;
          continue;
        }
        if (pa_mainloop_iterate(loop, 1, nullptr) < 0) break;
      }
    }
    {
      std::lock_guard<std::mutex> lock(mutex);
      active_loop = nullptr;
      running = false;
      ready = false;
      if (failure_reason.empty()) failure_reason = "Host audio server unavailable";
      ++generation;
      cv.notify_all();
    }
    pa_context_disconnect(ctx);
    pa_context_unref(ctx);
    pa_mainloop_free(loop);
  }

  void ensure_locked(std::unique_lock<std::mutex> &lock) {
    if (ready) return;
    if (!running) {
      running = true;
      failure_reason.clear();
      std::thread(&AudioMonitor::worker, this).detach();
    }
    cv.wait_for(lock, std::chrono::milliseconds(2500), [&] { return ready || !running; });
    if (!ready)
      throw std::runtime_error(failure_reason.empty() ? "Host audio server unavailable" : failure_reason);
  }

public:
  std::string snapshot() {
    std::unique_lock<std::mutex> lock(mutex);
    ensure_locked(lock);
    return cached_snapshot;
  }

  std::vector<QueryData::Connection> connections() {
    std::unique_lock<std::mutex> lock(mutex);
    ensure_locked(lock);
    return cached_connections;
  }

  uint64_t await_change(uint64_t known, int64_t timeout_ms) {
    std::unique_lock<std::mutex> lock(mutex);
    ensure_locked(lock);
    if (generation == known && timeout_ms > 0) {
      cv.wait_for(lock, std::chrono::milliseconds(timeout_ms),
                  [&] { return generation != known || !ready; });
    }
    if (!ready)
      throw std::runtime_error(failure_reason.empty() ? "Host audio server unavailable" : failure_reason);
    return generation;
  }
};

AudioMonitor &audio_monitor() {
  static AudioMonitor monitor;
  return monitor;
}
}
extern "C" JNIEXPORT jstring JNICALL Java_org_saildroid_host_HostApi_audioSnapshot(JNIEnv*e,jclass){
 try{std::string json=audio_monitor().snapshot();return e->NewStringUTF(json.c_str());}
 catch(const std::exception&x){e->ThrowNew(e->FindClass("java/lang/IllegalStateException"),x.what());return nullptr;}
}
extern "C" JNIEXPORT jlong JNICALL Java_org_saildroid_host_HostApi_awaitAudioRouteChange(JNIEnv*e,jclass,jlong known,jlong timeout_ms){
 try{return static_cast<jlong>(audio_monitor().await_change(static_cast<uint64_t>(known),timeout_ms));}
 catch(const std::exception&x){e->ThrowNew(e->FindClass("java/lang/IllegalStateException"),x.what());return known;}
}
extern "C" JNIEXPORT jint JNICALL Java_org_saildroid_host_HostApi_ringerMode(JNIEnv*e,jclass){
 GError*error=nullptr;auto bus=g_bus_get_sync(G_BUS_TYPE_SESSION,nullptr,&error);
 if(!bus){g_clear_error(&error);e->ThrowNew(e->FindClass("java/lang/IllegalStateException"),"Profile service bus unavailable");return 0;}
 auto result=g_dbus_connection_call_sync(bus,"com.nokia.profiled","/com/nokia/profiled","com.nokia.profiled","get_profile",nullptr,G_VARIANT_TYPE("(s)"),G_DBUS_CALL_FLAGS_NONE,1500,nullptr,&error);g_object_unref(bus);
 if(!result){g_clear_error(&error);e->ThrowNew(e->FindClass("java/lang/IllegalStateException"),"Host ringing profile unavailable");return 0;}
 const char*profile=nullptr;g_variant_get(result,"(&s)",&profile);int mode=!strcmp(profile,"silent")?0:2;g_variant_unref(result);return mode;
}
static jint connection_state(JNIEnv *env, jclass, jint device, jstring address) {
  const char *chars = address ? env->GetStringUTFChars(address, nullptr) : nullptr;
  if (address && !chars) return 0;
  std::string requested = chars ? chars : "";
  if (chars) env->ReleaseStringUTFChars(address, chars);
  try {
    auto rows = audio_monitor().connections();
    int state = 0;
    for (const auto &row : rows) {
      if (sd_audio_connection::device_matches(uint32_t(device), row.device)
          && sd_audio_connection::address_matches(requested, row.address)) {
        state = 1;
        break;
      }
    }
    fprintf(stderr, "SDAUDIO=device_connection|device=%u|state=%d|source=pulseaudio-ports\n",
            uint32_t(device), state);
    return state;
  } catch (const std::exception &failure) {
    fprintf(stderr, "SDAUDIO=device_connection_unavailable|reason=%s\n", failure.what());
    return 0;
  }
}

static jclass audio_class;
static jmethodID ports_method, patches_method, stream_method, mic_method, primary_rate_method, primary_frames_method, events_method;
static jint ports(JNIEnv*e,jclass,jobject list,jintArray gen){
 if(!ports_method)ports_method=e->GetStaticMethodID(audio_class,"listPorts","(Ljava/util/ArrayList;[I)I");
 return e->CallStaticIntMethod(audio_class,ports_method,list,gen);
}
static jint patches(JNIEnv*e,jclass,jobject list,jintArray gen){
 if(!patches_method)patches_method=e->GetStaticMethodID(audio_class,"listPatches","(Ljava/util/ArrayList;[I)I");
 return e->CallStaticIntMethod(audio_class,patches_method,list,gen);
}
static jint fcc(JNIEnv*,jclass){return 8;}
static jboolean stream(JNIEnv*e,jclass,jint id,jint ms){
 if(!stream_method)stream_method=e->GetStaticMethodID(audio_class,"streamActive","(II)Z");
 return e->CallStaticBooleanMethod(audio_class,stream_method,id,ms);
}
static jboolean mic(JNIEnv*e,jclass){
 if(!mic_method)mic_method=e->GetStaticMethodID(audio_class,"microphoneMuted","()Z");
 return e->CallStaticBooleanMethod(audio_class,mic_method);
}
static jint primary_rate(JNIEnv*env,jclass){
 if(!primary_rate_method)primary_rate_method=env->GetStaticMethodID(audio_class,"primaryOutputSamplingRate","()I");
 return env->CallStaticIntMethod(audio_class,primary_rate_method);
}
static jint primary_frames(JNIEnv*env,jclass){
 if(!primary_frames_method)primary_frames_method=env->GetStaticMethodID(audio_class,"primaryOutputFrameCount","()I");
 return env->CallStaticIntMethod(audio_class,primary_frames_method);
}
static void events(JNIEnv*e,jobject,jobject ref){
 if(!events_method)events_method=e->GetStaticMethodID(audio_class,"setupEvents","(Ljava/lang/Object;)V");
 e->CallStaticVoidMethod(audio_class,events_method,ref);
}
static void finalize_events(JNIEnv*,jobject){} // weak-owner polling has no native allocation
extern "C" JNIEXPORT void JNICALL Java_SdAudio_nativeInstall(JNIEnv*e,jclass c,jclass channel_owner){
 audio_class=(jclass)e->NewGlobalRef(c);
 ports_method=patches_method=stream_method=mic_method=primary_rate_method=primary_frames_method=events_method=nullptr;
 JNINativeMethod channels[]={{(char*)"native_get_FCC_8",(char*)"()I",(void*)fcc}};
 if(e->RegisterNatives(channel_owner,channels,1)<0)return;
 jclass audio_system=e->FindClass("android/media/AudioSystem");
 if(!audio_system)return;
 JNINativeMethod system[]={
  {(char*)"getDeviceConnectionState",(char*)"(ILjava/lang/String;)I",(void*)connection_state},
  {(char*)"getPrimaryOutputSamplingRate",(char*)"()I",(void*)primary_rate},
  {(char*)"getPrimaryOutputFrameCount",(char*)"()I",(void*)primary_frames},
  {(char*)"listAudioPorts",(char*)"(Ljava/util/ArrayList;[I)I",(void*)ports},
  {(char*)"listAudioPatches",(char*)"(Ljava/util/ArrayList;[I)I",(void*)patches},
  {(char*)"isStreamActive",(char*)"(II)Z",(void*)stream},
  {(char*)"isMicrophoneMuted",(char*)"()Z",(void*)mic}};
 if(e->RegisterNatives(audio_system,system,sizeof(system)/sizeof(system[0]))<0)return;
 JNINativeMethod handler[]={{(char*)"native_setup",(char*)"(Ljava/lang/Object;)V",(void*)events},{(char*)"native_finalize",(char*)"()V",(void*)finalize_events}};
 e->RegisterNatives(e->FindClass("android/media/AudioPortEventHandler"),handler,2);
}
