#!/usr/bin/env python3
"""Host contract tests; actual Android compilation is a separate device gate."""
from pathlib import Path
import ctypes,os,subprocess,tempfile,time
repo=Path(__file__).resolve().parents[4]
with tempfile.TemporaryDirectory(prefix='sd-rs-tools-contract-') as directory:
 root=Path(directory);(root/'rs/bin').mkdir(parents=True);(root/'rs/lib').mkdir()
 helper=root/'bridge.so'
 subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror','-DSD_RS_TIMEOUT_MS=200','-o',str(helper),str(repo/'native/compat/runtime-renderscript.c')],check=True)
 fixture=root/'linker.c'
 fixture.write_text(r'''
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv){
 if(getenv("LD_PRELOAD"))return 80;
 if(argc!=7||argv[1][0]!='/'||strcmp(argv[2],"-bclib"))return 81;
 char expected[4096];const char *root=getenv("ANDROID_ROOT");
 if(!root)return 82;
 strcpy(expected,root);strcat(expected,"/rs/lib");if(strcmp(getenv("LD_LIBRARY_PATH"),expected))return 83;
 strcpy(expected,root);strcat(expected,"/rs/lib/libclcore.bc");if(strcmp(argv[3],expected))return 84;
 strcpy(expected,"--library-path=");strcat(expected,root);strcat(expected,"/rs/lib");if(strcmp(argv[4],expected))return 85;
 if(strcmp(argv[5],"marker"))return 86;
 if(!strcmp(argv[6],"fail"))return 7;
 if(!strcmp(argv[6],"timeout")){sleep(3);return 9;}
 return 0;
}
''')
 subprocess.run(['gcc','-O2','-Wall','-Werror','-include','stdio.h','-o',str(root/'rs/bin/linker64'),str(fixture)],check=True)
 fn=getattr(ctypes.CDLL(str(helper),use_errno=True),'bionic__ZN7android12renderscript17rsuExecuteCommandEPKciPKS2_')
 fn.restype=ctypes.c_bool;fn.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.POINTER(ctypes.c_char_p)]
 os.environ['ANDROID_ROOT']=str(root)
 # Inherited preload must be removed from the compiler's explicit environment.
 os.environ['LD_PRELOAD']='/definitely-not-a-compiler-library.so'
 def call(tool,values):
  args=(ctypes.c_char_p*(len(values)+1))(*[v.encode()for v in values],None)
  return fn(tool.encode(),len(values),args)
 good=['/system/bin/bcc','-bclib','/system/lib64/libclcore.bc','--library-path=/system/lib64','marker','success']
 assert call('/system/bin/bcc',good),'Mapped compiler argv and sanitized environment must succeed'
 failed=good[:-1]+['fail'];assert not call('/system/bin/bcc',failed),'Real nonzero compiler exit must fail'
 assert not call('/bin/sh',['/bin/sh','-c','exit 0']),'Unrecognized executables must be rejected'
 assert not call('/system/bin/bcc',['/system/bin/ld.mc']),'argv[0] mismatch must fail'
 start=time.monotonic();assert not call('/system/bin/bcc',good[:-1]+['timeout']);assert time.monotonic()-start<1,'Compiler timeout must terminate and reap the child'
 assert not call('/system/bin/bcc',good[:2]+['/system/lib64/../../etc/passwd']+good[3:]),'Path traversal must be rejected'
 print('RS_TOOL_COMMAND_CONTRACT=PASS|checks=6|real-Android-compiler=separate-device-gate')
