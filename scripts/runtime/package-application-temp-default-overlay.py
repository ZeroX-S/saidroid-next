#!/usr/bin/env python3
"""Package the mutable application-private Java temp defaults with the exact current native host."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, stat, subprocess, tarfile, zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','host','output']:
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
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-application-temp-default-compat-v1'and module['passed']
builder=repo/'scripts/runtime/build-application-temp-default-compat-vm.py';source=repo/'scripts/runtime/core/application-temp-default-compat'
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():
    assert sha(source/n)==v['sha256']and sha(repo/v['reference'])==v['reference_sha256']
    assert sha(repo/v['baseline_source'])==v['baseline_sha256']
assert sha(source/'system-app-temp-default.patch')==module['sources']['patch_sha256']
core=module['components']['core-oj'];assert sha(a.module/'core-oj-hostdex.jar')==core['sha256']and sha(a.module/'core-oj-classes.jar')==core['class_jar_sha256']
assert core['all_existing_members_and_native_declarations_preserved'] and core['all_existing_member_flags_preserved'] and not core['added_members'] and core['changed_classes']==['java/lang/System.class'] and module['unmodified_system_classes_byte_identical']
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
assert changed==['java/dex/art/core-oj.jar']and not added and added==set(core['added_members'])
assert encoded['files']['java/dex/art/core-oj.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==27 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_files=[evidence/n for n in ['original-temp-default244-paired-v1-audit.json','application-temp-default244-encoded-v1-boundary.json','mutable-temp-defaults244-own-contract-v1.json']]
original,boundary,own=[json.loads(f.read_text())for f in proof_files]
assert original['passed']and original['tests']==163 and original['same_ordered_original_ids']and original['original_apk_arguments_and_budgets_identical']and original['before_counts']==dict(started=163,passed=161,failed=2)and original['after_counts']==dict(started=163,passed=162,failed=1)
assert original['fixed_tests']==['libcore.java.io.FileTest#testJavaIoTmpdirMutable']and original['remaining_failures']==['libcore.java.lang.SystemTest#testSystemProperties_mutable']and not original['full_module_passed']and not original['phone_staged']
assert original['before_sha256']==sha(evidence/'original-temp-default244-before-v1.json')and original['after_sha256']==sha(evidence/'original-temp-default244-after-v3.json')and original['own_contract_sha256']==sha(proof_files[2])and original['core_module_manifest_sha256']==sha(a.module/'manifest.json')
host=json.loads((a.host/'manifest.json').read_text());host_builder=repo/'native/compat/build-mutable-temp-default-host-vm.py';host_patch=repo/'native/compat/patches/host-mutable-temp-default.patch'
assert host['passed']and host['schema']=='saildroid-mutable-temp-default-host-v1'and host['unmodified_host_reproduced_byte_identical']and host['all_dynamic_symbols_identical']and host['needed_identical']
assert host['baseline_binary_sha256']==full['files']['libexec/saildroid-host']['sha256']and host['binary_sha256']==sha(a.host/'saildroid-host')and host['patch_sha256']==sha(host_patch)and host['builder_sha256']==sha(host_builder)and original['host_manifest_sha256']==sha(a.host/'manifest.json')
assert sha(a.host/'source/host-entry.cpp')==host['sources_after']['host-entry.cpp']
sy=lambda f:set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
assert sy(a.host/'baseline-host')==sy(a.host/'saildroid-host')
raw=json.loads((evidence/'original-temp-default244-after-v3.json').read_text());before_raw=json.loads((evidence/'original-temp-default244-before-v1.json').read_text())
assert all(raw.get(k)and before_raw.get(k)for k in ['private_state_and_apk_removed','owned_processes_reaped','binderfs_removed','private_bus_removed','private_data_mount_removed'])
assert raw['actual_client_runtime_maps']
assert all(v==images[str(Path(n).relative_to('/var/tmp/saidroid-temp-default244-prototype-v2/root/system/framework'))]for n,v in raw['actual_client_runtime_maps'].items()if '/system/framework/'in n)
core_oj=encoded['files']['java/dex/art/core-oj.jar']['sha256']
assert all(v==full['files'][str(Path(n).relative_to('/var/tmp/saidroid-temp-default244-prototype-v2/root'))]['sha256'] for n,v in raw['actual_client_runtime_maps'].items()if '/system/framework/'not in n)
assert boundary['passed']and boundary['core_module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['changed_jars']==changed and boundary['encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and boundary['boot_manifest_sha256']==sha(a.boot/'manifest.json')and boundary['all_existing_effective_flags_preserved']and not boundary['new_flags']
contract=repo/'scripts/runtime/tests/application-cache-startup/MutableApplicationTempDefaults244Contract.java';runner=evidence/'MutableTempDefaults244ContractRunner.java'
assert own['passed']and own['contract_source_sha256']==sha(contract)and own['driver_sha256']==sha(runner)and len(own['results'])==2 and all('checks=23|uid=65534|'in v['marker']and v['cross_uid_read_denied']for v in own['results'])
assert own['actual_component_manifest_sha256']==sha(Path('/var/tmp/saidroid-temp-default244-prototype-v2/root/install-manifest.json'))
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
    v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
install(a.host/'saildroid-host','libexec/saildroid-host',full['files']['libexec/saildroid-host']['mode'])
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/application-temp-default/'+n)
for n in module['sources']['files']:install(source/n,'share/build/application-temp-default/sources/'+n)
for n,v in module['sources']['files'].items():install(repo/v['reference'],'share/build/application-temp-default/references/'+n)
for f in proof_files:install(f,'share/build/application-temp-default/evidence/'+f.name)
for f,n in [(a.host/'manifest.json','host-manifest.json'),(a.host/'source/host-entry.cpp','host-entry.cpp'),(host_builder,'host-builder.py'),(host_patch,'host-entry.patch'),(contract,'tests/Contract.java'),(runner,'tests/ContractRunner.java'),(source/'system-app-temp-default.patch','system-app-temp-default.patch'),(evidence/'audit-original-temp-default244-paired-v1.py','tests/audit-paired.py')]:install(f,'share/build/application-temp-default/'+n)

runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['application_temp_startup']['historical_only']=True
runtime['application_temp_startup']['superseded_by']='application_temp_default_compat'
runtime['application_temp_default_compat']=dict(schema=module['schema'],core_module_manifest_sha256=sha(a.module/'manifest.json'),native_host_manifest_sha256=sha(a.host/'manifest.json'),native_host_sha256=host['binary_sha256'],core_oj_sha256=core_oj,scope='Every ordinary app defaults Java temporaryfiles to actual immutable host appdata/cache; java.io.tmpdir remains mutable, explicit set/clear/nonNull replacement canonical, reset restores private default. No test branches/user.home changes.',original_coupled_tests=163,original_coupled_passed=162,original_coupled_failed=1,original_FileTest_regression_fixed=True,own_apps=2,own_checks=46,cross_uid_read_denied=True,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['application_temp_default_overlay']=dict(schema='saildroid-application-temp-default-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_backend_art_media_manager_trust_bytes_unchanged=True,original_coupled_tests=163,original_coupled_failed=1,original_FileTest_regression_fixed=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('MUTABLE_APPLICATION_TEMP_DEFAULT_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
