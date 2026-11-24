#!/usr/bin/env python3
"""Package the native host transition against an exact installed predecessor.
No device writes: the predecessor runtime.json and install-manifest.json are
read-only inputs captured from the accepted release.
"""
from pathlib import Path
import argparse,hashlib,json,re,shutil,stat,subprocess,sys,tarfile,zipfile
p=argparse.ArgumentParser();p.add_argument('predecessor',type=Path);p.add_argument('product',type=Path);p.add_argument('manager',type=Path);p.add_argument('output',type=Path);p.add_argument('--platform-runtime',type=Path);p.add_argument('--media-runtime',action='store_true');p.add_argument('--core-runtime',type=Path);p.add_argument('--framework-runtime',type=Path);p.add_argument('--codec-performance-profile',type=Path);p.add_argument('--boot-image',type=Path);p.add_argument('--rs-tools',type=Path);p.add_argument('--linker-runtime',type=Path);p.add_argument('--art-runtime',type=Path);p.add_argument('--native-icu-runtime',type=Path);p.add_argument('--hiddenapi-runtime',type=Path);p.add_argument('--strictmath-runtime',type=Path);p.add_argument('--character-runtime',type=Path);p.add_argument('--command-runtime',type=Path);p.add_argument('--canonical-core-jar-names',action='store_true');a=p.parse_args();assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';root.mkdir();repo=Path(__file__).resolve().parents[2]
base_manifest=a.predecessor/'install-manifest.json';before=json.loads(base_manifest.read_text());full=json.loads(base_manifest.read_text());runtime=json.loads((a.predecessor/'runtime.json').read_text());assert before['api']==29 and runtime['api']==29
product_manifest=json.loads((a.product/'manifest.json').read_text());runtime.update(native_host=True,native_host_schema=1,native_nice_limit=product_manifest.get('native_nice_limit',28),native_bootstrap=product_manifest.get('native_bootstrap'),version='0.4.0')
if 'application_filesystem_policy' in product_manifest:
 policy=product_manifest['application_filesystem_policy']
 assert policy['schema']=='saildroid-app-filesystem-v1'and policy['backend']=='kernel-seccomp-tsync'and policy['hardlinks_errno']=='EACCES'
 assert policy['scope']=='application-and-declared-processes'and policy['excluded_roles']==['manager','broker','session']
 assert policy['source_sha256']==product_manifest['native_sources']['native/host/app-filesystem-policy.hpp']
 runtime['application_filesystem_policy']=policy
if 'application_working_directory' in product_manifest:
 directory=product_manifest['application_working_directory']
 assert directory['path']=='/'and directory['scope']=='application-and-declared-processes'
 assert directory['excluded_roles']==['manager','broker','session']
 assert directory['source_sha256']==product_manifest['native_sources']['native/host/host-entry.cpp']
 runtime['application_working_directory']=directory
changes={} 
def copy(source,target,mode=0o644):
 file=root/target;file.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,file);file.chmod(mode);entry=dict(sha256=hashlib.sha256(file.read_bytes()).hexdigest(),size=file.stat().st_size,mode=mode);changes[target]=entry;full['files'][target]=entry;full['symlinks'].pop(target,None)
for name in ['runtime.jar','libsdbridge.so','libsdwindow.so','libsdhostapi.so','libsdhost29.so']:copy(a.product/name,'lib/'+name)
if a.command_runtime:
 from command_runtime import validate_commands
 runtime['private_commands']=validate_commands(a.command_runtime,repo)
 copy(a.command_runtime/'toybox','bin/touch',0o755)
 copy(a.command_runtime/'manifest.json','share/build/android-commands/manifest.json')
 copy(a.command_runtime/'NOTICE','share/licenses/android-commands-NOTICE')

if a.strictmath_runtime:
 from strictmath_runtime import validate_strictmath
 math=validate_strictmath(a.strictmath_runtime,repo)
 copy(a.strictmath_runtime/math['file'],'lib/'+math['file'])
 copy(a.strictmath_runtime/'manifest.json','share/build/fdlibm-native/manifest.json')
 copy(a.strictmath_runtime/'compile-commands.json','share/build/fdlibm-native/compile-commands.json')
 copy(a.strictmath_runtime/'NOTICE','share/licenses/fdlibm-NOTICE')
 runtime['strict_math_backend']=dict(schema=math['schema'],scope='All ART roles; actual fdlibm algorithms and native JNI retained; correct ARM64 byte order, no host libc math replacement',library_sha256=math['sha256'],manifest_sha256=hashlib.sha256((a.strictmath_runtime/'manifest.json').read_bytes()).hexdigest())
if a.linker_runtime:
 manifest=json.loads((a.linker_runtime/'manifest.json').read_text());file=a.linker_runtime/'libdl_bio.so.0'
 assert hashlib.sha256(file.read_bytes()).hexdigest()==manifest['sha256']
 assert manifest['exported_abi_unchanged']or(manifest.get('exported_abi_backward_compatible')and manifest.get('added_function_exports')==['bionic_cfi_check']),'Unexpected private-linker ABI change'
 copy(file,'lib/libdl_bio.so.0',before['files']['lib/libdl_bio.so.0']['mode'])
 copy(a.linker_runtime/'manifest.json','share/build/linker-unload-manifest.json')
if a.art_runtime:
 manifest=json.loads((a.art_runtime/'manifest.json').read_text())
 assert manifest['exported_imported_abi_unchanged']and manifest['baseline_sha256']=='20e43876e250c93f10ad69bbcd29a7a4ec886722f35b6005a9a2ee094abc6f7a'
 assert set(manifest['files'])=={'libart.so','libopenjdkjvmti.so'}
 for name,entry in manifest['files'].items():
  file=a.art_runtime/name;assert hashlib.sha256(file.read_bytes()).hexdigest()==entry['sha256']
  copy(file,'lib/'+name)
 copy(a.art_runtime/'manifest.json','share/build/art-agent-manifest.json')
 runtime['private_art_agent']=dict(manifest_sha256=hashlib.sha256((a.art_runtime/'manifest.json').read_bytes()).hexdigest(),debug_policy='actual-apk-manifest',native_abi_unchanged=True)
if a.native_icu_runtime:
 from native_icu_runtime import validate_native_icu
 manifest=validate_native_icu(a.native_icu_runtime,repo,product_manifest)
 if manifest.get('socket_flags_api29'):
  assert a.core_runtime and json.loads((a.core_runtime/'manifest.json').read_text())['core-libart'].get('api29_socket_flags'),'Native socket flags require matching Java fields'
 for name in sorted(manifest['files']):copy(a.native_icu_runtime/name,'lib/'+name)
 for name in ['manifest.json','source-manifest.json']:copy(a.native_icu_runtime/name,'share/build/native-icu/'+name)
 runtime['private_native_icu']=dict(schema=manifest['schema'],source_commit=manifest['source_commit'],manifest_sha256=hashlib.sha256((a.native_icu_runtime/'manifest.json').read_bytes()).hexdigest(),icu_version=manifest['actual_native_version'],unicode_version=manifest['actual_native_unicode_version'],scope='All apps; actual ICU63 libraries and native data',public_c_jni_exports_unchanged=True,private_cpp_namespace='icu_63')
if a.character_runtime:
 assert a.native_icu_runtime,'Character native ABI requires the matching packaged ICU63 runtime'
 from character_runtime import validate_character
 character=validate_character(a.character_runtime,repo,json.loads((a.native_icu_runtime/'manifest.json').read_text()))
 copy(a.character_runtime/character['file'],'lib/'+character['file'])
 copy(a.character_runtime/'manifest.json','share/build/character-native/manifest.json')
 copy(a.character_runtime/'compile-commands.json','share/build/character-native/compile-commands.json')
 copy(a.character_runtime/'NOTICE','share/licenses/Character-NOTICE')
 runtime['character_native_backend']=dict(schema=character['schema'],scope='All ART roles; original Character source linked to actual Android10 ICU63; original JNI registration and other libopenjdk natives retained',library_sha256=character['sha256'],manifest_sha256=hashlib.sha256((a.character_runtime/'manifest.json').read_bytes()).hexdigest(),unicode_version=[11,0,0,0])
if a.core_runtime:
 assert a.boot_image,'Core DEX changes require a matching boot image'
 manifest=json.loads((a.core_runtime/'manifest.json').read_text())
 for component in ['core-oj','core-libart']+(['apachehttp']if 'apachehttp'in manifest else[]):
  file=a.core_runtime/(component+'-hostdex.jar')
  assert hashlib.sha256(file.read_bytes()).hexdigest()==manifest[component]['sha256']
  copy(file,'java/dex/art/'+file.name)
 if manifest['core-oj'].get('api29_regex'):
  provenance=manifest['core-oj']['api29_regex'];assert set(provenance)=={'Matcher','Pattern'}
  for name,entry in provenance.items():assert hashlib.sha256((repo/'scripts/api29/core'/(name+'.java')).read_bytes()).hexdigest()==entry['sha256']
  copy(a.core_runtime/'manifest.json','share/build/regex-core-manifest.json')
  runtime['regex_api29']=dict(schema='saildroid-regex-api29-v1',scope='All apps; Android10 group/null checks and actual-target-SDK split semantics',legacy_leading_empty_split_max_sdk=28,core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-oj'].get('api29_atomic_access'):
  provenance=manifest['core-oj']['api29_atomic_access'];directory=repo/'scripts/api29/core/atomic-access'
  assert provenance==json.loads((directory/'sources.json').read_text())
  expected={'java/util/concurrent/atomic/'+n+'.java'for n in ['AtomicIntegerFieldUpdater','AtomicLongFieldUpdater','AtomicReferenceFieldUpdater']}|{'sun/reflect/misc/ReflectUtil.java'}
  assert set(provenance['files'])==expected
  for name,entry in provenance['files'].items():assert hashlib.sha256((directory/name).read_bytes()).hexdigest()==entry['sha256']
  copy(a.core_runtime/'manifest.json','share/build/atomic-access-core-manifest.json')
  runtime['atomic_access_api29']=dict(schema='saildroid-atomic-access-api29-v1',scope='All apps; actual caller/member access checks for AtomicFieldUpdater; owner/public/package/protected boundaries retained',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-oj'].get('api29_bigint_random'):
  provenance=manifest['core-oj']['api29_bigint_random'];directory=repo/'scripts/api29/core/bigint-random'
  assert provenance==json.loads((directory/'source.json').read_text()) and provenance['source']=='java/math/BigInteger.java'
  assert hashlib.sha256((directory/provenance['source']).read_bytes()).hexdigest()==provenance['sha256']
  copy(a.core_runtime/'manifest.json','share/build/bigint-random-core-manifest.json')
  runtime['bigint_random_api29']=dict(schema='saildroid-bigint-random-api29-v1',scope='All apps; Android10 signed word-count overflow rejected before allocation or Random access; supported generation and arithmetic unchanged',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-oj'].get('api29_objectstream_compat'):
  from objectstream_core_overlay import verify_source_family
  assert manifest['core-oj']['api29_objectstream_compat']==verify_source_family(repo/'scripts/api29/core')
  copy(a.core_runtime/'manifest.json','share/build/objectstream-compat-core-manifest.json')
  runtime['objectstream_compat_api29']=dict(schema='saildroid-objectstream-compat-api29-v1',scope='All apps; genuine default-SUID compatibility callback and original native boolean ABI retained',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 for family,component in [('util-compat','core-oj'),('zoneinfo-compat','core-libart')]:
  key='api29_'+family.replace('-','_')
  if manifest[component].get(key):
   from util_core_overlay import verify_source_family
   assert manifest[component][key]==verify_source_family(repo/'scripts/api29/core',family)
   copy(a.core_runtime/'manifest.json','share/build/'+family+'-core-manifest.json')
   runtime[family.replace('-','_')+'_api29']=dict(schema='saildroid-'+family+'-api29-v1',scope='All apps; Android10 array equality, null-message or timezone semantics; all original native fields and declarations retained',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 for family in ['decimal-compat','date-format']:
  key='api29_'+family.replace('-','_')
  if manifest['core-oj'].get(key):
   from text_core_overlay import verify_source_family
   provenance=manifest['core-oj'][key];assert provenance==verify_source_family(repo/'scripts/api29/core',family)
   assert manifest['core-libart'].get('platform_icu'),'Text adapters require matching ICU63 runtime classes'
   copy(a.core_runtime/'manifest.json','share/build/'+family+'-core-manifest.json')
   runtime[family.replace('-','_')+'_api29']=dict(schema='saildroid-'+family+'-api29-v1',scope='All apps; original Android10 text adapters over unchanged real ICU63; native field ABI preserved',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-oj'].get('api29_covariant'):
  provenance=manifest['core-oj']['api29_covariant'];directory=repo/'scripts/api29/core/covariant'
  assert provenance==json.loads((directory/'sources.json').read_text())
  expected={'java/nio/'+name+'.java'for name in ['Buffer','ByteBuffer','CharBuffer','ShortBuffer','IntBuffer','LongBuffer','FloatBuffer','DoubleBuffer']}|{'java/util/concurrent/ConcurrentHashMap.java'}
  assert set(provenance['files'])==expected
  for name,entry in provenance['files'].items():assert hashlib.sha256((directory/name).read_bytes()).hexdigest()==entry['sha256']
  copy(a.core_runtime/'manifest.json','share/build/covariant-core-manifest.json')
  runtime['covariant_api29']=dict(schema='saildroid-covariant-api29-v1',scope='All apps; AOSP Buffer/ConcurrentHashMap compatibility overloads generated by D8',bridge_methods=50,core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-oj'].get('api29_buffer_order'):
  provenance=manifest['core-oj']['api29_buffer_order'];directory=repo/'scripts/api29/core/buffer-order'
  assert manifest['core-oj'].get('api29_covariant') and provenance==json.loads((directory/'source.json').read_text())
  assert provenance['source']=='java/nio/DoubleBuffer.java'
  assert hashlib.sha256((directory/provenance['source']).read_bytes()).hexdigest()==provenance['sha256']
  copy(a.core_runtime/'manifest.json','share/build/buffer-order-core-manifest.json')
  runtime['buffer_order_api29']=dict(schema='saildroid-buffer-order-api29-v1',scope='All apps; DoubleBuffer signed-zero equality in ordering; scalar Double.compare unchanged',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-libart'].get('api29_os_ioctl'):
  provenance=manifest['core-libart']['api29_os_ioctl'];directory=repo/'scripts/api29/core/os-ioctl'
  assert provenance==json.loads((directory/'source.json').read_text()) and provenance['source']=='android/system/Os.java'
  assert hashlib.sha256((directory/provenance['source']).read_bytes()).hexdigest()==provenance['sha256']
  copy(a.core_runtime/'manifest.json','share/build/os-ioctl-core-manifest.json')
  runtime['os_ioctl_api29']=dict(schema='saildroid-os-ioctl-api29-v1',scope='All apps; API29 Int32Ref carrier delegates to existing real native ioctl; legacy ABI retained',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-libart'].get('api29_os_sendfile'):
  provenance=manifest['core-libart']['api29_os_sendfile'];directory=repo/'scripts/api29/core/os-sendfile'
  assert manifest['core-libart'].get('api29_os_ioctl')
  assert provenance==json.loads((directory/'source.json').read_text()) and provenance['source']=='android/system/Os.java'
  assert hashlib.sha256((directory/provenance['source']).read_bytes()).hexdigest()==provenance['sha256']
  copy(a.core_runtime/'manifest.json','share/build/os-sendfile-core-manifest.json')
  runtime['os_sendfile_api29']=dict(schema='saildroid-os-sendfile-api29-v1',scope='All apps; API29 Int64Ref nullable carrier delegates to existing real native sendfile; legacy ABI retained',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-libart'].get('api29_socket_flags'):
  provenance=manifest['core-libart']['api29_socket_flags'];directory=repo/'scripts/api29/core/socket-flags'
  assert provenance==json.loads((directory/'source.json').read_text()) and provenance['source']=='android/system/OsConstants.java'
  assert hashlib.sha256((directory/provenance['source']).read_bytes()).hexdigest()==provenance['sha256']
  assert a.native_icu_runtime,'Java socket fields require matching actual native initializers'
  native_flags=json.loads((a.native_icu_runtime/'manifest.json').read_text()).get('socket_flags_api29')
  assert native_flags and native_flags['sources']['scripts/api29/core/socket-flags/android/system/OsConstants.java']==provenance['sha256']
  copy(a.core_runtime/'manifest.json','share/build/socket-flags-core-manifest.json')
  runtime['socket_flags_api29']=dict(schema='saildroid-socket-flags-api29-v1',scope='All apps; actual native SOCK_CLOEXEC/SOCK_NONBLOCK initialization paired with API29 fields',native_library_sha256=native_flags['native_library_sha256'],core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-libart'].get('api29_stringfactory_compat'):
  from stringfactory_core_overlay import verify_source_family
  provenance=manifest['core-libart']['api29_stringfactory_compat']
  assert provenance==verify_source_family(repo/'scripts/api29/core')
  copy(a.core_runtime/'manifest.json','share/build/stringfactory-compat-core-manifest.json')
  runtime['stringfactory_compat_api29']=dict(schema='saildroid-stringfactory-compat-api29-v1',scope='All apps; exact Android10 UTF8 maximal-subpart decoder, existing native declarations retained',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
 if manifest['core-oj'].get('api29_runtime_load_compat'):
  from runtime_load_core_overlay import verify_source_family
  provenance=manifest['core-oj']['api29_runtime_load_compat']
  assert provenance==verify_source_family(repo/'scripts/api29/core')
  copy(a.core_runtime/'manifest.json','share/build/runtime-load-compat-core-manifest.json')
  runtime['runtime_load_compat_api29']=dict(schema='saildroid-runtime-load-compat-api29-v1',scope='All apps; restore existing deprecated Runtime.loadLibrary target SDK guard; public loading unchanged',core_manifest_sha256=hashlib.sha256((a.core_runtime/'manifest.json').read_bytes()).hexdigest())
if a.canonical_core_jar_names:
 assert a.core_runtime and a.hiddenapi_runtime and a.boot_image
 # These files are the actual OpenJDK/libart boot libraries. Publish their
 # standard Android names; java.boot.class.path then reflects real JAR paths.
 for component in ['core-oj','core-libart']:
  old='java/dex/art/'+component+'-hostdex.jar';new='java/dex/art/'+component+'.jar'
  assert old in runtime['boot_jars']
  copy(root/old,new,full['files'][old]['mode'])
  runtime['boot_jars']=[new if name==old else name for name in runtime['boot_jars']]
if a.framework_runtime:
 assert a.hiddenapi_runtime,'Framework changes require re-encoding the actual platform metadata'
 manifest=json.loads((a.framework_runtime/'manifest.json').read_text())
 expected={Path(name).name for name in runtime['boot_jars']if '/framework29-'in name}
 assert set(manifest['files'])==expected,'Framework partition inventory changed'
 for name,entry in manifest['files'].items():
  file=a.framework_runtime/name;assert hashlib.sha256(file.read_bytes()).hexdigest()==entry['sha256']
  copy(file,'java/dex/art/'+name)
 copy(a.framework_runtime/'manifest.json','share/build/framework-manifest.json')
if a.hiddenapi_runtime:
 assert a.boot_image,'Hidden API metadata requires a matching core boot image'
 manifest=json.loads((a.hiddenapi_runtime/'manifest.json').read_text())
 assert manifest['schema']=='saildroid-hiddenapi-v1' and manifest['unknown_policy']=='implementation-private-blacklist'
 assert manifest['canonical_flags_sha256']=='f22a59c215e752777a114bd9b07b0b6b4aedfc8e49e6efca0f99681771c5bfeb'
 assert set(manifest['files'])==set(runtime['boot_jars'])|{'lib/runtime.jar'}
 for name,entry in manifest['files'].items():
  assert entry['executable_code_unchanged'] and full['files'][name]['sha256']==entry['source_sha256'],name
  source=a.hiddenapi_runtime/name;assert hashlib.sha256(source.read_bytes()).hexdigest()==entry['sha256']
  copy(source,name,full['files'][name]['mode'])
 copy(a.hiddenapi_runtime/'manifest.json','share/build/hiddenapi-manifest.json')
 runtime['hidden_api']=dict(schema=manifest['schema'],policy='enabled',platform_runtime_boot=True,manifest_sha256=hashlib.sha256((a.hiddenapi_runtime/'manifest.json').read_bytes()).hexdigest())
if a.boot_image:
 recipe=json.loads((a.boot_image/'recipe.json').read_text());images=json.loads((a.boot_image/'manifest.json').read_text())
 expected={Path(name).name:full['files'][name]['sha256']for name in runtime['boot_jars']if '/framework29-'not in name}
 assert {Path(name).name:sha for name,sha in recipe['files'].items()}==expected
 for name,sha in images.items():
  relative=Path(name);assert len(relative.parts)==2 and relative.parts[0]=='arm64'and relative.suffix in['.art','.oat','.vdex']
  file=a.boot_image/relative;assert hashlib.sha256(file.read_bytes()).hexdigest()==sha;copy(file,'system/framework/'+name)
 copy(a.boot_image/'manifest.json','share/build/boot-image-manifest.json')
 runtime['boot_image']=dict(path='framework/boot.art',files=len(images),manifest_sha256=hashlib.sha256((a.boot_image/'manifest.json').read_bytes()).hexdigest())
if a.media_runtime:assert a.platform_runtime,'Media JNI requires the matching platform extraction'
if a.platform_runtime:
 platform=a.platform_runtime;extraction=json.loads((platform/'extraction.json').read_text())
 def original(file,target):
  relative=str(file.relative_to(platform));assert hashlib.sha256(file.read_bytes()).hexdigest()==extraction['files'][relative]['sha256'],relative
  copy(file,target)
 for name in ['android.test.base','android.test.mock','android.test.runner','org.apache.http.legacy']:
  original(platform/'framework'/(name+'.jar'),'system/framework/'+name+'.jar')
  original(platform/'etc/permissions'/(name+'.xml'),'system/etc/permissions/'+name+'.xml')
 locations=[platform/'lib64',*[p/'lib64'for p in(platform/'apex').iterdir()if p.is_dir()]]
 libraries={}
 for directory in locations:
  if directory.is_dir():
   for file in directory.glob('*.so'):libraries.setdefault(file.name,file)
 queue=['libcompiler_rt.so','librs_jni.so','libRScpp.so','libRS_internal.so','libRSCpuRef.so','libRSDriver.so','libRSCacheDir.so','libbcc.so'];visited=set();host={'libc.so','libm.so','libdl.so','libstdc++.so'}
 if a.media_runtime:
  queue+=['libmedia_jni.so','libmediandk.so']
  # The HIDL memory passthrough module must share this API29 dependency graph.
  # Do not fall back to a host module from another ABI/platform release.
  memory=platform/'lib64/hw/android.hidl.memory@1.0-impl.so'
  original(memory,'android-libs/hw/'+memory.name)
  queue.extend(re.findall(r'\(NEEDED\).*\[([^]]+)\]',subprocess.check_output(['readelf','-d',str(memory)],text=True)))
 while queue:
  name=queue.pop()
  if name in visited or name in host or 'android-libs/'+name in full['files']:continue
  visited.add(name);assert name in libraries,'Missing matching platform dependency '+name
  file=libraries[name];original(file,'android-libs/'+name)
  dynamic=subprocess.check_output(['readelf','-d',str(file)],text=True);queue.extend(re.findall(r'\(NEEDED\).*\[([^]]+)\]',dynamic))
 # Real AOSP CPU backend; private runtime property, no host-system change.
 base_properties=a.predecessor/'build.prop'
 # The accepted predecessor's file is captured separately by the build wrapper.
 assert base_properties.is_file(),'Capture the exact predecessor build.prop'
 assert hashlib.sha256(base_properties.read_bytes()).hexdigest()==before['files']['build.prop']['sha256']
 file=a.output/'build.prop';file.write_text(base_properties.read_text().rstrip()+'\ndebug.rs.default-CPU-driver=1\n');copy(file,'build.prop');file.unlink()
if a.rs_tools:
 assert a.platform_runtime,'RS tools require the matching platform extraction'
 tools=json.loads((a.rs_tools/'manifest.json').read_text());queue=['libRSDriver.so','libRS_internal.so']
 for item in tools['tools']:
  file=Path(item['file']);assert file.parent==a.rs_tools and file.name in['bcc','ld.mc']
  assert hashlib.sha256(file.read_bytes()).hexdigest()==item['sha256']
  copy(file,'rs/bin/'+file.name,0o755)
  queue.extend(re.findall(r'\(NEEDED\).*\[([^]]+)\]',subprocess.check_output(['readelf','-d',str(file)],text=True)))
 assert {Path(item['file']).name for item in tools['tools']}=={'bcc','ld.mc'}
 linker=platform/'apex/com.android.runtime.debug/bin/linker64'
 original(linker,'rs/bin/linker64');(root/'rs/bin/linker64').chmod(0o755)
 changes['rs/bin/linker64']['mode']=full['files']['rs/bin/linker64']['mode']=0o755
 private_libraries={}
 for relative in extraction['files']:
  file=platform/relative
  if '/lib64/'in'/'+relative and file.suffix=='.so':private_libraries.setdefault(file.name,file)
 visited=set()
 while queue:
  name=queue.pop()
  if name in visited:continue
  visited.add(name);assert name in private_libraries,'Missing compiler Bionic dependency '+name
  file=private_libraries[name];original(file,'rs/lib/'+name)
  queue.extend(re.findall(r'\(NEEDED\).*\[([^]]+)\]',subprocess.check_output(['readelf','-d',str(file)],text=True)))
 for name in ['libclcore.bc','libclcore_g.bc','libclcore_debug.bc','libclcore_debug_g.bc','libcompiler_rt.so']:
  original(platform/'lib64'/name,'rs/lib/'+name)
 copy(a.rs_tools/'manifest.json','share/build/rs-tools-manifest.json')
if a.codec_performance_profile:
 assert a.framework_runtime and 'android/media/MediaCodecPerformance.class'in json.loads((a.framework_runtime/'manifest.json').read_text())['included'],'Measured metadata needs the lazy framework configuration reader'
 sys.path.insert(0,str(repo/'scripts/cts'))
 from media_profile_validation import validate_profile
 profile=a.codec_performance_profile
 verified=validate_profile(profile,repo/'build/evidence/cts-frame-repair-20261031/aosp-extra/get_achievable_rates.py')
 provenance=verified['report'];samples=verified['points']
 assert provenance['status']=='GENERATED_NOT_INSTALLED'and provenance['required_rounds']==20 and provenance['actual_rounds']==len(samples)>=20
 assert provenance['source_sha256']=='1f879f25ba92862ec766debbf128bc9ca3a8aa6934026a3d0a662a7ab0a7b2b1'
 assert provenance['independent_holdout_required']is True
 assert len({(v['run_id'],v['round'])for v in samples})==len(samples),'Repeated measurements are not independent samples'
 assert all(v['runtime']==provenance['runtime']for v in samples)
 xml=profile/'media_codecs_performance.xml';assert hashlib.sha256(xml.read_bytes()).hexdigest()==provenance['xml_sha256']
 implementation=provenance['implementation_identity'];assert implementation['host_codec_processes']and implementation['private_root']==provenance['runtime']
 for name,entry in implementation['private'].items():assert full['files']['android-libs/'+name]['sha256']==entry['sha256'],'The measured native frontend changed: '+name
 copy(xml,'system/etc/saildroid-media-performance.xml')
 for name in ['provenance.json','samples.json','aosp-pure-functions-python3.py']:copy(profile/name,'share/build/media-performance/'+name)
 runtime['media_performance_measurements']=dict(schema='saildroid-device-media-measurements-v1',xml_sha256=provenance['xml_sha256'],samples=len(samples),scope='All apps; measured frame rates only; native coding capabilities unchanged',independent_holdout_required=True)
for name in ['saildroid-app','saildroid-host']:copy(a.product/name,'libexec/'+name,0o755)
copy(a.manager/'manager.apk','share/manager.apk')
copy(a.product/'webview-host/sdwebview-host','libexec/sdwebview-host',0o755)
copy(a.product/'webview-host/webview-host-env.json','libexec/webview-host-env.json')
copy(a.product/'webview-host/sdwebviewd','libexec/sdwebviewd',0o755)
copy(a.product/'webview-host/webview-engine.qml','libexec/webview-engine.qml')
# TimeZoneFinder needs both matching Android tzdata and country mapping.
with zipfile.ZipFile(repo/'build/codex-api29/inputs/android-all-10-robolectric-5803371.jar')as source:
 name='usr/share/zoneinfo/tzlookup.xml';file=a.output/'tzlookup.xml';file.write_bytes(source.read(name));copy(file,name);file.unlink()
# Android's DirectoryCertificateSource looks up subject_hash_old.N, whereas
# the existing verified Sailfish CA snapshot retained SHA256.pem filenames.
# Add an Android-compatible index of the exact same certificates. No new root,
# host trust-store mutation, certificate rewriting or relaxed verifier.
certificate_files=sorted(name for name in before['files']if name.startswith('system/etc/security/cacerts/')and name.endswith('.pem'))
certificate_root=Path('/home/art/etc/security/cacerts');by_subject={};certificate_index=[]
for name in certificate_files:
 file=certificate_root/Path(name).name
 assert file.is_file()and hashlib.sha256(file.read_bytes()).hexdigest()==before['files'][name]['sha256'],name
 result=subprocess.check_output(['openssl','x509','-in',str(file),'-noout','-subject_hash_old'],text=True).strip()
 assert re.fullmatch('[a-f0-9]{8}',result),result
 number=by_subject.get(result,0);by_subject[result]=number+1
 target='system/etc/security/cacerts/'+result+'.'+str(number)
 assert target not in full['files'],'Canonical certificate name already has an owner: '+target
 copy(file,target)
 certificate_index.append(dict(source=name,target=target,sha256=before['files'][name]['sha256']))
assert len(certificate_index)==len(certificate_files)>0
index=a.output/'ca-subject-index.json';index.write_text(json.dumps(dict(scope='Android lookup index of unchanged verified private CA snapshot',certificates=certificate_index),indent=2)+'\n');copy(index,'share/build/ca-subject-index.json');index.unlink()
copy(repo/'native/host/third_party/LICENSE.json.MIT','share/licenses/host-json-LICENSE.MIT')
copy(repo/'native/host/third_party/manifest.json','share/licenses/host-json-manifest.json')
# Brand raster is generated from the same geometry as the installed SVG.
icon=a.output/'saildroid.png';subprocess.run(['python3',str(repo/'scripts/api29/make-startup-icon.py'),str(icon)],check=True);copy(icon,'share/icons/saildroid.png');icon.unlink()
metadata=a.output/'runtime.json';metadata.write_text(json.dumps(runtime,indent=2)+'\n');copy(metadata,'runtime.json');metadata.unlink()
full['files'].pop('libexec/saildroid-open',None);full['symlinks']['libexec/saildroid-open']='saildroid-app';full['bytes']=sum(v['size'] for v in full['files'].values())
for name in changes:
 parts=Path(name).parts
 for i in range(1,len(parts)):
  assert str(Path(*parts[:i]))not in full['symlinks'],'Overlay target must use its canonical manifest path: '+name
record=dict(schema='saildroid-native-overlay-v1',api=29,predecessor_manifest_sha256=hashlib.sha256(base_manifest.read_bytes()).hexdigest(),predecessor=json.loads((a.predecessor/'identity.json').read_text()),changes=changes,symlinks={'libexec/saildroid-open':'saildroid-app'},install_manifest=full,product_manifest=json.loads((a.product/'manifest.json').read_text()))
(a.output/'overlay.json').write_text(json.dumps(record,indent=2)+'\n')
pending=a.output/'native-overlay.tar.gz.pending'
with tarfile.open(pending,'w:gz')as tar:tar.add(root,arcname='payload');tar.add(a.output/'overlay.json',arcname='overlay.json')
pending.replace(a.output/'native-overlay.tar.gz')
print('NATIVE_OVERLAY=packaged|files='+str(len(changes))+'|sha256='+hashlib.sha256((a.output/'native-overlay.tar.gz').read_bytes()).hexdigest())
