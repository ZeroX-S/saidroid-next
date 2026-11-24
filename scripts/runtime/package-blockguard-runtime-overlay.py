#!/usr/bin/env python3
"""Package verified real BlockGuard, stream open and Runtime.gc policy compatibility."""
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
assert before['schema']=='saildroid-native-overlay-v2' and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
    f=oldroot/n;assert not Path(n).is_absolute() and '..'not in Path(n).parts
    assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-blockguard-compat-v1'and module['passed']
builder=repo/'scripts/runtime/build-blockguard-compat-vm.py';source=repo/'scripts/runtime/core/blockguard-compat'
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():
    assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
for key,core in module['components'].items():
    assert sha(a.module/(key+'-hostdex.jar'))==core['sha256']and sha(a.module/(key+'-classes.jar'))==core['class_jar_sha256']
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
    assert set(old)<=set(new)and all(old[k][0]==new[k][0]for k in old)
    assert {k:v[0]for k,v in old.items()if v[0]&0x100}=={k:v[0]for k,v in new.items()if v[0]&0x100}
    added|=set(new)-set(old)
    if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
assert set(changed)=={'java/dex/art/core-libart.jar','java/dex/art/core-oj.jar'}and len(added)==6 and added=={v for c in module['components'].values()for v in c['added_members']}
for key,core in module['components'].items():assert encoded['files']['java/dex/art/'+key+'.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_files=[evidence/n for n in ['original-blockguard209-paired-v1-audit.json','original-runtime210-paired-v1-audit.json','runtime210-own-contract-v1.json']]
prior,original,own=[json.loads(f.read_text())for f in proof_files]
assert prior['accepted_comparison']and prior['tests']==57 and prior['before_fail']==7 and prior['after_fail']==1
assert original['accepted_comparison']and original['tests']==57 and original['before_fail']==1 and original['after_fail']==0 and own['passed']and 'checks=31|'in own['results'][1]['marker']and 'real_gc_delta=7|'in own['results'][1]['marker']
assert sha(evidence/'original-blockguard209-selected-v4.json')==prior['raw_paired_sha256']and sha(evidence/'original-runtime210-selected-v1.json')==original['raw_paired_sha256']and sha(proof_files[0])==original['prior_comparison_sha256']and sha(proof_files[2])==original['own_contract_sha256']
for key in ['core-oj','core-libart']:assert original['actual_'+key.replace('-','_')+'_sha256']==encoded['files']['java/dex/art/'+key+'.jar']['sha256']
assert original['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')and original['actual_javacore_sha256']==full['files']['lib/libjavacore.so']['sha256']
native=json.loads((a.native/'manifest.json').read_text());nbuilder=repo/'native/compat/build-runtime-gc-policy-vm.py';nsource=repo/'native/compat/runtime-policy/runtime-gc.c'
assert native['schema']=='saildroid-runtime-gc-policy-native-v1'and native['passed']and native['baseline_rebuild_byte_identical']and native['baseline_openjdk_registration_preemptable']and native['all_previous_dynamic_symbols_preserved']and native['added_exports']==['Runtime_gc']and native['needed_identical']
assert sha(nbuilder)==native['builder_sha256']and sha(nsource)==native['source_sha256']and sha(a.native/'libsdhost29.so')==native['library_sha256']==original['actual_new_host_sha256']==own['new_native_sha256']
symbols=lambda f:set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
old_symbols,new_symbols=symbols(oldroot/'lib/libsdhost29.so'),symbols(a.native/'libsdhost29.so');assert not old_symbols-new_symbols and new_symbols-old_symbols=={'T Runtime_gc'}
assert native['baseline_library_sha256']==full['files']['lib/libsdhost29.so']['sha256']==original['actual_old_host_sha256']==own['old_native_sha256']
assert all(sha(repo/n)==h for n,h in native['sources'].items())and sha(repo/'scripts/runtime/tests/runtime-policy/RuntimeGcPolicyContract.java')==own['source_sha256']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
    v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
install(a.native/'libsdhost29.so','lib/libsdhost29.so',full['files']['lib/libsdhost29.so']['mode'])
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/blockguard-runtime/'+n)
for n in module['sources']['files']:install(source/n,'share/build/blockguard-runtime/sources/'+n)
for n,v in module['sources']['files'].items():install(repo/v['reference'],'share/build/blockguard-runtime/references/'+n)
for f,n in [(a.native/'manifest.json','native-manifest.json'),(nbuilder,'native-builder.py'),(nsource,'runtime-gc.c'),(repo/'scripts/runtime/tests/runtime-policy/RuntimeGcPolicyContract.java','tests/RuntimeGcPolicyContract.java')]:install(f,'share/build/blockguard-runtime/'+n)
for f in proof_files:install(f,'share/build/blockguard-runtime/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['blockguard_runtime_compat']=dict(schema='saildroid-blockguard-runtime-compat-v1',core_module_manifest_sha256=sha(a.module/'manifest.json'),native_manifest_sha256=sha(a.native/'manifest.json'),current_native_host_sha256=native['library_sha256'],selected_original_tests=57,selected_original_passed=57,full_module_passed=False,original_libopenjdk_registration_and_backend_retained=True)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['blockguard_runtime_overlay']=dict(schema='saildroid-blockguard-runtime-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_other_native_art_media_manager_trust_bytes_unchanged=True,original_selected_tests=57,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
assert sha(nbuilder)==native['builder_sha256']and sha(nsource)==native['source_sha256']and sha(a.native/'libsdhost29.so')==native['library_sha256']
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('BLOCKGUARD_RUNTIME_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
