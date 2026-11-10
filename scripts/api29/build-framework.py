#!/usr/bin/env python3
"""Convert actual API 28/29 classes to DEX 039 with the standalone libcore.

Every class already supplied by standalone ART's libcore is excluded explicitly.
Produces separate single-DEX boot JARs and an auditable inventory. Android's
normal lambda desugaring is required: its LambdaMetafactory is compile-time-only.
"""
from pathlib import Path
import argparse,zipfile,subprocess,hashlib,json,os,struct
p=argparse.ArgumentParser();p.add_argument('inputs',type=Path);p.add_argument('core',type=Path);p.add_argument('output',type=Path);p.add_argument('--source',type=Path);p.add_argument('--api',type=int,choices=(28,29),default=29)
p.add_argument('--platform-dex',type=Path,action='append',default=[],help='Matching standard platform DEX with private paths relocated and standalone core classes excluded')
args=p.parse_args()
framework_inputs={28:('android-all-9-robolectric-4913185-2.jar','cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32'),29:('android-all-10-robolectric-5803371.jar','a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c')}
framework_name,framework_hash=framework_inputs[args.api]
source=args.source or (args.inputs/framework_name);r8=args.inputs/'r8-8.3.37.jar'
if args.source is None:
 assert hashlib.sha256(source.read_bytes()).hexdigest()==framework_hash
else:
 print('API'+str(args.api)+'_FRAMEWORK_SOURCE=patched|'+str(source)+'|sha256='+hashlib.sha256(source.read_bytes()).hexdigest(),flush=True)
assert hashlib.sha256(r8.read_bytes()).hexdigest()=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
assert not args.output.exists();args.output.mkdir(parents=True)
def classes(blob):
 def u(at):return struct.unpack_from('<I',blob,at)[0]
 def string(index):
  at=u(u(60)+4*index)
  while blob[at]&128:at+=1
  at+=1;return blob[at:blob.index(b'\0',at)].decode('utf-8')
 return {string(u(u(68)+4*u(at)))for at in range(u(100),u(100)+u(96)*32,32)}
core=set();core_files={}
for file in sorted(args.core.glob('*.jar')):
 if file.name.startswith(('framework','graphics')):continue
 with zipfile.ZipFile(file)as z:core.update(classes(z.read('classes.dex')))
 core_files[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
assert 'Ljava/lang/Object;'in core
platform_types=set()
platform_files={}
for file in args.platform_dex:
 data=file.read_bytes()
 types=classes(data)
 assert not(types&platform_types or types&core),str(file)
 platform_types.update(types)
 platform_files[str(file)]=hashlib.sha256(data).hexdigest()
included=[];excluded=[];platform_replaced=[];path_changes=[]
private_root=b'/home/art/api29-root'
def private_paths(name,data):
 # Keep Android's implementation; relocate only platform-owned file resources.
 # Do not touch system properties, version constants, class names or methods.
 count=struct.unpack_from('>H',data,8)[0];at=10;index=1;result=bytearray(data[:10])
 while index<count:
  tag=data[at];result.append(tag);at+=1
  if tag==1:
   length=struct.unpack_from('>H',data,at)[0];at+=2;value=data[at:at+length];at+=length
   if value.startswith((b'/system/fonts',b'/system/etc/fonts',b'/system/etc/font_',b'/system/usr/hyphen-data',b'/system/framework/framework-res.apk')):
    replacement=private_root+value;path_changes.append(dict(class_file=name,before=value.decode(),after=replacement.decode()));value=replacement
   result.extend(struct.pack('>H',len(value)));result.extend(value)
  else:
   lengths={3:4,4:4,5:8,6:8,7:2,8:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2};length=lengths[tag]
   result.extend(data[at:at+length]);at+=length
   if tag in (5,6):index+=1
  index+=1
 result.extend(data[at:]);return bytes(result)
with zipfile.ZipFile(source)as incoming,zipfile.ZipFile(args.output/'classes.jar','x',zipfile.ZIP_DEFLATED)as outgoing:
 for name in sorted(incoming.namelist()):
  if not name.endswith('.class'):continue
  descriptor='L'+name[:-6]+';'
  if descriptor in core:excluded.append(name);continue
  if descriptor in platform_types:platform_replaced.append(name);continue
  included.append(name);outgoing.writestr(name,private_paths(name,incoming.read(name)))
print('API'+str(args.api)+'_CLASSES=prepared|included='+str(len(included))+'|core_excluded='+str(len(excluded)),flush=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin/java'
core_classes=Path(os.environ.get('SAILDROID_CORE_CLASSES','/tmp/art-build/art-standalone/out/host/common/obj/JAVA_LIBRARIES/core-all-hostdex_intermediates/classes'))
with zipfile.ZipFile(args.output/'core-library.jar','x',zipfile.ZIP_DEFLATED)as library:
 for file in sorted(core_classes.rglob('*.class')):library.write(file,str(file.relative_to(core_classes)))
command=[str(java),'-Xmx6g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api',str(args.api),'--lib',str(args.output/'core-library.jar'),'--output',str(args.output/'multi.jar'),str(args.output/'classes.jar'),*[str(file)for file in args.platform_dex]]
with(args.output/'d8.log').open('xb')as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
written=set();files={};resources={}
with zipfile.ZipFile(source)as original_archive:
 for name in original_archive.namelist():
  if name.endswith('/')or name.endswith('.class')or name.startswith(('res/','assets/'))or name in ['resources.arsc','AndroidManifest.xml']:continue
  resources[name]=original_archive.read(name)
with zipfile.ZipFile(args.output/'multi.jar')as z:
 for n in sorted(z.namelist()):
  if not n.endswith('.dex'):continue
  data=z.read(n);assert data[:8]==b'dex\n039\0';types=classes(data);assert not(types&written or types&core);written.update(types)
  name='framework'+str(args.api)+'-'+n[:-4]+'.jar';file=args.output/name
  with zipfile.ZipFile(file,'x',zipfile.ZIP_DEFLATED)as jar:
   jar.writestr('classes.dex',data)
   if not files:
    for resource,value in resources.items():jar.writestr(resource,value)
  files[name]=dict(sha256=hashlib.sha256(file.read_bytes()).hexdigest(),classes=len(types))
original_types={'L'+n[:-6]+';'for n in included}|platform_types;assert original_types<=written
synthetics=sorted(written-original_types)
assert all('$$ExternalSynthetic'in name or '$-CC;'in name or '$$Lambda$'in name for name in synthetics),synthetics[:20]
record=dict(api=args.api,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),compiler_sha256=hashlib.sha256(r8.read_bytes()).hexdigest(),core=core_files,files=files,included=included,excluded_core=excluded,synthetics=synthetics,private_path_changes=path_changes,resources={name:hashlib.sha256(value).hexdigest()for name,value in resources.items()},platform_dex=platform_files,platform_replaced=platform_replaced)
(args.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('API'+str(args.api)+'_FRAMEWORK=compiled|classes='+str(len(written))+'|jars='+str(len(files)))
