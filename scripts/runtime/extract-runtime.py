#!/usr/bin/env python3
"""Extract only matching Android user-space libraries/resources from system ext4."""
from pathlib import Path
import argparse,subprocess,json,hashlib,zipfile
p=argparse.ArgumentParser();p.add_argument('image',type=Path);p.add_argument('output',type=Path);args=p.parse_args();assert not args.output.exists();args.output.mkdir(parents=True)
for remote in ['/system/lib64','/system/framework','/system/etc','/system/fonts','/system/usr','/system/apex']:
 result=subprocess.run(['debugfs','-R','rdump '+remote+' '+str(args.output),str(args.image)],capture_output=True,text=True)
 (args.output/(remote.rsplit('/',1)[1]+'-extract.log')).write_text(result.stdout+result.stderr)
 assert 'Filesystem not open'not in result.stderr and 'File not found'not in result.stderr,result.stderr
files={}
for f in args.output.rglob('*'):
 if f.is_file()and not f.is_symlink():files[str(f.relative_to(args.output))]=dict(size=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest())
assert 'lib64/libandroid_runtime.so'in files and 'framework/framework-res.apk'in files
(args.output/'extraction.json').write_text(json.dumps(dict(api=29,files=files),indent=2)+'\n')
print('API29_NATIVE=extracted|files='+str(len(files)))
for name in ['lib64/libandroid_runtime.so','lib64/libhwui.so','framework/framework-res.apk']:
 print(name,files[name])
