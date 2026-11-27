"""Real private-linker dispatch to an explicitly synthetic host-loader fixture.

The fixture tests handle ownership/refcount/error routing, not Android HAL ABI.
The separate device gates must establish real hardware behavior.
"""
from pathlib import Path
import ctypes,os,subprocess,tempfile
repo=Path(__file__).resolve().parents[3]
linker=Path('/var/tmp/saidroid-linker-hardware-20261031/libdl_bio.so.0')
assert os.getuid()==0,'Trust-policy fixture must run as VM root'
with tempfile.TemporaryDirectory(prefix='sd-hardware-loader-')as directory:
 root=Path(directory);(root/'config').mkdir();os.environ['BIONIC_TRANSLATION_CONFIG_DIR']=str(root/'config')
 fixture=root/'fixture.c';fixture.write_text('static int n;int increment(void){return ++n;}')
 subprocess.run(['gcc','-shared','-fPIC',str(fixture),'-o',str(root/'fixture.so')],check=True)
 mock=root/'mock.c';mock.write_text(r'''
#define _GNU_SOURCE
#include <dlfcn.h>
void *android_dlopen(const char *n,int f){return dlopen(n,f);}
void *android_dlsym(void *h,const char *n){return dlsym(h,n);}
int android_dlclose(void *h){return dlclose(h);}
int android_dladdr(const void *a,Dl_info *i){return dladdr(a,i);}
const char *android_dlerror(void){return dlerror();}
void *android_load_sphal_library(const char *n,int f){return dlopen(n,f);}
int android_unload_sphal_library(void *h){return dlclose(h);}
''')
 common=root/'common.so';subprocess.run(['gcc','-shared','-fPIC',str(mock),'-o',str(common),'-ldl'],check=True)
 helper=root/'bridge.so';subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-DSD_HOST_LOADER_LIBRARY="'+str(common)+'"','-DSD_HOST_VNDK_LIBRARY="'+str(common)+'"',str(repo/'native/compat/runtime-hardware-loader.c'),'-o',str(helper),'-ldl','-pthread'],check=True)
 bridge=ctypes.CDLL(str(helper),mode=ctypes.RTLD_GLOBAL);guest=ctypes.CDLL(str(linker),mode=ctypes.RTLD_GLOBAL)
 load=bridge.bionic_android_load_sphal_library;load.argtypes=[ctypes.c_char_p,ctypes.c_int];load.restype=ctypes.c_void_p
 symbol=guest.bionic_dlsym;symbol.argtypes=[ctypes.c_void_p,ctypes.c_char_p];symbol.restype=ctypes.c_void_p
 close=guest.bionic_dlclose;close.argtypes=[ctypes.c_void_p];close.restype=ctypes.c_int
 foreign_close=bridge.sd_hardware_close;foreign_close.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)]
 foreign_symbol=bridge.sd_hardware_symbol;foreign_symbol.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)]
 error=bridge.sd_hardware_error;error.restype=ctypes.c_char_p
 assert not load(b'/no-such-hardware-fixture.so',os.RTLD_NOW)
 assert b'no-such-hardware-fixture.so'in error() and not error()
 one=load(str(root/'fixture.so').encode(),os.RTLD_NOW);two=load(str(root/'fixture.so').encode(),os.RTLD_NOW);assert one and two==one
 function=symbol(one,b'increment');assert function
 inc=ctypes.CFUNCTYPE(ctypes.c_int)(function);assert inc()==1 and inc()==2
 assert not symbol(one,b'not_a_real_symbol')
 assert b'not_a_real_symbol'in error() and not error()
 assert not symbol(one,None)
 assert close(one)==0 and inc()==3
 assert close(two)==0
 untouched=ctypes.c_int(37);assert foreign_close(one,ctypes.byref(untouched))==0 and untouched.value==37
 untouched_symbol=ctypes.c_void_p(91);assert foreign_symbol(one,b'increment',ctypes.byref(untouched_symbol))==0 and untouched_symbol.value==91
 assert not any(str(root/'fixture.so')in line for line in Path('/proc/self/maps').read_text().splitlines())
 print('HARDWARE_HANDLE_CONTRACT=PASS|actual_private_linker_dispatch=true|fixture_host_api=true|duplicate_references=true|missing_symbol_is_null=true|null_symbol_rejected=true|unknown_handles_not_interpreted=true|last_close_unmaps=true|hardware_hal_claim=false')
