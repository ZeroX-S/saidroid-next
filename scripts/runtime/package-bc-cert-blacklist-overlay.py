#!/usr/bin/env python3
"""Package the canonical Android10 CertBlacklist class over unchanged BC1.77 primitives."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, stat, tarfile, zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','output']:
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
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-bc-cert-blacklist-compat-v1'and module['passed']
builder=repo/'scripts/runtime/build-bc-cert-blacklist-compat-vm.py';source=repo/'scripts/runtime/core/bc-cert-blacklist-compat'
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():
    assert sha(source/n)==v['sha256']and sha(repo/v['reference'])==v['reference_sha256']
    assert (source/n).read_text()==(repo/v['reference']).read_text().replace('org.bouncycastle.','com.android.org.bouncycastle.')
core=module['components']['bouncycastle'];assert sha(a.module/'bouncycastle-hostdex.jar')==core['sha256']and sha(a.module/'bouncycastle-classes.jar')==core['class_jar_sha256']
assert module['all_previous_class_bytes_identical']and module['canonical_namespace_relocation_only']and core['all_existing_member_flags_and_native_declarations_preserved']and len(core['added_members'])==16
assert all(n.startswith('Lcom/android/org/bouncycastle/jce/provider/CertBlacklist;->')for n in core['added_members'])
assert all(sha(Path(n))==h for n,h in module['inputs'].items())
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
assert changed==['java/dex/art/bouncycastle-hostdex.jar']and len(added)==16 and added==set(core['added_members'])
assert encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_files=[evidence/n for n in ['original-bc-cert-blacklist234-selected-v1-audit.json','original-bc-cert-blacklist234-regression-v1-audit.json','bc-cert-blacklist234-encoded-v1-boundary.json','bc-cert-blacklist234-own-contract-v1.json']]
original,regression,boundary,own=[json.loads(f.read_text())for f in proof_files]
assert original['accepted_comparison']and original['tests']==18 and original['before_fail']==18 and original['before_executed_method_bodies']==0 and original['after_fail']==0 and original['after_executed_method_bodies']==18 and original['whole_original_class']and original['same_original_expected_methods']and original['warning_callbacks_replaced_by_actual_methods']and not original['full_module_passed']and not original['phone_executed']and original['jni_registrations']==104
assert len(set(original['constructor_methods_in_original_order']))==18
assert sha(evidence/'original-bc-cert-blacklist234-selected-v1.json')==original['raw_paired_sha256']and sha(evidence/'run-original-bc-cert-blacklist234-selected-v1-vm.py')==original['driver_sha256']and sha(evidence/'original-bc-cert-blacklist234-selected-v1-host.log')==original['driver_log_sha256']
assert original['actual_old_bouncycastle_sha256']==old_encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['sha256']
assert regression['accepted_no_regression']and regression['tests']==102 and regression['before_fail']==regression['after_fail']==3 and regression['before_passed']==regression['after_passed']==99 and regression['same_ordered_callbacks']and not regression['full_module_passed']and not regression['phone_executed']and regression['jni_registrations']==104
assert sha(evidence/'original-bc-cert-blacklist234-regression-v1.json')==regression['raw_paired_sha256']and sha(evidence/'run-original-bc-cert-blacklist234-regression-v1-vm.py')==regression['driver_sha256']and sha(evidence/'original-bc-cert-blacklist234-regression-v1-host.log')==regression['driver_log_sha256']
for proof in [original,regression]:
 assert proof['actual_new_bouncycastle_sha256']==encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['sha256']and proof['actual_new_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']and proof['actual_new_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']and proof['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')and proof['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
 assert all(proof[key]==full['files']['lib/'+name]['sha256']for key,name in [('actual_javacore_sha256','libjavacore.so'),('actual_native_host_sha256','libsdhost29.so'),('actual_bridge_sha256','libsdbridge.so'),('actual_art_sha256','libart.so')])
assert boundary['passed']and boundary['core_module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['changed_jars']==changed and boundary['encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and boundary['boot_manifest_sha256']==sha(a.boot/'manifest.json')and boundary['all_existing_effective_flags_preserved']and set(boundary['new_flags'])==added and all(v=='blacklist'for v in boundary['new_flags'].values())
assert own['passed']and len(own['markers'])==2 and 'properties=566|implementation_classes=153|'in own['markers'][0]and 'BKS_actual_roundtrip=true|bad_password_rejected=true|actual_version=1.77'in own['markers'][0]and 'checks=67|'in own['markers'][1]
assert own['driver_source_sha256']==sha(evidence/'CertBlacklist234OwnContractRunner.java')and all(sha(repo/n)==h for n,h in own['source_sha256'].items())and own['actual_new_bouncycastle_sha256']==encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['sha256']and own['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and own['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')
for key,name in [('actual_art_sha256','lib/libart.so'),('actual_javacore_sha256','lib/libjavacore.so'),('actual_native_host_sha256','lib/libsdhost29.so'),('actual_runtime_sha256','lib/runtime.jar'),('actual_bridge_sha256','lib/libsdbridge.so')]:assert own[key]==full['files'][name]['sha256']
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
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/bc-cert-blacklist/'+n)
for n in module['sources']['files']:install(source/n,'share/build/bc-cert-blacklist/sources/'+n)
for n,v in module['sources']['files'].items():install(repo/v['reference'],'share/build/bc-cert-blacklist/references/'+n)
for f in proof_files:install(f,'share/build/bc-cert-blacklist/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['bc_cert_blacklist_compat']=dict(schema=module['schema'],core_module_manifest_sha256=sha(a.module/'manifest.json'),bouncycastle_sha256=encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['sha256'],canonical_namespace_relocation_only=True,all_previous_class_bytes_identical=True,original_whole_class_tests=18,original_whole_class_failures=0,original_whole_class_bodies_executed=18,original_crypto_regression_tests=102,original_crypto_regression_failures=3,canonical_registry_properties=566,canonical_implementation_classes=153,crypto_policy_checks=67,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['bc_cert_blacklist_overlay']=dict(schema='saildroid-bc-cert-blacklist-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_art_media_manager_trust_bytes_unchanged=True,original_whole_class_tests=18,original_whole_class_failures=0,original_crypto_regression_tests=102,original_crypto_regression_failures=3,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('BC_CERT_BLACKLIST_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
