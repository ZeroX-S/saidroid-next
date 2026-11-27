"""Private-map CFI owner/type/lifetime contracts with real loaded ELF objects.

The fixture's checker implements the public CFI dispatch protocol explicitly;
this does not claim exhaustive LLVM/Android CFI conformance.
"""
from pathlib import Path
import argparse,json,os,resource,struct,subprocess,tempfile

p=argparse.ArgumentParser();p.add_argument('linker',type=Path);a=p.parse_args()
repo=Path(__file__).resolve().parents[4];resource.setrlimit(resource.RLIMIT_CORE,(0,0))
with tempfile.TemporaryDirectory(prefix='sd-private-cfi-')as directory:
 out=Path(directory);(out/'config').mkdir()
 checked=out/'checked.c';checked.write_text(r'''
#include <stdint.h>
extern void fixture_fail(void);
static int calls;
const int marker=123;
int target(void){return 73;}
void __cfi_check(uint64_t type,void *pointer,void *diagnostic){
 if(!((type==42&&pointer==(void*)target)||(type==44&&pointer==(void*)&marker)))fixture_fail();
 if(diagnostic&&*(int*)diagnostic!=1234)fixture_fail();
 calls++;
}
int checks(void){return calls;}
''')
 unchecked=out/'unchecked.c';unchecked.write_text('extern int target(void);int unchecked_target(void){return target();}\n')
 for source,name,extra in [(checked,'checked.so',[]),(unchecked,'unchecked.so',['-Wl,--no-as-needed',str(out/'checked.so')])]:
  subprocess.run(['gcc','-shared','-fPIC','-nostdlib','-Wl,--hash-style=both','-Wl,-soname,'+name,str(source),'-o',str(out/name),*extra],check=True)
 raw=(out/'checked.so').read_bytes();phoff=struct.unpack_from('<Q',raw,32)[0];count=struct.unpack_from('<H',raw,56)[0]
 ranges=[]
 for i in range(count):
  ph=struct.unpack_from('<IIQQQQQQ',raw,phoff+i*56)
  if ph[0]==1:ranges.append((ph[3],ph[3]+ph[6]))
 gap=next(x for x in range(0,max(end for _,end in ranges),4096)if not any(start<=x<end for start,end in ranges))
 source=out/'runner.c';source.write_text(r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
extern void __cfi_slowpath(uint64_t,void*);
extern void __cfi_slowpath_diag(uint64_t,void*,void*);
void fixture_fail(void){abort();}
static int mapped(const char *name){FILE*f=fopen("/proc/self/maps","r");assert(f);char line[8192];int yes=0;while(fgets(line,sizeof(line),f))if(strstr(line,name))yes=1;fclose(f);return yes;}
int main(int argc,char **argv){
 assert(argc==5);void *linker=dlopen(argv[1],RTLD_NOW|RTLD_GLOBAL);assert(linker);
 void *(*open_guest)(const char*,int)=dlsym(linker,"bionic_dlopen");
 void *(*symbol_guest)(void*,const char*)=dlsym(linker,"bionic_dlsym");
 int(*close_guest)(void*)=dlsym(linker,"bionic_dlclose");
 int(*add_path)(const char*)=dlsym(linker,"bionic_add_library_path");
 assert(open_guest&&symbol_guest&&close_guest&&add_path&&!add_path(argv[2]));
 assert(!chdir(argv[2]));void *h=open_guest("checked.so",RTLD_NOW);assert(h);
 void *target=symbol_guest(h,"target");int(*checks)(void)=symbol_guest(h,"checks");
 assert(target&&checks&&checks()==0);
 if(!strcmp(argv[3],"wrong-type")){__cfi_slowpath(43,target);return 10;}
 if(!strcmp(argv[3],"unmapped")){__cfi_slowpath(42,(void*)1);return 10;}
 if(!strcmp(argv[3],"gap")){
  Dl_info owner={0};int(*address)(const void*,Dl_info*)=dlsym(linker,"bionic_dladdr");assert(address(target,&owner));
  __cfi_slowpath(42,(char*)owner.dli_fbase+strtoull(argv[4],NULL,0));return 10;
 }
 int token=1234;__cfi_slowpath_diag(42,target,&token);assert(checks()==1);
 if(!strcmp(argv[3],"after-close")){assert(!close_guest(h));assert(!mapped("checked.so"));__cfi_slowpath(42,target);return 10;}
 if(!strcmp(argv[3],"data-target")){
  void *marker=symbol_guest(h,"marker");assert(marker);__cfi_slowpath(44,marker);assert(checks()==2);
 }else if(!strcmp(argv[3],"unchecked-owner")){
  void *u=open_guest("unchecked.so",RTLD_NOW);assert(u);void *fn=symbol_guest(u,"unchecked_target");assert(fn);
  __cfi_slowpath(987,fn);assert(checks()==1);assert(((int(*)(void))fn)()==73);assert(!close_guest(u));
 }else if(!strcmp(argv[3],"reload")){
  for(int i=0;i<100;i++){
   assert(!close_guest(h)&&!mapped("checked.so"));h=open_guest("checked.so",RTLD_NOW);assert(h);
   target=symbol_guest(h,"target");checks=symbol_guest(h,"checks");assert(checks&&checks()==0);
   __cfi_slowpath(42,target);assert(checks()==1);
  }
 }else{
  for(int i=0;i<1000;i++)__cfi_slowpath(42,target);
  assert(checks()==1001);
 }
 assert(!close_guest(h)&&!mapped("checked.so"));puts("PRIVATE_CFI_OWNER_CONTRACT=PASS");return 0;
}
''')
 subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-rdynamic',str(source),str(repo/'native/compat/runtime-cfi.c'),'-o',str(out/'runner'),'-ldl','-pthread'],check=True)
 env=dict(os.environ,SAILDROID_STRICT_LINK='1',BIONIC_TRANSLATION_CONFIG_DIR=str(out/'config'));rows=[]
 for mode,expected in [('valid',0),('data-target',0),('unchecked-owner',0),('reload',0),('wrong-type',-6),('unmapped',-6),('gap',-6),('after-close',-6)]:
  run=subprocess.run([str(out/'runner'),str(a.linker),str(out),mode,str(gap)],env=env,capture_output=True,text=True,timeout=15)
  row=dict(mode=mode,expected=expected,exit=run.returncode,output=run.stdout.strip());rows.append(row)
  assert run.returncode==expected,dict(row,stderr=run.stderr[-3000:])
 print(json.dumps(dict(status='PASS',scope=__doc__,cases=rows),indent=2))
