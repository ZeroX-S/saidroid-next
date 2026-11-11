#include "host-common.hpp"
#include <jni.h>
#include <pulse/pulseaudio.h>
#include <chrono>
#include <thread>
#include "../../scripts/api29/audio-connection-compat/source/audio-connection.hpp"

namespace {
struct Query {
  pa_mainloop *loop = pa_mainloop_new();
  pa_context *context = nullptr;
  Json result={{"outputs",Json::array()},{"inputs",Json::array()}};
  std::string default_sink,default_source;
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
  Query(){
    if(!loop)throw std::runtime_error("PulseAudio mainloop allocation failed");
    context=pa_context_new(pa_mainloop_get_api(loop),"SailDroid audio queries");
    if(!context||pa_context_connect(context,nullptr,PA_CONTEXT_NOAUTOSPAWN,nullptr)<0)throw std::runtime_error("Host audio server unavailable");
    auto end=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    while(pa_context_get_state(context)!=PA_CONTEXT_READY){
      auto state=pa_context_get_state(context);
      if(!PA_CONTEXT_IS_GOOD(state)||std::chrono::steady_clock::now()>end)throw std::runtime_error("Host audio connection deadline");
      pa_mainloop_iterate(loop,0,nullptr);std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
  }
  ~Query(){if(context){pa_context_disconnect(context);pa_context_unref(context);}if(loop)pa_mainloop_free(loop);}
  void wait(pa_operation *op){
    if(!op)throw std::runtime_error("Host audio operation unavailable");
    auto end=std::chrono::steady_clock::now()+std::chrono::seconds(2);
    while(pa_operation_get_state(op)==PA_OPERATION_RUNNING){
      pa_mainloop_iterate(loop,0,nullptr);
      if(std::chrono::steady_clock::now()>end){pa_operation_cancel(op);pa_operation_unref(op);throw std::runtime_error("Host audio query deadline");}
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    pa_operation_unref(op);
  }
};
void server(pa_context*,const pa_server_info *info,void *data){auto&q=*(Query*)data;if(info){q.default_sink=info->default_sink_name?info->default_sink_name:"";q.default_source=info->default_source_name?info->default_source_name:"";}}
std::string property(pa_proplist *properties,const char *name){
  const char *value=properties?pa_proplist_gets(properties,name):nullptr;
  return value?value:"";
}
void sink(pa_context*,const pa_sink_info *info,int end,void *data){
  if(end||!info)return;
  auto &query=*static_cast<Query*>(data);
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
void source(pa_context*,const pa_source_info *i,int end,void *data){if(end||!i||i->monitor_of_sink!=PA_INVALID_INDEX)return;auto&q=*(Query*)data;Json row={{"id",i->index},{"name",i->name?i->name:""},{"description",i->description?i->description:""},{"rate",i->sample_spec.rate},{"channels",i->sample_spec.channels},{"muted",bool(i->mute)},{"active",i->state==PA_SOURCE_RUNNING},{"default",q.default_source==(i->name?i->name:"")},{"physical",bool(i->flags&PA_SOURCE_HARDWARE)}};q.result["inputs"].push_back(row);}
void connection_sink(pa_context *, const pa_sink_info *info, int end, void *data) {
  if (end || !info) return;
  auto &query = *static_cast<Query *>(data);
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
  auto &query = *static_cast<Query *>(data);
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
  auto &query = *static_cast<Query *>(data);
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
}
extern "C" JNIEXPORT jstring JNICALL Java_org_saildroid_host_HostApi_audioSnapshot(JNIEnv*e,jclass){
 try{Query q;q.wait(pa_context_get_server_info(q.context,server,&q));q.wait(pa_context_get_sink_info_list(q.context,sink,&q));q.wait(pa_context_get_source_info_list(q.context,source,&q));return e->NewStringUTF(q.result.dump().c_str());}
 catch(const std::exception&x){e->ThrowNew(e->FindClass("java/lang/IllegalStateException"),x.what());return nullptr;}
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
    Query query;
    query.wait(pa_context_get_card_info_list(query.context, connection_card, &query));
    query.wait(pa_context_get_sink_info_list(query.context, connection_sink, &query));
    query.wait(pa_context_get_source_info_list(query.context, connection_source, &query));
    int state = 0;
    for (const auto &row : query.connections) {
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
static jint ports(JNIEnv*e,jclass,jobject list,jintArray gen){return e->CallStaticIntMethod(audio_class,e->GetStaticMethodID(audio_class,"listPorts","(Ljava/util/ArrayList;[I)I"),list,gen);}
static jint patches(JNIEnv*e,jclass,jobject list,jintArray gen){return e->CallStaticIntMethod(audio_class,e->GetStaticMethodID(audio_class,"listPatches","(Ljava/util/ArrayList;[I)I"),list,gen);}
static jint fcc(JNIEnv*,jclass){return 8;}
static jboolean stream(JNIEnv*e,jclass,jint id,jint ms){return e->CallStaticBooleanMethod(audio_class,e->GetStaticMethodID(audio_class,"streamActive","(II)Z"),id,ms);}
static jboolean mic(JNIEnv*e,jclass){return e->CallStaticBooleanMethod(audio_class,e->GetStaticMethodID(audio_class,"microphoneMuted","()Z"));}
static jint primary_rate(JNIEnv*env,jclass){
 jmethodID getter=env->GetStaticMethodID(audio_class,"primaryOutputSamplingRate","()I");
 return env->CallStaticIntMethod(audio_class,getter);
}
static jint primary_frames(JNIEnv*env,jclass){
 jmethodID getter=env->GetStaticMethodID(audio_class,"primaryOutputFrameCount","()I");
 return env->CallStaticIntMethod(audio_class,getter);
}
static void events(JNIEnv*e,jobject,jobject ref){e->CallStaticVoidMethod(audio_class,e->GetStaticMethodID(audio_class,"setupEvents","(Ljava/lang/Object;)V"),ref);}
static void finalize_events(JNIEnv*,jobject){} // weak-owner polling has no native allocation
extern "C" JNIEXPORT void JNICALL Java_SdAudio_nativeInstall(JNIEnv*e,jclass c,jclass channel_owner){
 audio_class=(jclass)e->NewGlobalRef(c);
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
