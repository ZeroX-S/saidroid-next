#!/usr/bin/env python3
"""Compile a verified APK for one exact component; ART retains cache admission checks."""
from pathlib import Path
import argparse,subprocess,os,json,hashlib,time
p=argparse.ArgumentParser();p.add_argument('component',type=Path);p.add_argument('apk',type=Path);p.add_argument('device_apk_location');p.add_argument('output',type=Path);p.add_argument('--filter',choices=['quicken','speed'],default='speed');p.add_argument('--art',type=Path,default=Path('/tmp/art-build/art-standalone/out/host/linux-x86'));a=p.parse_args()
assert a.device_apk_location.startswith('/home/art/apps/') and a.device_apk_location.endswith('/base.apk') and '..' not in Path(a.device_apk_location).parts
assert not a.output.exists();a.output.mkdir();root=a.component.resolve();runtime=json.loads((root/'runtime.json').read_text());assert runtime.get('boot_image')
paths=[str(root/name)for name in runtime['boot_jars']];locations=['/home/art/api29-root/'+name for name in runtime['boot_jars']]
command=[str(a.art/'bin/dex2oat'),'--host','--instruction-set=arm64','--compiler-filter='+a.filter,'-j4','--runtime-arg','-Xmx1536m','--boot-image='+str(root/'framework/boot.art'),'--runtime-arg','-Xbootclasspath:'+':'.join(paths),'--runtime-arg','-Xbootclasspath-locations:'+':'.join(locations),'--dex-file='+str(a.apk),'--dex-location='+a.device_apk_location,'--oat-file='+str(a.output/'base.odex'),'--class-loader-context=PCL[];PCL['+str(root/'lib/runtime.jar')+']','--stored-class-loader-context=PCL[];PCL[/home/art/api29-root/lib/runtime.jar]']
env=dict(os.environ,LD_LIBRARY_PATH=str(a.art/'lib64')+':/usr/local/lib',ANDROID_ROOT=str(root),ANDROID_DATA=str(a.output/'data'));(a.output/'data').mkdir()
recipe=dict(command=command,apk_location=a.device_apk_location,apk_sha256=hashlib.sha256(a.apk.read_bytes()).hexdigest(),runtime_jar_sha256=hashlib.sha256((root/'lib/runtime.jar').read_bytes()).hexdigest(),boot_files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in runtime['boot_jars']},boot_image=runtime['boot_image'],image_files={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest()for f in (root/'framework/arm64').glob('*')if f.suffix in ['.art','.oat','.vdex']})
(a.output/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n');start=time.monotonic()
with(a.output/'build.log').open('wb')as log:subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=480,check=True)
files={name:dict(bytes=(a.output/name).stat().st_size,sha256=hashlib.sha256((a.output/name).read_bytes()).hexdigest())for name in ['base.odex','base.vdex']}
(a.output/'manifest.json').write_text(json.dumps(files,indent=2)+'\n');print('APP_DEX_CACHE=compiled|seconds='+str(round(time.monotonic()-start,3))+'|bytes='+str(sum(x['bytes']for x in files.values())))
