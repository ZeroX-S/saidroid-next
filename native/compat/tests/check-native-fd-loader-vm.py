"""Use the real private Bionic linker to validate FD-copy instance semantics."""
from pathlib import Path
import argparse,ctypes,os,subprocess,tempfile
p=argparse.ArgumentParser();p.add_argument('--linker',type=Path,default=Path('/var/tmp/saidroid-linker-unload-20261031/libdl_bio.so.0'));a=p.parse_args()
repo=Path(__file__).resolve().parents[3];linker=a.linker
class Info(ctypes.Structure):
 _fields_=[('flags',ctypes.c_uint64),('reserved_addr',ctypes.c_void_p),('reserved_size',ctypes.c_size_t),('relro_fd',ctypes.c_int),('library_fd',ctypes.c_int),('library_fd_offset',ctypes.c_int64),('namespace',ctypes.c_void_p)]
with tempfile.TemporaryDirectory(prefix='sd-native-fd-')as directory:
 root=Path(directory);cache=root/'code_cache';cache.mkdir();(root/'config').mkdir()
 os.environ['BIONIC_TRANSLATION_CONFIG_DIR']=str(root/'config');os.environ['SAILDROID_DATA_DIR']=str(root)
 fixture=root/'fixture.c';fixture.write_text('static int value;int increment(void){return ++value;}\n')
 subprocess.run(['gcc','-shared','-fPIC','-nostdlib','-Wl,--hash-style=both','-Wl,-soname,liboriginal.so','-o',str(root/'original.so'),str(fixture)],check=True)
 helper=root/'loader.so';subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-o',str(helper),str(repo/'native/compat/runtime-native-loader.c'),'-ldl','-pthread'],check=True)
 guest=ctypes.CDLL(str(linker),mode=ctypes.RTLD_GLOBAL);bridge=ctypes.CDLL(str(helper),use_errno=True)
 open_fd=bridge.bionic_android_dlopen_ext;open_fd.restype=ctypes.c_void_p;open_fd.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.POINTER(Info)]
 error=bridge.bionic_dlerror;error.restype=ctypes.c_char_p
 symbol=guest.bionic_dlsym;symbol.restype=ctypes.c_void_p;symbol.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
 close=guest.bionic_dlclose;close.argtypes=[ctypes.c_void_p];close.restype=ctypes.c_int
 fd=os.open(root/'original.so',os.O_RDONLY);os.lseek(fd,7,os.SEEK_SET);info=Info(flags=0x50,library_fd=fd)
 one=open_fd(str(cache/'virtual.so').encode(),os.RTLD_NOW,ctypes.byref(info));assert one,error()
 first=ctypes.CFUNCTYPE(ctypes.c_int)(symbol(one,b'increment'));assert first()==1 and first()==2
 two=open_fd(str(cache/'virtual.so').encode(),os.RTLD_NOW,ctypes.byref(info));assert two and two!=one,error()
 second=ctypes.CFUNCTYPE(ctypes.c_int)(symbol(two,b'increment'));assert second()==1 and first()==3
 assert os.lseek(fd,0,os.SEEK_CUR)==7,'pread must preserve caller FD position'
 assert not list(cache.iterdir()),'Temporary FD copies must already be unlinked'
 assert close(one)==0 and second()==2
 info.flags=0x10;assert not open_fd(str(cache/'virtual.so').encode(),os.RTLD_NOW,ctypes.byref(info));assert error()and not error()
 info.flags=0x50;info.library_fd_offset=1;assert not open_fd(str(cache/'virtual.so').encode(),os.RTLD_NOW,ctypes.byref(info))
 info.library_fd_offset=0;assert not open_fd(str(root/'outside.so').encode(),os.RTLD_NOW,ctypes.byref(info))
 ordinary_cache=root/'cache';ordinary_cache.mkdir()
 third=open_fd(str(ordinary_cache/'virtual.so').encode(),os.RTLD_NOW,ctypes.byref(info));assert third,error()
 third_value=ctypes.CFUNCTYPE(ctypes.c_int)(symbol(third,b'increment'));assert third_value()==1
 assert not list(ordinary_cache.iterdir()) and close(third)==0
 os.close(fd);os.unlink(root/'original.so');assert second()==3,'Mappings must survive caller closing the source FD'
 assert close(two)==0
 assert not any('.saildroid-fd-'in line for line in Path('/proc/self/maps').read_text().splitlines()),'Closing both handles must unmap the actual copies'
 print('NATIVE_FD_LOAD=PASS|independent_globals=true|fd_position_preserved=true|copies_unlinked=true|unsupported_flags_rejected=true|offset_rejected=true|escape_rejected=true|actual_unload=true|ordinary_cache_supported=true')
