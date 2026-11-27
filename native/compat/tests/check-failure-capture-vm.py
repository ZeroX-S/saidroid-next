"""Capture through a locally loaded ART signal chain without swallowing faults."""
from pathlib import Path
import os, resource, signal, subprocess, tempfile

repo=Path(__file__).resolve().parents[3]
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
with tempfile.TemporaryDirectory(prefix='sd-failure-capture-')as directory:
    root=Path(directory)
    source=root/'local-art.c'
    source.write_text(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <signal.h>
struct action {bool(*handler)(int,siginfo_t*,void*);sigset_t mask;uint64_t flags;};
static struct action handlers[64];
static void dispatch(int s,siginfo_t*i,void*c){
 assert(!handlers[s].handler(s,i,c));
 signal(s,SIG_DFL);raise(s);
}
void AddSpecialSignalHandlerFn(int s,struct action*a){
 handlers[s]=*a;struct sigaction actual={0};actual.sa_sigaction=dispatch;
 actual.sa_flags=SA_SIGINFO;sigemptyset(&actual.sa_mask);assert(!sigaction(s,&actual,0));
}
''')
    subprocess.run(['gcc','-shared','-fPIC','-Wl,-soname,libart.so','-o',str(root/'libart.so'),str(source)],check=True)
    helper=root/'capture.so'
    subprocess.run(['gcc','-shared','-fPIC','-O2','-o',str(helper),
                    str(repo/'native/compat/runtime-diagnostics.c'),'-ldl'],check=True)
    source=root/'main.c'
    source.write_text(r'''
#include <assert.h>
#include <dlfcn.h>
#include <signal.h>
int main(int argc,char**argv){
 assert(argc==3);assert(dlopen(argv[1],RTLD_NOW|RTLD_LOCAL));
 assert(!dlsym(RTLD_DEFAULT,"AddSpecialSignalHandlerFn"));
 void*h=dlopen(argv[2],RTLD_NOW|RTLD_LOCAL);assert(h);
 void(*install)(void)=dlsym(h,"sd_failure_diagnostics_install");assert(install);install();
 raise(SIGTRAP);return 99;
}
''')
    subprocess.run(['gcc','-o',str(root/'test'),str(source),'-ldl'],check=True)
    env=dict(os.environ,LD_LIBRARY_PATH=str(root))
    r=subprocess.run([str(root/'test'),str(root/'libart.so'),str(helper)],env=env,capture_output=True,timeout=5)
    assert r.returncode==-signal.SIGTRAP,(r.returncode,r.stderr[-2000:])
    assert b'SDNATIVE_DIAGNOSTICS=installed'in r.stderr
    assert b'SDNATIVE_FAILURE=begin|kind=SIGTRAP'in r.stderr
    assert b'SDNATIVE_MAPS=begin'in r.stderr and b'SDNATIVE_FAILURE=end'in r.stderr
    print('FAILURE_CAPTURE=PASS|local_art_scope_preserved|actual_signal_maps_captured|SIGTRAP_not_swallowed')
