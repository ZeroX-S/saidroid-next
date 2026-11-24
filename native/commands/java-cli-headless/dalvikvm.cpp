// Private ordinary-user ART CLI. Component selection comes only from this executable.
#include "../../host/app-filesystem-policy.hpp"
#include "../../host/third_party/json.hpp"
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <vector>
namespace fs = std::filesystem;
using Json = nlohmann::json;
static fs::path component_root;
static void trusted(const fs::path &path, bool regular) {
  auto absolute=fs::absolute(path).lexically_normal();
  auto relative=absolute.lexically_relative(component_root);
  if(relative.empty()||relative.is_absolute()||*relative.begin()=="..")
    throw std::runtime_error("Component path escapes executable root");
  struct stat owner{};
  if(lstat(component_root.c_str(),&owner)||!S_ISDIR(owner.st_mode)||owner.st_uid!=0||(owner.st_mode&022))
    throw std::runtime_error("Component root is not root-owned and immutable");
  fs::path current=component_root;
  for (const auto &part:relative) {
    current/=part; struct stat s{};
    if (lstat(current.c_str(),&s)||S_ISLNK(s.st_mode)||s.st_uid!=0||(s.st_mode&022))
      throw std::runtime_error("Component path is not root-owned and immutable");
  }
  struct stat s{};
  if (lstat(absolute.c_str(),&s)||(regular&&!S_ISREG(s.st_mode))||(!regular&&!S_ISDIR(s.st_mode)))
    throw std::runtime_error("Component path type mismatch");
}
static std::string read(const fs::path &path) {
  std::ifstream input(path); if(!input)throw std::runtime_error("Cannot read runtime metadata");
  std::ostringstream out;out<<input.rdbuf();return out.str();
}
static void environment(const char *name,const std::string &value) {
  if(setenv(name,value.c_str(),1))throw std::runtime_error("Cannot set ART environment");
}
static std::string joined(const std::vector<std::string> &v) {
  std::string out;for(const auto &s:v){if(!out.empty())out+=':';out+=s;}return out;
}
int main(int argc,char **argv) {
  try {
    if(getuid()==0||getuid()!=geteuid()||getgid()!=getegid())
      throw std::runtime_error("Java CLI requires an ordinary caller without setuid");
    auto status=read("/proc/self/status");auto cap=status.find("CapEff:\t");
    if(cap==std::string::npos||std::stoull(status.substr(cap+8),nullptr,16)!=0)
      throw std::runtime_error("Java CLI requires zero effective capabilities");
    auto self=fs::read_symlink("/proc/self/exe");
    if(self.filename()!="dalvikvm"||self.parent_path().filename()!="bin")
      throw std::runtime_error("Java CLI executable is outside its component bin");
    auto root=self.parent_path().parent_path();component_root=root;trusted(root,false);trusted(self,true);
    auto metadata=root/"runtime.json";trusted(metadata,true);
    Json runtime=Json::parse(read(metadata));
    int api=runtime.at("api").get<int>();
    if(api!=28&&api!=29)throw std::runtime_error("Java CLI requires API28/API29 metadata");
    auto executable=root/"libexec/dalvikvm-real";trusted(executable,true);
    auto art=root/"lib/libart.so";trusted(art,true);
    auto image=root/"system/framework/arm64/boot.art";trusted(image,true);
    std::vector<std::string> jars,locations;
    for(const auto &entry:runtime.at("boot_jars")) {
      auto name=entry.get<std::string>();fs::path p(name);
      if(p.is_absolute()||name.find("..")!=std::string::npos)throw std::runtime_error("Invalid boot classpath");
      trusted(root/p,true);jars.push_back((root/p).string());locations.push_back("/home/art/api29-root/"+name);
    }
    if(jars.size()!=static_cast<size_t>(api==28?13:14))throw std::runtime_error("Unexpected boot classpath");
    auto framework_runtime=root/"lib/runtime.jar";trusted(framework_runtime,true);
    jars.push_back(framework_runtime.string());locations.push_back("/home/art/api29-root/lib/runtime.jar");
    trusted(root/"lib/libsdbridge.so",true);trusted(root/"android-libs",false);
    trusted(root/"android-libs/libandroid_runtime.so",true);
    auto cli_boot=root/"lib/java-cli-bootstrap.jar";trusted(cli_boot,true);
    jars.push_back(cli_boot.string());locations.push_back(cli_boot.string());
    auto image_alias=root/"system/framework/boot.art";
    // ART inserts its ISA directory into this logical basename. The base name
    // need not exist; its verified arm64/boot.art backing file must exist.
    if((fs::exists(image_alias)||fs::is_symlink(image_alias))&&fs::canonical(image_alias)!=image)
      throw std::runtime_error("Boot image alias differs from its component");
    // Keep the same ordinary-user filesystem restriction in descendants.
    if(!sd_install_app_filesystem_policy())throw std::runtime_error("Cannot preserve application filesystem policy");
    if(argc==1){std::fputs("Usage: dalvikvm [ART options] [-cp classpath] class [arguments...]\n",stderr);return 2;}
    bool need_classpath=false,in_options=true;int class_index=argc;
    std::string user_native_path;std::vector<bool> consumed(argc,false);
    for(int i=1;i<argc&&in_options;i++) {
      std::string s(argv[i]);
      if(need_classpath){need_classpath=false;continue;}
      if(s.empty()||s[0]!='-'){class_index=i;in_options=false;break;}
      if(s=="-cp"||s=="-classpath"){need_classpath=true;continue;}
      if(s.rfind("-Dsaidroid.",0)==0)throw std::runtime_error("Component runtime and native policy options cannot be overridden");
      if(s.rfind("-Djava.library.path=",0)==0){user_native_path=s.substr(20);consumed[i]=true;continue;}
      if(s.rfind("-XXlib",0)==0||s.rfind("-Ximage",0)==0||s.rfind("-Xbootclasspath",0)==0||
         s.rfind("-Xtarget-sdk-version",0)==0||s.rfind("-Xhidden-api",0)==0||s.rfind("-Xplugin",0)==0||
         s.rfind("-agent",0)==0||s.rfind("-Xrun",0)==0||s=="-Xcompiler-option"||s=="-Ximage-compiler-option")
        throw std::runtime_error("Component runtime and native policy options cannot be overridden");
    }
    if(need_classpath)throw std::runtime_error("Classpath option needs a value");
    environment("ANDROID_ROOT",root.string());
    environment("ANDROID_RUNTIME_ROOT",(root/"apex/com.android.runtime.debug").string());
    environment("ANDROID_TZDATA_ROOT",(root/"apex/com.android.tzdata").string());
    environment("ICU_DATA",(root/"usr/icu").string());
    environment("SD_BUILD_PROP",(root/"build.prop").string());
    environment("BIONIC_TRANSLATION_CONFIG_DIR",(root/"linker-config").string());
    environment("LD_LIBRARY_PATH",(root/"lib").string()+":/home/art/lib");
    std::vector<std::string> preload;
    for(const auto &name:{"libsdmath-precision.so","libsdstrictmath-fdlibm.so","libsdcharacter-icu63.so","libsdhost29.so","libdl_bio.so.0"}) {
      auto p=root/"lib"/name;trusted(p,true);preload.push_back(p.string());
    }
    preload.push_back("libresolv.so.2");environment("LD_PRELOAD",joined(preload));
    // exec preserves the caller's UID, open stdio pipes, cwd, data directory and
    // inherited no-new-privileges/seccomp; it does not acquire a manager lease/UI.
    std::vector<std::string> args={executable.string(),"-XXlib:"+art.string(),"-Xnoimage-dex2oat",
      "-Ximage:"+image_alias.string(),"-Xbootclasspath:"+joined(jars),"-Xbootclasspath-locations:"+joined(locations),
      "-Xtarget-sdk-version:"+std::to_string(api),"-Xhidden-api-policy:enabled","-Djava.library.path="+(root/"lib").string()+":"+(root/"android-libs").string()+":/home/art/lib"+(user_native_path.empty()?"":":"+user_native_path),
      "-Dsaidroid.framework.api="+std::to_string(api),
      "-Dsaidroid.bridge.library="+(root/"lib/libsdbridge.so").string(),
      "-Dsaidroid.native.runtime="+(root/"android-libs").string()};
    for(int i=1;i<class_index;i++){
      if(!consumed[i])args.emplace_back(argv[i]);
    }
    if(class_index<argc){
      args.emplace_back("SdJavaCommand");
      for(int i=class_index;i<argc;i++)args.emplace_back(argv[i]);
    }
    std::vector<char*> raw;for(auto &s:args)raw.push_back(s.data());raw.push_back(nullptr);
    execv(executable.c_str(),raw.data());throw std::runtime_error("Cannot execute component ART");
  }catch(const std::exception &e){std::fprintf(stderr,"SD_JAVA_CLI=failed|%s\n",e.what());return 125;}
}
