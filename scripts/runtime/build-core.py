#!/usr/bin/env python3
"""Apply Android's normal lambda desugaring to the standalone core bytecode."""
from pathlib import Path
import argparse,subprocess,zipfile,os,json,hashlib
p=argparse.ArgumentParser();p.add_argument('inputs',type=Path);p.add_argument('output',type=Path);p.add_argument('--platform-http-runtime',type=Path,help='Matching API29 platform extraction; retain boot HTTP API types and use its declared shared implementation');p.add_argument('--api29-regex',action='store_true',help='Apply Android10 group/null/split semantics while preserving the private regex JNI ABI');p.add_argument('--api29-covariant',action='store_true',help='Add Android10 Buffer/ConcurrentHashMap compatibility methods through the normal D8 annotation transform');p.add_argument('--api29-buffer-order',action='store_true',help='Restore Android10 DoubleBuffer signed-zero comparison; requires --api29-covariant');p.add_argument('--api29-os-ioctl',action='store_true',help='Add the API29 Int32Ref ioctl carrier over the unchanged native MutableInt ABI');p.add_argument('--api29-os-sendfile',action='store_true',help='Add the API29 Int64Ref sendfile carrier over the unchanged native MutableLong ABI; requires --api29-os-ioctl');p.add_argument('--api29-socket-flags',action='store_true',help='Add API29 socket flag fields; must be packaged with matching native constant initializers');p.add_argument('--api29-atomic-access',action='store_true',help='Restore Android10 AtomicFieldUpdater caller access checks and protected-access helper');p.add_argument('--api29-bigint-random',action='store_true',help='Preserve Android10 signed word-count overflow rejection in random BigInteger construction');p.add_argument('--api29-decimal-compat',action='store_true',help='Restore Android10 ICU-compatible number formatting, complete symbols and localized pattern separators; requires --platform-icu');p.add_argument('--api29-date-format',action='store_true',help='Apply Android10 date-format parsing and pattern behavior; requires --platform-icu');p.add_argument('--api29-util-compat',action='store_true',help='Restore Android10 deep array equality and preserve requireNonNull null messages through D8');p.add_argument('--api29-zoneinfo-compat',action='store_true',help='Restore Android10 earliest non-DST offsets and signed DST savings without native field changes');p.add_argument('--api29-objectstream-compat',action='store_true',help='Restore Android10 default-SUID compatibility listener over the retained native boolean ABI');p.add_argument('--api29-stringfactory-compat',action='store_true',help='Restore Android10 UTF8 maximal-subpart decoding while retaining StringFactory native declarations');p.add_argument('--api29-runtime-load-compat',action='store_true',help='Restore the existing Android deprecated Runtime.loadLibrary target SDK guard; standard library loading unchanged');p.add_argument('--platform-icu',action='store_true',help='Replace legacy boot-owned ICU classes and resources with matching API29 bytes');args=p.parse_args();assert not args.api29_buffer_order or args.api29_covariant,'Buffer ordering overlay requires the API29 covariant source baseline';assert not args.api29_os_sendfile or args.api29_os_ioctl,'Sendfile overlay requires the API29 ioctl source baseline';assert not(args.api29_decimal_compat or args.api29_date_format)or args.platform_icu,'Android10 text adapters require --platform-icu';assert not args.output.exists();args.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin/java';r8=args.inputs/'r8-8.3.37.jar'
assert hashlib.sha256(r8.read_bytes()).hexdigest()=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
base=Path('/tmp/art-build/art-standalone/out/host/common/obj/JAVA_LIBRARIES');record={}
platform_icu={};icu_resources={}
if args.platform_icu:
 platform=args.inputs/'android-all-10-robolectric-5803371.jar'
 assert hashlib.sha256(platform.read_bytes()).hexdigest()=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'
 with zipfile.ZipFile(platform)as archive:
  for name in archive.namelist():
   if not name.startswith('android/icu/')or name.endswith('/'):continue
   (platform_icu if name.endswith('.class')else icu_resources)[name]=archive.read(name)
 assert platform_icu and icu_resources
overlay=args.output/'overlay';overlay.mkdir()
source=Path(__file__).resolve().parent/'core'
subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(overlay),*[str(f)for f in sorted(source.glob('*.java'))if not f.name.endswith('.aosp.java')and f.name!='TimeZone.java'and (args.api29_regex or f.name not in ['Matcher.java','Pattern.java'])]],check=True)
if args.platform_icu:
 # This one source calls the matching ICU63 API, not the legacy ICU58 method.
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(args.inputs/'android-all-10-robolectric-5803371.jar')+':'+str(base/'core-all-hostdex_intermediates/classes'),'-d',str(overlay),str(source/'TimeZone.java')],check=True)
covariant=None
if args.api29_covariant:
 directory=source/'covariant';covariant=json.loads((directory/'sources.json').read_text())
 expected={'java/nio/'+name+'.java'for name in ['Buffer','ByteBuffer','CharBuffer','ShortBuffer','IntBuffer','LongBuffer','FloatBuffer','DoubleBuffer']}|{'java/util/concurrent/ConcurrentHashMap.java'}
 assert set(covariant['files'])==expected
 for name,entry in covariant['files'].items():
  assert hashlib.sha256((directory/name).read_bytes()).hexdigest()==entry['sha256']
  assert hashlib.sha256((source.parents[2]/entry['baseline_source']).read_bytes()).hexdigest()==entry['baseline_sha256']
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(overlay),*[str(directory/name)for name in sorted(expected)]],check=True)
buffer_order=None
if args.api29_buffer_order:
 directory=source/'buffer-order';buffer_order=json.loads((directory/'source.json').read_text())
 assert buffer_order['source']=='java/nio/DoubleBuffer.java'
 assert buffer_order['baseline_source']=='scripts/runtime/core/covariant/java/nio/DoubleBuffer.java'
 assert hashlib.sha256((directory/buffer_order['source']).read_bytes()).hexdigest()==buffer_order['sha256']
 assert hashlib.sha256((source.parents[2]/buffer_order['baseline_source']).read_bytes()).hexdigest()==buffer_order['baseline_sha256']
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(overlay)+':'+str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(overlay),str(directory/buffer_order['source'])],check=True)
os_ioctl=None
if args.api29_os_ioctl:
 directory=source/'os-ioctl';os_ioctl=json.loads((directory/'source.json').read_text())
 assert os_ioctl['source']=='android/system/Os.java'
 assert os_ioctl['baseline_source']=='third_party/art-standalone/libcore/luni/src/main/java/android/system/Os.java'
 assert hashlib.sha256((directory/os_ioctl['source']).read_bytes()).hexdigest()==os_ioctl['sha256']
 assert hashlib.sha256((source.parents[2]/os_ioctl['baseline_source']).read_bytes()).hexdigest()==os_ioctl['baseline_sha256']
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(overlay),str(directory/os_ioctl['source'])],check=True)
os_sendfile=None
if args.api29_os_sendfile:
 directory=source/'os-sendfile';os_sendfile=json.loads((directory/'source.json').read_text())
 assert os_sendfile['source']=='android/system/Os.java'
 assert os_sendfile['baseline_source']=='scripts/runtime/core/os-ioctl/android/system/Os.java'
 assert hashlib.sha256((directory/os_sendfile['source']).read_bytes()).hexdigest()==os_sendfile['sha256']
 assert hashlib.sha256((source.parents[2]/os_sendfile['baseline_source']).read_bytes()).hexdigest()==os_sendfile['baseline_sha256']
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(overlay),str(directory/os_sendfile['source'])],check=True)
socket_flags=None
if args.api29_socket_flags:
 directory=source/'socket-flags';socket_flags=json.loads((directory/'source.json').read_text())
 assert socket_flags['source']=='android/system/OsConstants.java'
 assert socket_flags['baseline_source']=='third_party/art-standalone/libcore/luni/src/main/java/android/system/OsConstants.java'
 assert hashlib.sha256((directory/socket_flags['source']).read_bytes()).hexdigest()==socket_flags['sha256']
 assert hashlib.sha256((source.parents[2]/socket_flags['baseline_source']).read_bytes()).hexdigest()==socket_flags['baseline_sha256']
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(overlay),str(directory/socket_flags['source'])],check=True)
atomic_access=None
if args.api29_atomic_access:
 directory=source/'atomic-access';atomic_access=json.loads((directory/'sources.json').read_text())
 expected={'java/util/concurrent/atomic/'+n+'.java'for n in ['AtomicIntegerFieldUpdater','AtomicLongFieldUpdater','AtomicReferenceFieldUpdater']}|{'sun/reflect/misc/ReflectUtil.java'}
 assert set(atomic_access['files'])==expected
 for name,entry in atomic_access['files'].items():
  assert hashlib.sha256((directory/name).read_bytes()).hexdigest()==entry['sha256']
  assert hashlib.sha256((source.parents[2]/entry['baseline_source']).read_bytes()).hexdigest()==entry['baseline_sha256']
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(overlay),*[str(directory/name)for name in sorted(expected)]],check=True)
bigint_random=None
bigint_file=None
if args.api29_bigint_random:
 directory=source/'bigint-random';bigint_random=json.loads((directory/'source.json').read_text())
 assert bigint_random['source']=='java/math/BigInteger.java'
 assert bigint_random['baseline_source']=='third_party/art-standalone/libcore/ojluni/src/main/java/java/math/BigInteger.java'
 assert hashlib.sha256((directory/bigint_random['source']).read_bytes()).hexdigest()==bigint_random['sha256']
 assert hashlib.sha256((source.parents[2]/bigint_random['baseline_source']).read_bytes()).hexdigest()==bigint_random['baseline_sha256']
 compiled=args.output/'bigint-random-overlay';compiled.mkdir()
 subprocess.run([str(java.with_name('javac')),'-source','8','-target','8','-nowarn','-bootclasspath',str(base/'core-all-hostdex_intermediates/classes')+':'+str(args.inputs/'android-all-10-robolectric-5803371.jar'),'-d',str(compiled),str(directory/bigint_random['source'])],check=True)
 bigint_file=compiled/'java/math/BigInteger.class';assert bigint_file.is_file()
 # Recompilation moves nested-class line tables. Verify their instructions
 # and descriptors, then retain the original nested bytes in the output.
 for file in compiled.rglob('*.class'):
  name=file.relative_to(compiled)
  if file==bigint_file:continue
  assert str(name).startswith('java/math/BigInteger$')
  original=base/'core-oj-hostdex_intermediates/classes'/name;assert original.is_file()
  before=subprocess.run([str(java.with_name('javap')),'-p','-c','-s',str(original)],capture_output=True,text=True,check=True).stdout
  after=subprocess.run([str(java.with_name('javap')),'-p','-c','-s',str(file)],capture_output=True,text=True,check=True).stdout
  assert before==after,'Unexpected nested BigInteger behavior change: '+str(name)
from text_core_overlay import build_text_overlays
text_files,text_provenance=build_text_overlays(args.output,source,base/'core-all-hostdex_intermediates/classes',platform_icu,java,args.inputs/'android-all-10-robolectric-5803371.jar',args.api29_decimal_compat,args.api29_date_format)
from util_core_overlay import build_util_overlays
util_files,util_provenance=build_util_overlays(args.output,source,base/'core-all-hostdex_intermediates/classes',java,args.inputs/'android-all-10-robolectric-5803371.jar',args.api29_util_compat,args.api29_zoneinfo_compat)
assert not set(text_files)&set(util_files)
from objectstream_core_overlay import build_objectstream_overlay
objectstream_files,objectstream_provenance=build_objectstream_overlay(args.output,source,base/'core-all-hostdex_intermediates/classes',java,args.inputs/'android-all-10-robolectric-5803371.jar',args.api29_objectstream_compat)
assert not(set(objectstream_files)&(set(text_files)|set(util_files)))
from stringfactory_core_overlay import build_stringfactory_overlay
stringfactory_files,stringfactory_provenance=build_stringfactory_overlay(args.output,source,base/'core-all-hostdex_intermediates/classes',java,args.inputs/'android-all-10-robolectric-5803371.jar',args.api29_stringfactory_compat)
assert not(set(stringfactory_files)&(set(text_files)|set(util_files)|set(objectstream_files)))
from runtime_load_core_overlay import build_runtime_load_overlay
runtime_load_files,runtime_load_provenance=build_runtime_load_overlay(args.output,source,base/'core-all-hostdex_intermediates/classes',java,args.inputs/'android-all-10-robolectric-5803371.jar',args.api29_runtime_load_compat)
assert not(set(runtime_load_files)&(set(text_files)|set(util_files)|set(objectstream_files)|set(stringfactory_files)))
for component in ['core-oj','core-libart']:
 cls=base/(component+'-hostdex_intermediates/classes');assert cls.is_dir();jar=args.output/(component+'-classes.jar');files={}
 with zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as z:
  inputs={str(f.relative_to(cls)):f for f in cls.rglob('*.class')}
  if bigint_random and component=='core-oj':inputs['java/math/BigInteger.class']=bigint_file
  for name,file in {**text_files,**util_files,**objectstream_files,**runtime_load_files}.items():
   if name.startswith('java/')==(component=='core-oj'):
    assert name in inputs or name=='java/io/ObjectStreamClass$DefaultSUIDCompatibilityListener.class';inputs[name]=file
  if component=='core-libart':
   for name,file in stringfactory_files.items():
    assert name in inputs;inputs[name]=file
  icu_record=None
  if args.platform_icu and component=='core-libart':
   # Newer ICU-only classes already live in the matching framework JARs.
   # Replace the boot-owned overlap, without introducing duplicate types.
   old_icu={name for name in inputs if name.startswith('android/icu/')}
   assert old_icu
   for name in old_icu:del inputs[name]
   replacements={name:platform_icu[name]for name in old_icu&platform_icu.keys()}
   inputs.update(replacements)
   icu_record=dict(source_sha256=hashlib.sha256(platform.read_bytes()).hexdigest(),classes={name:hashlib.sha256(data).hexdigest()for name,data in sorted(replacements.items())},removed_legacy_types=sorted(old_icu-platform_icu.keys()),boundary='Only legacy boot-owned ICU types replaced; new API29 types remain in matching framework')
  prefixes=['java/io/FileDescriptor','java/net/Socket','java/net/SocksSocketImpl','javax/net/ssl/SSLParameters'] if component=='core-oj' else ['libcore/util/NativeAllocationRegistry','dalvik/system/BaseDexClassLoader','dalvik/system/PathClassLoader','dalvik/system/DexPathList','dalvik/system/VMRuntime','dalvik/system/VMDebug','dalvik/system/BlockGuard','libcore/io/BlockGuardOs','libcore/io/IoUtils']
  if args.platform_icu and component=='core-oj':prefixes.append('java/util/TimeZone')
  if args.api29_regex and component=='core-oj':prefixes.extend(['java/util/regex/Matcher','java/util/regex/Pattern'])
  if covariant and component=='core-oj':prefixes.extend(name[:-5]for name in covariant['files'])
  if atomic_access and component=='core-oj':prefixes.extend(name[:-5]for name in atomic_access['files'])
  if os_ioctl and component=='core-libart':prefixes.append('android/system/Os')
  if socket_flags and component=='core-libart':prefixes.append('android/system/OsConstants')
  for name in list(inputs):
   if any(name==prefix+'.class' or name.startswith(prefix+'$')for prefix in prefixes):del inputs[name]
  for f in overlay.rglob('*.class'):
   name=str(f.relative_to(overlay))
   if any(name==prefix+'.class' or name.startswith(prefix+'$')for prefix in prefixes):inputs[name]=f
  for name,f in sorted(inputs.items()):data=f if isinstance(f,bytes)else f.read_bytes();z.writestr(name,data);files[name]=hashlib.sha256(data).hexdigest()
 target=args.output/(component+'-hostdex.jar');command=[str(java),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(args.inputs/'android-all-10-robolectric-5803371.jar'),'--output',str(target),str(jar)]
 with(args.output/(component+'-d8.log')).open('xb')as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
 with zipfile.ZipFile(target)as z:assert z.namelist()==['classes.dex'] and z.read('classes.dex')[:8]==b'dex\n039\0'
 resources={}
 original=Path('/home/art/java/dex/art')/(component+'-hostdex.jar')
 with zipfile.ZipFile(original)as source_jar,zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as output_jar:
  for name in source_jar.namelist():
   if name.endswith('/')or name.endswith('.dex'):continue
   if args.platform_icu and component=='core-libart'and name.startswith('android/icu/'):continue
   data=source_jar.read(name);output_jar.writestr(name,data);resources[name]=hashlib.sha256(data).hexdigest()
  if args.platform_icu and component=='core-libart':
   for name,data in sorted(icu_resources.items()):output_jar.writestr(name,data);resources[name]=hashlib.sha256(data).hexdigest()
 record[component]=dict(classes=files,resources=resources,sha256=hashlib.sha256(target.read_bytes()).hexdigest());print('API29_CORE=desugared|component='+component+'|classes='+str(len(files))+'|resources='+str(len(resources)),flush=True)
 if icu_record:record[component]['platform_icu']=icu_record
 if args.api29_regex and component=='core-oj':record[component]['api29_regex']={name:json.loads((source/(name+'.source.json')).read_text())for name in ['Matcher','Pattern']}
 if covariant and component=='core-oj':record[component]['api29_covariant']=covariant
 if buffer_order and component=='core-oj':record[component]['api29_buffer_order']=buffer_order
 if os_ioctl and component=='core-libart':record[component]['api29_os_ioctl']=os_ioctl
 if os_sendfile and component=='core-libart':record[component]['api29_os_sendfile']=os_sendfile
 if socket_flags and component=='core-libart':record[component]['api29_socket_flags']=socket_flags
 if atomic_access and component=='core-oj':record[component]['api29_atomic_access']=atomic_access
 if bigint_random and component=='core-oj':record[component]['api29_bigint_random']=bigint_random
 if objectstream_provenance and component=='core-oj':record[component]['api29_objectstream_compat']=objectstream_provenance
 if stringfactory_provenance and component=='core-libart':record[component]['api29_stringfactory_compat']=stringfactory_provenance
 if runtime_load_provenance and component=='core-oj':record[component]['api29_runtime_load_compat']=runtime_load_provenance
 for family,provenance in util_provenance.items():
  if component==('core-oj'if family=='util-compat'else'core-libart'):record[component]['api29_'+family.replace('-','_')]=provenance
 if component=='core-oj':
  for family,provenance in text_provenance.items():record[component]['api29_'+family.replace('-','_')]=provenance
if args.platform_http_runtime:
 import struct
 def dex_types(path):
  with zipfile.ZipFile(path)as z:data=z.read('classes.dex')
  def u(offset):return struct.unpack_from('<I',data,offset)[0]
  def string(index):
   offset=u(u(60)+4*index)
   while data[offset]&128:offset+=1
   offset+=1;return data[offset:data.index(bytes([0]),offset)].decode()
  return{string(u(u(68)+4*u(offset)))for offset in range(u(100),u(100)+u(96)*32,32)}
 original=Path('/home/art/java/dex/art/apachehttp-hostdex.jar')
 shared=args.platform_http_runtime/'framework/org.apache.http.legacy.jar'
 extraction=json.loads((args.platform_http_runtime/'extraction.json').read_text())
 assert hashlib.sha256(shared.read_bytes()).hexdigest()==extraction['files']['framework/org.apache.http.legacy.jar']['sha256']
 old=dex_types(original);shared_types=dex_types(shared);retained=old-shared_types
 assert retained and all(name.startswith('Lorg/apache/http/')for name in retained)
 jar=args.output/'apachehttp-api29-boot-classes.jar';files={}
 with zipfile.ZipFile(args.inputs/'android-all-10-robolectric-5803371.jar')as platform,zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as output:
  for descriptor in sorted(retained):
   name=descriptor[1:-1]+'.class';data=platform.read(name);output.writestr(name,data);files[name]=hashlib.sha256(data).hexdigest()
 target=args.output/'apachehttp-hostdex.jar'
 command=[str(java),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(args.inputs/'android-all-10-robolectric-5803371.jar'),'--output',str(target),str(jar)]
 with(args.output/'apachehttp-d8.log').open('xb')as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
 assert dex_types(target)==retained,'Boot HTTP boundary must exactly match platform-required API types'
 record['apachehttp']=dict(classes=files,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),shared_platform_sha256=hashlib.sha256(shared.read_bytes()).hexdigest(),old_boot_types=len(old),retained_boot_types=len(retained),shared_types=len(shared_types),boundary='API29 boot HTTP API types; declared org.apache.http.legacy shared implementation')
 print('API29_HTTP=split|boot_types='+str(len(retained))+'|shared_types='+str(len(shared_types)),flush=True)
(args.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
