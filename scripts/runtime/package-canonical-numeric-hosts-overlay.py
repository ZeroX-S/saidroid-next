#!/usr/bin/env python3
"""Package canonical numeric Java delegation and real ordinary/numeric LinuxJNI resolver."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, stat, subprocess, tarfile, zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','native','output']:
    p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text())
assert before['schema']=='saildroid-native-overlay-v3' and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
    f=oldroot/n;assert not Path(n).is_absolute() and '..'not in Path(n).parts
    assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-inet-numeric-compat-v1'and module['passed']
builder=repo/'scripts/runtime/build-inet-numeric-compat-vm.py';source=repo/'scripts/runtime/core/inet-numeric-compat'
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():
    assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
core=module['components']['core-oj'];assert sha(a.module/'core-oj-hostdex.jar')==core['sha256']and sha(a.module/'core-oj-classes.jar')==core['class_jar_sha256']
assert core['all_existing_member_flags_preserved']and core['all_existing_members_and_native_declarations_preserved']and not core['added_members']
runtime=json.loads((oldroot/'runtime.json').read_text())
encoded=json.loads((a.encoded/'manifest.json').read_text());old_encoded=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text())
assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old_encoded[k]
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('loader_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
added=set();changed=[]
for n,v in encoded['files'].items():
    assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']
    assert sha(a.baseline_encoded/n)==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']
    with zipfile.ZipFile(a.baseline_encoded/n)as z:old,_=enc.dex_members(z.read('classes.dex'));old_resources={k:sha256 for k in z.namelist()if not k.endswith('.dex')for sha256 in [hashlib.sha256(z.read(k)).hexdigest()]}
    with zipfile.ZipFile(a.encoded/n)as z:new,_=enc.dex_members(z.read('classes.dex'));new_resources={k:hashlib.sha256(z.read(k)).hexdigest()for k in z.namelist()if not k.endswith('.dex')}
    assert new_resources==old_resources
    assert set(old)<=set(new)
    actual_flag_changes={k:dict(before=old[k][0],after=new[k][0])for k in old if old[k][0]!=new[k][0]}
    assert actual_flag_changes=={}
    assert {k:v[0]for k,v in old.items()if v[0]&0x100}=={k:v[0]for k,v in new.items()if v[0]&0x100}
    added|=set(new)-set(old)
    if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
assert changed==['java/dex/art/core-oj.jar']and len(added)==0 and added==set(core['added_members'])
assert encoded['files']['java/dex/art/core-oj.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_files=[evidence/n for n in ['original-canonical-numeric233-chain-v1-audit.json','original-canonical-numeric233-regression-v1-audit.json','inet-numeric232-encoded-v1-boundary.json','canonical-numeric233-own-contract-v2.json','canonical-numeric233-native-contract-v1.json','inet-numeric232-original-namespace-v1.json','canonical-numeric233-original-namespace-v1.json','canonical-numeric233-regression-namespace-v1.json','canonical-numeric233-own-namespace-v2.json']]
original,regression,boundary,own,native_contract,*namespaces=[json.loads(p.read_text())for p in proof_files]
assert original['accepted_comparison']and original['tests']==184 and original['combined_before_fail']==14 and original['combined_after_fail']==2 and original['combined_fixed_original_failures']==12 and original['whole_original_classes']and not original['full_module_passed']and not original['phone_executed']and original['jni_registrations']==104
for stage in original['stages']:
 prefix=stage['stage'];assert sha(evidence/('original-'+prefix+'-selected-v1.json'))==stage['raw_paired_sha256']and sha(evidence/('run-original-'+prefix+'-selected-v1-vm.py'))==stage['driver_sha256']and sha(evidence/('original-'+prefix+'-selected-v1-host.log'))==stage['driver_log_sha256']
assert original['actual_old_core_oj_sha256']==old_encoded['files']['java/dex/art/core-oj.jar']['sha256']
assert regression['accepted_no_regression']and regression['tests']==322 and regression['before_fail']==regression['after_fail']==0 and regression['before_assumptions']==regression['after_assumptions']==2 and regression['same_ordered_callbacks']and not regression['full_module_passed']and not regression['phone_executed']and regression['jni_registrations']==104
assert sha(evidence/'original-canonical-numeric233-regression-v1.json')==regression['raw_paired_sha256']and sha(evidence/'run-original-canonical-numeric233-regression-v1-vm.py')==regression['driver_sha256']and sha(evidence/'original-canonical-numeric233-regression-v1-host.log')==regression['driver_log_sha256']
for proof in [original,regression]:
 assert proof['actual_new_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']and proof['actual_new_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']and proof['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')and proof['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
 assert all(proof[key]==full['files']['lib/'+name]['sha256']for key,name in [('actual_native_host_sha256','libsdhost29.so'),('actual_bridge_sha256','libsdbridge.so'),('actual_art_sha256','libart.so')])
assert boundary['passed']and boundary['changed_jars']==changed and boundary['core_module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and boundary['boot_manifest_sha256']==sha(a.boot/'manifest.json')and boundary['all_existing_effective_flags_preserved']and not boundary['new_flags']and not boundary['canonical_member_flag_changes']
native=json.loads((a.native/'manifest.json').read_text());native_builder=repo/'native/compat/build-canonical-numeric-hosts-vm.py';native_source=repo/'native/compat/canonical-numeric-hosts/sources.json';native_sources=json.loads(native_source.read_text())
assert native['schema']=='saildroid-canonical-numeric-hosts-native-v1'and native['passed']and all(native[k]for k in ['shared_tree_unchanged','all_previous_dynamic_symbols_preserved','all_defined_exports_identical','needed_identical'])
assert sha(native_builder)==native['builder_sha256']and all(sha(repo/n)==h for n,h in native['headers'].items())and sha(a.native/'libjavacore.so')==native['library_sha256']and native['baseline_library_sha256']==full['files']['lib/libjavacore.so']['sha256']
assert all(sha(repo/n)==h for n,h in native_sources['references'].items())
assert sha(a.native/'source/libcore_io_Linux.cpp')==native['linux_source_sha256']==native['baseline_linux_source_sha256']and sha(a.native/'source/Portability.h')==native['patched_portability_sha256']
def symbols(f,defined=False):return set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',*(['--defined-only']if defined else[]),str(f)],text=True).splitlines()if len(l.split())>=2)
old_symbols=symbols(oldroot/'lib/libjavacore.so');new_symbols=symbols(a.native/'libjavacore.so');assert old_symbols<=new_symbols and new_symbols-old_symbols==set(native['added_imports'])and symbols(oldroot/'lib/libjavacore.so',True)==symbols(a.native/'libjavacore.so',True)
for proof in [original,regression]:assert proof['actual_new_javacore_sha256']==native['library_sha256']and proof['native_manifest_sha256']==sha(a.native/'manifest.json')
assert own['passed']and 'checks=10306|'in own['marker']and own['source_sha256']==sha(repo/'scripts/runtime/tests/resolver/CanonicalNumericHostsContract.java')and own['driver_source_sha256']==sha(evidence/'CanonicalNumeric233ContractRunner.java')and len(own['before'])==1 and own['before'][0]['expected_baseline_failure']
assert own['actual_new_javacore_sha256']==native['library_sha256']and own['native_manifest_sha256']==sha(a.native/'manifest.json')and own['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and own['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')and own['actual_new_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']and own['actual_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']
for key,name in [('actual_art_sha256','lib/libart.so'),('actual_native_host_sha256','lib/libsdhost29.so'),('actual_runtime_sha256','lib/runtime.jar'),('actual_bridge_sha256','lib/libsdbridge.so')]:assert own[key]==full['files'][name]['sha256']
assert native_contract['passed']and len(native_contract['cases'])==2 and all(v['passed']for v in native_contract['cases'])and 'checks=63|'in native_contract['cases'][0]['marker']and 'checks=29|'in native_contract['cases'][1]['marker']and native_contract['source_sha256']==sha(repo/'native/compat/tests/canonical-numeric-hosts/resolver-contract.cpp')and all(native['headers'][n]==h for n,h in native_contract['headers'].items())
assert all(v['passed']and v['global_parent_files_unchanged']for v in namespaces)
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
    v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/canonical-numeric-hosts/'+n)
for n in module['sources']['files']:install(source/n,'share/build/canonical-numeric-hosts/sources/'+n)
for n,v in module['sources']['files'].items():install(repo/v['reference'],'share/build/canonical-numeric-hosts/references/'+n)
for f in proof_files:install(f,'share/build/canonical-numeric-hosts/evidence/'+f.name)
install(a.native/'libjavacore.so','lib/libjavacore.so',full['files']['lib/libjavacore.so']['mode'])
for f,n in [(a.native/'manifest.json','manifest.json'),(native_builder,'builder.py'),(native_source,'sources.json'),(a.native/'source/Portability.h','Portability.h'),(a.native/'source/libcore_io_Linux.cpp','libcore_io_Linux.cpp')]:install(f,'share/build/canonical-numeric-hosts/native/'+n)
for n in native['headers']:install(repo/n,'share/build/canonical-numeric-hosts/native/provenance/'+n)
for n in native_sources['references']:install(repo/n,'share/build/canonical-numeric-hosts/native/references/'+Path(n).name)
for f in [repo/'scripts/runtime/tests/resolver/CanonicalNumericHostsContract.java',evidence/'CanonicalNumeric233ContractRunner.java',repo/'native/compat/tests/canonical-numeric-hosts/resolver-contract.cpp']:install(f,'share/build/canonical-numeric-hosts/tests/'+f.name)
old_icu=json.loads((oldroot/'share/build/native-icu/manifest.json').read_text());assert old_icu['files']['libjavacore.so']['sha256']==native['baseline_library_sha256'];install(oldroot/'share/build/native-icu/manifest.json','share/build/native-icu/base-manifest-before-canonical-numeric-hosts.json')
icu=copy.deepcopy(old_icu);icu.update(schema='saildroid-native-icu-canonical-numeric-hosts-v8',base_manifest_sha256=sha(oldroot/'share/build/native-icu/manifest.json'),base_manifest_path='share/build/native-icu/base-manifest-before-canonical-numeric-hosts.json',canonical_numeric_hosts_manifest_sha256=sha(a.native/'manifest.json'));icu['files']['libjavacore.so']=dict(sha256=native['library_sha256'],bytes=(a.native/'libjavacore.so').stat().st_size,dynamic=subprocess.check_output(['readelf','-d',str(a.native/'libjavacore.so')],text=True))
tmp_icu=a.output/'icu.pending.json';tmp_icu.write_text(json.dumps(icu,indent=2)+'\n');install(tmp_icu,'share/build/native-icu/manifest.json');tmp_icu.unlink()
runtime['private_native_icu'].update(schema=icu['schema'],manifest_sha256=sha(root/'share/build/native-icu/manifest.json'))
for section,key in [('socket_flags_api29','native_library_sha256'),('linux_io_compat','library_sha256'),('os_extended_io','current_native_library_sha256'),('numeric_resolver','library_sha256'),('fdsan_ownership','libjavacore_sha256'),('component_hosts','libjavacore_sha256'),('reverse_component_hosts','libjavacore_sha256')]:
 assert runtime[section][key]==native['baseline_library_sha256'];runtime[section][key]=native['library_sha256']

runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['canonical_numeric_hosts']=dict(schema='saildroid-canonical-numeric-hosts-v1',core_module_manifest_sha256=sha(a.module/'manifest.json'),native_manifest_sha256=sha(a.native/'manifest.json'),libjavacore_sha256=native['library_sha256'],all_existing_member_flags_preserved=True,original_whole_class_tests=506,original_before_failures=14,original_after_failures=2,original_assumptions=2,own_java_checks=10306,own_native_checks=92,full_module_passed=False,phone_executed=False,normal_apps=True)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['canonical_numeric_hosts_overlay']=dict(schema='saildroid-canonical-numeric-hosts-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_other_native_art_media_manager_trust_bytes_unchanged=True,original_whole_class_tests=506,original_whole_class_failures=2,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('CANONICAL_NUMERIC_HOSTS_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
