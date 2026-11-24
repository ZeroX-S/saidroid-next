#!/usr/bin/env python3
"""Package SDK1..29 genuinely-absent-IV PBE compatibility over exact269; no default promotion."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, stat, tarfile, zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','output']:
    p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
p.add_argument('--content-pool',type=Path)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text())
assert before['schema']=='saildroid-native-overlay-v3' and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
    f=oldroot/n;assert not Path(n).is_absolute() and '..'not in Path(n).parts
    assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-pbe-api29-compat-v2'and module['passed']and module['unmodified_classfiles_byte_identical']
builder=repo/'scripts/runtime/build-pbe-api29-compat-v2-vm.py';source=repo/'scripts/runtime/core/pbe-api29-compat-v2'
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(source/'pbe-api29.patch')==v['patch_sha256']and sha(repo/v['reference'])==v['reference_sha256']
for k,c in module['components'].items():
    assert sha(a.module/(k+'-hostdex.jar'))==c['sha256']and sha(a.module/(k+'-classes.jar'))==c['class_jar_sha256']and c['all_existing_member_flags_and_native_declarations_preserved']
assert not module['components']['bouncycastle']['added_members']and module['components']['bouncycastle']['changed_classes']==['com/android/org/bouncycastle/jcajce/provider/symmetric/util/BaseBlockCipher.class']
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
assert changed==['java/dex/art/bouncycastle-hostdex.jar']and added=={n for c in module['components'].values()for n in c['added_members']}
assert encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['source_sha256']==module['components']['bouncycastle']['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==27 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_names=['pbe-api29274-paired-v1-audit.json','pbe-api29274-encoded-v2-boundary.json','pbe-api29274-own-v5.json','pbe-api29274-module-v2-boundary-v1.json','pbe-api29274-v1-nondeployable-audit.json']
proof_files=[evidence/n for n in proof_names]
audit,boundary,own,module_boundary,quarantine=[json.loads(f.read_text())for f in proof_files]
assert audit['passed'] and audit['whole_classes']==15 and audit['tests']==204 and audit['before_pass']==200 and audit['before_fail']==4 and audit['after_pass']==201 and audit['after_fail']==3
assert audit['fixed_original_tests']==['com.android.org.conscrypt.javax.crypto.CipherTest#test_PBKDF2WITHHMACSHA1_SKFactory_and_PBEAESCBC_Cipher_noIV']
assert len(audit['retained_original_failures'])==3 and audit['all_cleanup_safe'] and audit['expected_main_original_id_set_exact'] and not audit['full_module_passed'] and not audit['phone_executed']
driver=evidence/'run-original-pbe-api29274-coupled-v1-vm.py';assert sha(driver)==audit['driver_sha256']
for label,digest in audit['raw_results'].items():
    raw=evidence/('original-pbe-api29274-'+label+'-v1.json');assert sha(raw)==digest
assert boundary['passed']and boundary['core_module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['changed_jars']==changed and boundary['encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and boundary['boot_manifest_sha256']==sha(a.boot/'manifest.json')and boundary['all_existing_effective_flags_preserved']and not boundary['new_flags']and not added
assert module_boundary['passed']and module_boundary['module_manifest_sha256']==sha(a.module/'manifest.json')and sha(proof_files[3])==audit['module_boundary_sha256']and module_boundary['nested_classfiles_retained_byte_identical']and module_boundary['no_added_members']and module_boundary['own_actual_after_checks']==321
contract=repo/'scripts/runtime/tests/pbe-api29/PbeApi29Contract.java';runner=repo/'scripts/runtime/tests/pbe-api29/PbeApi29ContractRunner.java'
assert own['passed']and own['actual_nonroot']and own['source_sha256']==sha(contract)and own['runner_source_sha256']==sha(runner)and own['product_source_meta_sha256']==module['source_meta_sha256']and audit['own_contract_sha256']==sha(proof_files[2])and audit['own_actual_after_checks']==321
assert own['results'][0]['returncode']!=0 and own['results'][0]['sdk']==29
assert [v['sdk']for v in own['results'][1:]]==[0,1,28,29,30,35]and all(v['returncode']==0 and v['marker'].startswith('PBE_API29274_CONTRACT=PASS|')for v in own['results'][1:])
assert module['nested_classfiles_retained_byte_identical']and all(module['nested_executable_members_identical'].values())
frozen=json.loads((evidence/'original-pbe-api29274-coupled-v1-frozen-inputs.json').read_text());assert all(sha(repo/n)==h for n,h in frozen['sources'].items())and all(sha(evidence/n)==h for n,h in frozen['proofs'].items())
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root,copy_function=os.link);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink()
    if target.exists():target.unlink()
    pooled=a.content_pool/n if a.content_pool else None
    if pooled and pooled.is_file()and not pooled.is_symlink()and pooled.stat().st_size==f.stat().st_size and sha(pooled)==sha(f)and stat.S_IMODE(pooled.stat().st_mode)==mode:
        os.link(pooled,target)
    else:
        shutil.copyfile(f,target);target.chmod(mode)
    v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/pbe-api29/'+n)
for n,v in module['sources']['files'].items():
    install(source/n,'share/build/pbe-api29/sources/'+n);install(source/'pbe-api29.patch','share/build/pbe-api29/pbe-api29.patch');install(repo/v['reference'],'share/build/pbe-api29/reference/BaseBlockCipher.java')
for f in proof_files:install(f,'share/build/pbe-api29/evidence/'+f.name)
for f,n in [(contract,'tests/Contract.java'),(runner,'tests/ContractRunner.java'),(evidence/'audit-pbe-api29274-paired-v1.py','tests/audit-paired.py'),(evidence/'run-pbe-api29274-own-v5-vm.py','tests/run-own.py'),(driver,'tests/run-original.py')]:install(f,'share/build/pbe-api29/'+n)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['pbe_api29_compat']=dict(schema=module['schema'],module_manifest_sha256=sha(a.module/'manifest.json'),sdk_min=1,sdk_max=29,genuinely_absent_iv_only=True,nested_provided_iv_strict=True,unknown_and_modern_sdk_strict=True,canonical_deprecation_warnings=True,original_whole_class_tests=204,original_whole_class_failures=3,own_after_checks=321,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['pbe_api29_overlay']=dict(schema='saildroid-pbe-api29-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_art_media_manager_trust_cli_bytes_unchanged=True,original_whole_class_tests=204,original_whole_class_failures=3,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
assert not any(p.is_symlink()for p in root.rglob('*'))
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz',dereference=True)as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','r:gz')as archive:
    members=archive.getmembers();assert all(m.isfile()or m.isdir()for m in members),'V3 requires regular files/directories, never archive hardlinks'
    assert len([m for m in members if m.isfile()])==len(changes)+1
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert all(sha(oldroot/n)==v['sha256']and stat.S_IMODE((oldroot/n).stat().st_mode)==v['mode']for n,v in before['changes'].items())
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('PBE_API29_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
