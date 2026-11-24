#!/usr/bin/env python3
"""Read official API 29 image into an isolated build tree. No mounts or deploy."""
from pathlib import Path
import argparse,zipfile,subprocess,json,hashlib,struct
p=argparse.ArgumentParser();p.add_argument('inputs',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
record=json.loads((args.inputs/'inputs.json').read_text());source=args.inputs/'arm64-v8a-29_r08.zip'
assert hashlib.sha256(source.read_bytes()).hexdigest()==record['assets'][source.name]['sha256']
assert not args.output.exists();args.output.mkdir(parents=True)
with zipfile.ZipFile(source)as z:
 names=[n for n in z.namelist()if n.endswith('/system.img')];assert len(names)==1
 image=args.output/'system.img'
 with z.open(names[0])as stream,image.open('wb')as dest:
  import shutil;shutil.copyfileobj(stream,dest,1024*1024)
 for name in ['arm64-v8a/build.prop','arm64-v8a/NOTICE.txt','arm64-v8a/source.properties']:
  if name in z.namelist():(args.output/Path(name).name).write_bytes(z.read(name))
with image.open('rb')as f:magic=f.read(4)
if magic==b'\x3a\xff\x26\xed':
 raw=args.output/'system.raw.img';subprocess.run(['simg2img',str(image),str(raw)],check=True);image=raw
listing=subprocess.run(['debugfs','-R','ls -l /',str(image)],capture_output=True,text=True,check=True);(args.output/'root-list.txt').write_text(listing.stdout+listing.stderr);print(listing.stdout)
print('API29_IMAGE=extracted|image='+str(image))
