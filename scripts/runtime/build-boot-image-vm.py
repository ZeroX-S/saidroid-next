#!/usr/bin/env python3
"""Build a core boot image against exact component DEX bytes inside the build VM."""
from pathlib import Path
import argparse,subprocess,os,json,time,hashlib
p=argparse.ArgumentParser();p.add_argument('component',type=Path);p.add_argument('output',type=Path);p.add_argument('--art',type=Path,default=Path('/tmp/art-build/art-standalone/out/host/linux-x86'));a=p.parse_args()
assert not a.output.exists();a.output.mkdir();(a.output/'arm64').mkdir();(a.output/'data').mkdir()
runtime=json.loads((a.component/'runtime.json').read_text());core=[name for name in runtime['boot_jars'] if '/framework29-' not in name]
assert runtime['boot_jars'][:len(core)]==core,'A boot image must be a boot-classpath prefix'
paths=[str((a.component/name).resolve())for name in core];locations=['/home/art/api29-root/'+name for name in core]
empty=a.output/'image-classes.txt';empty.write_text('')
command=[str(a.art/'bin/dex2oat'),'--host','--instruction-set=arm64','--base=0x70000000','--compiler-filter=speed','-j4','--image='+str(a.output/'arm64/boot.art'),'--oat-file='+str(a.output/'arm64/boot.oat'),'--image-classes='+str(empty),'--runtime-arg','-Xbootclasspath:'+':'.join(paths),'--runtime-arg','-Xbootclasspath-locations:'+':'.join(locations)]
for source,location in zip(paths,locations):command+=['--dex-file='+source,'--dex-location='+location]
env=dict(os.environ,LD_LIBRARY_PATH=str(a.art/'lib64')+':/usr/local/lib',ANDROID_ROOT=str(a.art),ANDROID_DATA=str(a.output/'data'))
recipe=dict(command=command,files={name:hashlib.sha256(Path(name).read_bytes()).hexdigest()for name in paths},compiler_sha256=hashlib.sha256((a.art/'bin/dex2oat').read_bytes()).hexdigest())
(a.output/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n');start=time.monotonic()
with(a.output/'build.log').open('wb')as log:subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240,check=True)
files={str(f.relative_to(a.output)):hashlib.sha256(f.read_bytes()).hexdigest()for f in(a.output/'arm64').iterdir()if f.is_file()}
(a.output/'manifest.json').write_text(json.dumps(files,indent=2)+'\n');print('ART_BOOT_IMAGE=compiled|files='+str(len(files))+'|seconds='+str(round(time.monotonic()-start,3)))
