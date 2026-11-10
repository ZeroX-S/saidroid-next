// Android getprop-compatible reads from the component's actual existing native
// property backend. No property values or test names are special-cased.
#include <algorithm>
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
namespace fs=std::filesystem;
extern "C" int sd_import_host_product_properties(void *private_libc);
extern "C" int sd_import_host_timezone_properties(void *private_libc, char timezone[92]);
struct prop_info;
static void require(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static void trusted(const fs::path& path,bool directory){
 struct stat s{};require(lstat(path.c_str(),&s)==0&&!S_ISLNK(s.st_mode)&&s.st_uid==0&&
     !(s.st_mode&0022)&&(directory?S_ISDIR(s.st_mode):S_ISREG(s.st_mode)),
     "Untrusted component property input");
}
static void ancestors(fs::path path){
 for(;;){trusted(path,true);if(path==path.root_path())break;path=path.parent_path();}
}
struct Reader {
 int(*read)(const prop_info*,char*,char*);
 std::vector<std::pair<std::string,std::string>> rows;
 static void collect(const prop_info* info,void* cookie){
  auto*self=static_cast<Reader*>(cookie);char name[256]{},value[256]{};
  require(self->read(info,name,value)>=0,"Native property read failed");
  self->rows.emplace_back(name,value);
 }
};
int main(int argc,char**argv){try{
 require(argc<=3,"usage: getprop [NAME [DEFAULT]]; property types and writes unavailable");
 if(argc>1)require(argv[1][0]!='-',"Property type options are unavailable in this backend");
 const auto executable=fs::canonical("/proc/self/exe");
 require(executable.filename()=="getprop"&&executable.parent_path().filename()=="bin",
         "Install private getprop in its component bin directory");
 const auto root=executable.parent_path().parent_path();ancestors(root);
 const auto properties=root/"build.prop",library=root/"lib/private-getprop/libc_bio.so.0";
 trusted(properties,false);
 std::ifstream input(properties);require(input.is_open()&&input.good(),"Component build properties are unreadable");
 struct stat property_stat{};require(stat(properties.c_str(),&property_stat)==0&&property_stat.st_size>0&&property_stat.st_size<=1024*1024,"Component build property size invalid");
 input.close();ancestors(library.parent_path());trusted(library,false);
 require(setenv("ANDROID_ROOT",root.c_str(),1)==0&&setenv("SD_BUILD_PROP",properties.c_str(),1)==0,
         "Cannot select component property store");
 // Resolve the copied backend's private dependencies through the component
 // before its historical RUNPATH takes effect.
 std::vector<void*> dependency_handles;
 for(const char* name:{"libpthread_bio.so.0","libunwind.so.8"}){
  const auto dependency=root/"lib"/name;
  if(fs::exists(dependency)){
   trusted(dependency,false);
   void* loaded=dlopen(dependency.c_str(),RTLD_NOW|RTLD_LOCAL);
   require(loaded!=nullptr,dlerror());
   dependency_handles.push_back(loaded);
  }
 }
 void* handle=dlopen(library.c_str(),RTLD_NOW|RTLD_LOCAL);require(handle!=nullptr,dlerror());
 require(sd_import_host_product_properties(handle)>=0,"Host product property import failed");
 char timezone[92]{};
 require(sd_import_host_timezone_properties(handle,timezone)>=0,"Host timezone import failed");
 auto get=reinterpret_cast<int(*)(const char*,char*)>(dlsym(handle,"bionic___system_property_get"));
 auto each=reinterpret_cast<int(*)(void(*)(const prop_info*,void*),void*)>(dlsym(handle,"bionic___system_property_foreach"));
 auto read=reinterpret_cast<int(*)(const prop_info*,char*,char*)>(dlsym(handle,"bionic___system_property_read"));
 require(get&&each&&read,"Existing native property API unavailable");
 Dl_info actual{};require(dladdr(reinterpret_cast<void*>(get),&actual)&&actual.dli_fname&&
     fs::canonical(actual.dli_fname)==library,"Native property implementation owner differs");
 if(argc>1){char value[256]{};const int length=get(argv[1],value);require(length>=0&&length<256,"Native property value invalid");std::cout<<(length?value:(argc==3?argv[2]:""))<<'\n';}
 else{Reader reader{read,{}};require(each(Reader::collect,&reader)==0,"Native property enumeration failed");std::sort(reader.rows.begin(),reader.rows.end());for(const auto&row:reader.rows)std::cout<<'['<<row.first<<"]: ["<<row.second<<"]\n";}
 dlclose(handle);
 for(void* dependency:dependency_handles)dlclose(dependency);
 return 0;
 }catch(const std::exception&e){std::cerr<<"getprop: "<<e.what()<<'\n';return 1;}}
