#pragma once
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <string>

namespace sd_audio_connection {
inline std::string lower(std::string s) {
  std::transform(s.begin(),s.end(),s.begin(),[](unsigned char c){return std::tolower(c);});
  return s;
}
inline bool contains(const std::string&s,const char*p){return s.find(p)!=std::string::npos;}
// PulseAudio UCM/ALSA and Sailfish droid route names describe physical ports.
// Do not infer a connection from a localized description or a playing stream.
inline uint32_t port_device(std::string name,bool input) {
  name=lower(name);
  if(contains(name,"parking")||contains(name,"null"))return 0;
  if(contains(name,"sco"))return input?0x80000008u:0x10u;
  if(contains(name,"a2dp"))return input?0x80020000u:0x80u;
  if(contains(name,"usb_device"))return input?0x80001000u:0x4000u;
  if(contains(name,"headset"))return input?0x80000010u:4u;
  if(contains(name,"headphone"))return input?0u:8u;
  if(contains(name,"earpiece"))return input?0u:1u;
  if(contains(name,"speaker"))return input?0u:2u;
  if(contains(name,"hdmi")||contains(name,"displayport"))return input?0u:0x400u;
  if(input&&(contains(name,"builtin")||contains(name,"internal")||contains(name,"primary")))return 0x80000004u;
  return 0;
}
inline bool present(int available,bool active) {
  // PA_PORT_AVAILABLE_UNKNOWN is not proof of an unplugged physical port.
  // An actually selected port supplies positive evidence in that case.
  return available==2||(available==0&&active);
}
inline std::string address_key(std::string s) {
  s=lower(s);s.erase(std::remove_if(s.begin(),s.end(),[](unsigned char c){return !std::isalnum(c);}),s.end());return s;
}
inline bool address_matches(const std::string&requested,const std::string&actual) {
  return requested.empty()||(!actual.empty()&&address_key(requested)==address_key(actual));
}
inline uint32_t endpoint_device(std::string api,std::string protocol,std::string profile,bool input) {
  api=lower(api);protocol=lower(protocol);profile=lower(profile);
  if(api=="bluez"||api=="bluez5") {
    bool sco=contains(protocol,"sco")||contains(protocol,"headset")||contains(protocol,"handsfree")||contains(profile,"headset")||contains(profile,"handsfree")||contains(profile,"hsp")||contains(profile,"hfp");
    if(sco)return input?0x80000008u:0x10u;
    if(contains(protocol,"a2dp")||contains(profile,"a2dp"))return input?0x80020000u:0x80u;
  }
  if(api=="usb")return input?0x80001000u:0x4000u;
  return 0;
}
inline bool device_matches(uint32_t requested,uint32_t actual) {
  // The three SCO/A2DP output values are Android endpoint subtypes.
  if(actual==0x10u&&(requested==0x10u||requested==0x20u||requested==0x40u))return true;
  if(actual==0x80u&&(requested==0x80u||requested==0x100u||requested==0x200u))return true;
  return requested!=0&&requested==actual;
}
}
