#!/usr/bin/env python3
"""Prepare a VM-only private Android 10 resource tree. Does not install to phone."""
from pathlib import Path
import argparse,zipfile,shutil,hashlib,json,os
p=argparse.ArgumentParser();p.add_argument('inputs',type=Path);p.add_argument('native',type=Path);p.add_argument('root',type=Path);args=p.parse_args()
assert not args.root.exists();args.root.mkdir(parents=True)
source=args.inputs/'android-all-10-robolectric-5803371.jar';assert hashlib.sha256(source.read_bytes()).hexdigest()=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'
(args.root/'system').mkdir();(args.root/'system/framework').mkdir()
for name in ['fonts','etc','usr']:(args.root/'system'/name).symlink_to(args.native/name,target_is_directory=True)
(args.root/'apex').symlink_to(args.native/'apex',target_is_directory=True)
(args.root/'framework').symlink_to('system/framework',target_is_directory=True)
for name in ['fonts','etc']:(args.root/name).symlink_to('system/'+name,target_is_directory=True)
(args.root/'usr/icu').mkdir(parents=True)
for directory in [Path('/home/art/usr/icu'),args.native/'apex/com.android.runtime.debug/etc/icu']:
 for file in directory.glob('*.dat'):
  target=args.root/'usr/icu'/file.name
  assert not target.exists();target.symlink_to(file)
apk=args.root/'system/framework/framework-res.apk';files={}
with zipfile.ZipFile(source)as incoming,zipfile.ZipFile(apk,'x',zipfile.ZIP_DEFLATED)as outgoing:
 for name in incoming.namelist():
  if name.endswith('/'):continue
  if name in ['resources.arsc','AndroidManifest.xml']or name.startswith(('res/','assets/')):
   data=incoming.read(name);outgoing.writestr(name,data);files[name]=hashlib.sha256(data).hexdigest()
 assert 'AndroidManifest.xml'in files and 'resources.arsc'in files
(args.root/'resources.json').write_text(json.dumps(dict(api=29,sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),entries=files),indent=2)+'\n')
print('API29_ROOT=prepared|resource_entries='+str(len(files))+'|framework_apk_sha256='+hashlib.sha256(apk.read_bytes()).hexdigest())
