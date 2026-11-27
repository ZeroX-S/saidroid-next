#!/usr/bin/env python3
"""Exercise actual SONAME dependency reuse and a live pool beyond 128 ELFs."""
from pathlib import Path
import argparse,os,subprocess
p=argparse.ArgumentParser()
p.add_argument('linker',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
repo=Path(__file__).resolve().parents[2]
def compile_library(source,target,*flags):
    subprocess.run(['gcc','-shared','-fPIC','-nostdlib','-Wl,--hash-style=both',str(source),'-o',str(target),*flags],check=True)
(a.output/'provided.c').write_text('int provided_value(void){return 42;}\n')
compile_library(a.output/'provided.c',a.output/'libprovided.so','-Wl,-soname,libalias.so')
(a.output/'dependent.c').write_text('extern int provided_value(void);int dependent_value(void){return provided_value();}\n')
compile_library(a.output/'dependent.c',a.output/'libdependent.so',str(a.output/'libprovided.so'))
(a.output/'property.c').write_text('extern int __system_properties_init(void);int initialize_properties(void){return __system_properties_init();}\n')
compile_library(a.output/'property.c',a.output/'libpropertyclient.so')
(a.output/'capacity.c').write_text('int capacity_value(void){return VALUE;}\n')
for i in range(140):
    compile_library(a.output/'capacity.c',a.output/('libcapacity%03d.so'%i),'-DVALUE='+str(i))
runner=a.output/'check'
subprocess.run(['gcc','-O2','-Wall','-rdynamic',str(repo/'native/compat/tests/linker-lifecycle.c'),'-o',str(runner),'-ldl'],check=True)
(a.output/'config').mkdir()
env=dict(os.environ,SAILDROID_STRICT_LINK='1',BIONIC_TRANSLATION_CONFIG_DIR=str(a.output/'config'))
r=subprocess.run([str(runner),str(a.linker.resolve()),str(a.output.resolve())],env=env,capture_output=True,text=True,timeout=15)
(a.output/'result.log').write_text(r.stdout+r.stderr)
print(r.stdout)
if r.returncode:print(r.stderr[-4000:])
r.check_returncode()
