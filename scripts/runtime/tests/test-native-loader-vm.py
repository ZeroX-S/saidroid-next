#!/usr/bin/env python3
"""Test the production loader's API28/glibc vs Android dispatch in an isolated VM.

The guest linker and ART DSOs are stand-ins, not Android/JNI acceptance tests.
Wrap only the API28 marker lookup; never modify the VM's /system or a phone.
"""
from pathlib import Path
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[3]
GUEST = r'''
#include <stddef.h>
static int calls;
void *bionic_dlopen(const char *name,int flags){(void)name;(void)flags;++calls;return (void *)0x1234;}
const char *bionic_dlerror(void){return NULL;}
int bionic_add_library_path(const char *path){(void)path;return 0;}
int guest_calls(void){return calls;}
'''
TEST = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void *bionic_dlopen(const char *,int);
const char *bionic_dlerror(void);
void *bionic_android_dlopen_ext(const char *,int,const void *);
static int api28;
int __real_access(const char *,int);
int __wrap_access(const char *path,int flags){
    if(!strcmp(path,"/system/etc/ld.config.28.txt"))return api28?0:-1;
    return __real_access(path,flags);
}
int main(int argc,char **argv){
    assert(argc==3);api28=atoi(argv[2]);
    void *guest=NULL;int (*calls)(void)=NULL;
    if(api28!=2){guest=dlopen(argv[1],RTLD_NOW|RTLD_GLOBAL);assert(guest);calls=dlsym(guest,"guest_calls");assert(calls);}
    else{
        api28=0;errno=0;assert(!bionic_dlopen("libordinary.so",RTLD_NOW));assert(errno==ENOSYS);
        assert(strstr(bionic_dlerror(),"Android linker unavailable"));assert(!bionic_dlerror());
        puts("NATIVE_LOADER=passed|missing_guest_fails_closed");return 0;
    }
    char path[4096],directory[4096];strcpy(directory,argv[1]);*strrchr(directory,'/')=0;
    const char *names[]={"libjavacore.so","libopenjdk.so","libopenjdkjvm.so","libopenjdkjvmti.so"};
    for(int i=0;i<4;++i){
        assert(snprintf(path,sizeof(path),"%s/%s",directory,names[i])<(int)sizeof(path));
        int before=calls();void *handle=bionic_dlopen(path,RTLD_NOW|RTLD_LOCAL);assert(handle);
        if(api28){int (*marker)(void)=dlsym(handle,"art_marker");assert(marker&&marker()==42);assert(calls()==before);assert(!dlclose(handle));}
        else{assert(handle==(void *)0x1234&&calls()==before+1);}
    }
    if(api28){
        assert(!bionic_dlopen("/missing/libjavacore.so",RTLD_NOW));
        assert(strstr(bionic_dlerror(),"glibc loader:"));assert(!bionic_dlerror());
    }
    int before=calls();assert(bionic_dlopen("libordinary.so",RTLD_NOW)==(void *)0x1234);assert(calls()==before+1);
    assert(bionic_dlopen(NULL,RTLD_NOW)==(void *)0x1234);
    assert(bionic_android_dlopen_ext("libjavacore.so",RTLD_NOW,NULL)==(void *)0x1234);
    struct {uint64_t flags;void *reserved;size_t size;int relro;int fd;int64_t offset;void *ns;} info={.flags=1};
    errno=0;assert(!bionic_android_dlopen_ext("/tmp/x.so",RTLD_NOW,&info));assert(errno==ENOTSUP);
    assert(strstr(bionic_dlerror(),"only zero-offset"));assert(!bionic_dlerror());
    printf("NATIVE_LOADER=passed|api28=%d|four_art_libraries|ordinary_guest|ext_guest|errors\n",api28);
}
'''

with tempfile.TemporaryDirectory(prefix='sd-native-loader-') as d:
    root = Path(d)
    (root/'guest.c').write_text(GUEST)
    (root/'art.c').write_text('int art_marker(void){return 42;}\n')
    (root/'test.c').write_text(TEST)
    for name, source in [('libdl_bio.so.0', 'guest.c')]+[(n, 'art.c') for n in
            ['libjavacore.so', 'libopenjdk.so', 'libopenjdkjvm.so', 'libopenjdkjvmti.so']]:
        subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', '-Wl,-soname,'+name,
                        str(root/source), '-o', str(root/name)], check=True)
    subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    str(repo/'native/compat/runtime-native-loader.c'), str(root/'test.c'),
                    '-Wl,--wrap=access', '-ldl', '-pthread', '-o', str(root/'test')], check=True)
    for mode in ('0', '1', '2'):
        subprocess.run([str(root/'test'), str(root/'libdl_bio.so.0'), mode], check=True)
