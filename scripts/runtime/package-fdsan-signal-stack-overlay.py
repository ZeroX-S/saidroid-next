#!/usr/bin/env python3
"""Package verified descriptor ownership and guarded ART signal stacks privately."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,stat,subprocess,tarfile,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','native','host','art','output']:
 p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2]
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2' and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute() and '..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
source=repo/'scripts/runtime/core/fdsan-ownership-compat';builder=repo/'scripts/runtime/build-fdsan-ownership-compat-vm.py'
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-fdsan-ownership-compat-v1' and module['passed']
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():
 assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
for key,core in module['components'].items():
 assert sha(a.module/(key+'-hostdex.jar'))==core['sha256']and sha(a.module/(key+'-classes.jar'))==core['class_jar_sha256']and core['all_existing_member_flags_and_native_declarations_preserved']
runtime=json.loads((oldroot/'runtime.json').read_text());encoded=json.loads((a.encoded/'manifest.json').read_text());old_encoded=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text())
assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old_encoded[k]
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('fdsan_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
added=set();newn=set();changed=[]
for n,v in encoded['files'].items():
 assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']
 assert sha(a.baseline_encoded/n)==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']
 with zipfile.ZipFile(a.baseline_encoded/n)as z:old,_=enc.dex_members(z.read('classes.dex'));oldres={k:hashlib.sha256(z.read(k)).hexdigest()for k in z.namelist()if not k.endswith('.dex')}
 with zipfile.ZipFile(a.encoded/n)as z:new,_=enc.dex_members(z.read('classes.dex'));newres={k:hashlib.sha256(z.read(k)).hexdigest()for k in z.namelist()if not k.endswith('.dex')}
 assert oldres==newres and set(old)<=set(new)and all(old[k][0]==new[k][0]for k in old)
 oldnative={k:v[0]for k,v in old.items()if v[0]&0x100};newnative={k:v[0]for k,v in new.items()if v[0]&0x100};assert all(newnative[k]==v for k,v in oldnative.items())
 added|=set(new)-set(old);newn|=set(newnative)-set(oldnative)
 if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
assert set(changed)=={'java/dex/art/core-libart.jar','java/dex/art/core-oj.jar'}
assert len(added)==16 and added=={n for c in module['components'].values()for n in c['added_members']}
assert len(newn)==4 and newn==set(module['components']['core-libart']['new_native_members'])
for key,core in module['components'].items():assert encoded['files']['java/dex/art/'+key+'.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
native=json.loads((a.native/'manifest.json').read_text());host=json.loads((a.host/'manifest.json').read_text());art=json.loads((a.art/'manifest.json').read_text())
assert native['schema']=='saildroid-fdsan-ownership-native-v1'and native['passed']and native['shared_tree_unchanged']and native['needed_identical']and native['all_defined_exports_identical']and native['all_previous_dynamic_symbols_preserved']
assert sha(repo/'native/compat/build-fdsan-ownership-vm.py')==native['builder_sha256']and sha(repo/'native/compat/fdsan-ownership/linux-fdsan.inc')==native['header_sha256']
assert sha(repo/'build/evidence/cts-frame-repair-20261031/aosp-extra/fdsan219-native-v1/libcore_io_Linux.cpp')==native['reference_sha256']
assert sha(a.native/'libjavacore.so')==native['library_sha256']and native['baseline_library_sha256']==full['files']['lib/libjavacore.so']['sha256']
assert host['schema']=='saildroid-fdsan-registry-lock-v1'and host['passed']and host['baseline_rebuild_byte_identical']and host['all_dynamic_symbols_identical']and host['needed_identical']
assert sha(repo/'native/compat/build-fdsan-registry-lock-vm.py')==host['builder_sha256']and sha(repo/'native/compat/fdsan-ownership/api29-fdsan.c')==host['source_sha256']
assert all(sha(repo/n)==h for n,h in host['actual_sources'].items())and sha(a.host/'libsdhost29.so')==host['library_sha256']and host['baseline_library_sha256']==full['files']['lib/libsdhost29.so']['sha256']
assert art['passed']and art['abi_unchanged']and art['vm_baseline_sources_and_objects_restored']and sha(a.art/'libart.so')==art['binary_sha256']and art['baseline_binary_sha256']==full['files']['lib/libart.so']['sha256']
assert sha(repo/'native/compat/build-art-host-signal-stack-vm.py')==art['builder_sha256']and sha(repo/'native/compat/art-host-signal-stack/sources.json')==art['source_meta_sha256']
for n,h in art['patches'].items():assert sha(repo/'native/compat/patches'/n)==h
for n,v in art['sources'].items():assert sha(a.art/'patched'/n)==v['patched_sha256']
# Independently compare the actual ELF sets, not just builder assertions.
def symbols(f):return set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
assert symbols(oldroot/'lib/libsdhost29.so')==symbols(a.host/'libsdhost29.so')
assert symbols(oldroot/'lib/libart.so')==symbols(a.art/'libart.so')
assert symbols(a.native/'libjavacore.so')-symbols(oldroot/'lib/libjavacore.so')==set(native['added_imports'])and not symbols(oldroot/'lib/libjavacore.so')-symbols(a.native/'libjavacore.so')
b=repo/'build/evidence/cts-frame-repair-20261031'
proofs=[b/n for n in ['original-fdsan220-paired-v1-audit.json','fdsan220-own-contract-v1.json','fdsan220-fatal-contract-v2.json','art220-signal-stack-contract-v1.json','fdsan219-native-lifecycle-v1.json']]
original,own,fatal,stack,lifecycle=[json.loads(f.read_text())for f in proofs]
assert original['accepted_comparison']and original['tests']==original['after_pass']==113 and original['before_fail']==6 and original['after_fail']==0 and not original['full_module_passed']
assert sha(b/'original-fdsan220-selected-v1.json')==original['raw_paired_sha256']
assert own['passed']and 'checks=1184|'in own['marker']and own['source_sha256']==sha(repo/'scripts/runtime/tests/OsFdOwnershipContract.java')and own['source_meta_sha256']==sha(source/'sources.json')
assert fatal['passed']and fatal['exit_code']==-6 and fatal['normal_jit']and not fatal['diagnostic_stack_override']and not fatal['native_diagnostic_chain']
assert stack['passed']and 'threads=64|checks=320|'in stack['marker']and stack['source_sha256']==sha(repo/'scripts/runtime/tests/fdsan/ArtSignalStackContract.java')and stack['helper_source_sha256']==sha(repo/'scripts/runtime/tests/fdsan/art-signal-stack.c')
assert fatal['source_sha256']==sha(repo/'scripts/runtime/tests/fdsan/FdOwnershipFatalContract.java')and fatal['helper_source_sha256']==sha(repo/'scripts/runtime/tests/fdsan/fatal-ownership.c')
assert lifecycle['passed']and lifecycle['library_sha256']==host['library_sha256']and lifecycle['native_manifest_sha256']==sha(a.host/'manifest.json')
for d in [own,fatal,stack]:
 assert d['actual_art_sha256']==art['binary_sha256']and d['actual_art_manifest_sha256']==sha(a.art/'manifest.json')and d['actual_new_javacore_sha256']==native['library_sha256']
 assert d['actual_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']and d['actual_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']
 assert d['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')and d['actual_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
 assert d.get('actual_native_host_sha256',d.get('actual_new_host_sha256'))==host['library_sha256']
assert original['actual_new_art_sha256']==art['binary_sha256']and original['actual_new_javacore_sha256']==native['library_sha256']and original['actual_new_host_sha256']==host['library_sha256']
assert original['actual_new_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']and original['actual_new_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']
assert original['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')and original['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
assert original['actual_old_runtime_sha256']==original['actual_new_runtime_sha256']==own['actual_new_runtime_sha256']==full['files']['lib/runtime.jar']['sha256']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
 v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
def putjson(value,n):
 tmp=a.output/'metadata.pending.json';tmp.write_text(json.dumps(value,indent=2)+'\n');install(tmp,n);tmp.unlink()
for directory,name in [(a.native,'libjavacore.so'),(a.host,'libsdhost29.so'),(a.art,'libart.so')]:install(directory/name,'lib/'+name,full['files']['lib/'+name]['mode'])
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/fdsan-signal-stack/'+n)
for n,v in module['sources']['files'].items():
 install(source/n,'share/build/fdsan-signal-stack/sources/'+n);install(repo/v['reference'],'share/build/fdsan-signal-stack/references/'+n)
for directory,name in [(a.native,'native'),(a.host,'host'),(a.art,'art')]:install(directory/'manifest.json','share/build/fdsan-signal-stack/'+name+'-manifest.json')
for n in ['native/compat/build-fdsan-ownership-vm.py','native/compat/build-fdsan-registry-lock-vm.py','native/compat/build-art-host-signal-stack-vm.py','native/compat/fdsan-ownership/linux-fdsan.inc','native/compat/fdsan-ownership/api29-fdsan.c','native/compat/art-host-signal-stack/thread_linux.cc','native/compat/art-host-signal-stack/sources.json',*['native/compat/patches/'+n for n in art['patches']],'scripts/runtime/tests/OsFdOwnershipContract.java','scripts/runtime/tests/fdsan/FdOwnershipFatalContract.java','scripts/runtime/tests/fdsan/fatal-ownership.c','scripts/runtime/tests/fdsan/ArtSignalStackContract.java','scripts/runtime/tests/fdsan/art-signal-stack.c']:
 install(repo/n,'share/build/fdsan-signal-stack/provenance/'+n)
for n in art['sources']:install(a.art/'patched'/n,'share/build/fdsan-signal-stack/art-patched/'+n)
install(a.native/'source/libcore_io_Linux.cpp','share/build/fdsan-signal-stack/native-patched/libcore_io_Linux.cpp')
for f in proofs:install(f,'share/build/fdsan-signal-stack/evidence/'+f.name)
# Keep historical provenance and explicitly update current library references.
oldicu=json.loads((oldroot/'share/build/native-icu/manifest.json').read_text());assert oldicu['files']['libjavacore.so']['sha256']==native['baseline_library_sha256']
install(oldroot/'share/build/native-icu/manifest.json','share/build/native-icu/base-manifest-before-fdsan.json')
icu=copy.deepcopy(oldicu);icu.update(schema='saildroid-native-icu-fdsan-v5',base_manifest_sha256=sha(oldroot/'share/build/native-icu/manifest.json'),base_manifest_path='share/build/native-icu/base-manifest-before-fdsan.json',fdsan_native_manifest_sha256=sha(a.native/'manifest.json'))
icu['files']['libjavacore.so']=dict(sha256=native['library_sha256'],bytes=(a.native/'libjavacore.so').stat().st_size,dynamic=subprocess.check_output(['readelf','-d',str(a.native/'libjavacore.so')],text=True))
putjson(icu,'share/build/native-icu/manifest.json')
agent=json.loads((oldroot/'share/build/art-agent-manifest.json').read_text());assert agent['files']['libart.so']['sha256']==art['baseline_binary_sha256']and agent['files']['libopenjdkjvmti.so']['sha256']==full['files']['lib/libopenjdkjvmti.so']['sha256']
install(oldroot/'share/build/art-agent-manifest.json','share/build/fdsan-signal-stack/base-art-agent-manifest.json')
agent['files']['libart.so']=dict(sha256=art['binary_sha256'],size=(a.art/'libart.so').stat().st_size)
agent['host_signal_stack']=dict(build_manifest_sha256=sha(a.art/'manifest.json'),exact_abi_unchanged_from_previous=True,minimum_bytes=262144,guard_pages=2,native_stack_only=True)
putjson(agent,'share/build/art-agent-manifest.json')
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['private_native_icu'].update(schema=icu['schema'],manifest_sha256=sha(root/'share/build/native-icu/manifest.json'))
for key,field in [('socket_flags_api29','native_library_sha256'),('linux_io_compat','library_sha256'),('os_extended_io','current_native_library_sha256'),('numeric_resolver','library_sha256')]:
 assert runtime[key][field]==native['baseline_library_sha256'];runtime[key][field]=native['library_sha256']
for key in ['blockguard_runtime_compat','zip_compat']:
 assert runtime[key]['current_native_host_sha256']==host['baseline_library_sha256'];runtime[key]['current_native_host_sha256']=host['library_sha256']
runtime['private_art_agent']['manifest_sha256']=sha(root/'share/build/art-agent-manifest.json')
assert runtime['interface_object_dispatch']['libart_sha256']==art['baseline_binary_sha256'];runtime['interface_object_dispatch']['libart_sha256']=art['binary_sha256']
runtime['fdsan_ownership']=dict(schema=module['schema'],scope='All apps; real process-private native descriptor ownership, tagged close, raw ownership transfer and TCP/UDP ownership. Existing policy default retained.',module_manifest_sha256=sha(a.module/'manifest.json'),native_manifest_sha256=sha(a.native/'manifest.json'),host_manifest_sha256=sha(a.host/'manifest.json'),libjavacore_sha256=native['library_sha256'],libsdhost29_sha256=host['library_sha256'],original_selected_tests=113,original_selected_failures=0,own_checks=1184,fatal_mode_contract='separate VM process clean SIGABRT',full_module_passed=False)
runtime['host_signal_stack']=dict(schema='saildroid-art-host-signal-stack-v1',scope='All ART host threads; guarded native signal stacks, independent of managed heap and JIT policy',build_manifest_sha256=sha(a.art/'manifest.json'),libart_sha256=art['binary_sha256'],minimum_bytes=262144,guard_pages=2,thread_lifecycle_checks=320,original_abi_unchanged=True)
putjson(runtime,'runtime.json')
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['fdsan_signal_stack_overlay']=dict(schema='saildroid-fdsan-signal-stack-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),original_selected_tests=113,original_selected_failures=0,own_ownership_checks=1184,thread_lifecycle_checks=320,clean_fatal_sigabrt=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']and all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
for directory,lib,record in [(a.native,'libjavacore.so',native),(a.host,'libsdhost29.so',host),(a.art,'libart.so',art)]:assert sha(directory/lib)==record.get('library_sha256',record.get('binary_sha256'))
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('FDSAN_SIGNAL_STACK_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
