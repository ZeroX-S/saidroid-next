#!/usr/bin/env python3
"""Package verified canonical ZIP/GZIP Java behavior and actual direct-array native ZIP reader."""
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
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-zip-compat-v1'and module['passed']
builder=repo/'scripts/runtime/build-zip-compat-vm.py';source=repo/'scripts/runtime/core/zip-compat'
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
assert set(changed)=={'java/dex/art/core-oj.jar'}and len(added)==0 and added=={v for c in module['components'].values()for v in c['added_members']}
for key,core in module['components'].items():assert encoded['files']['java/dex/art/'+key+'.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_files=[evidence/n for n in ['original-zip216-paired-v2-audit.json','zip216-own-contract-v3.json']]
original,own=[json.loads(f.read_text())for f in proof_files]
assert original['accepted_comparison']and original['tests']==67 and original['before_fail']==5 and original['after_fail']==2 and original['after_pass']==65 and not original['full_module_passed']
assert own['passed']and 'checks=181|'in own['marker']and sha(evidence/'original-zip216-selected-v2.json')==original['raw_paired_sha256']
assert own['source_meta_sha256']==sha(source/'sources.json')and own['source_sha256']==sha(repo/'scripts/runtime/tests/zip/ZipCompatibilityContract.java')
assert original['actual_new_core_oj_sha256']==own['actual_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']
assert original['actual_new_core_libart_sha256']==full['files']['java/dex/art/core-libart.jar']['sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']
assert original['actual_new_boot_manifest_sha256']==own['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')
assert original['actual_new_encoded_manifest_sha256']==own['actual_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
assert original['actual_old_runtime_sha256']==original['actual_new_runtime_sha256']==own['actual_new_runtime_sha256']==full['files']['lib/runtime.jar']['sha256']
assert original['actual_javacore_sha256']==full['files']['lib/libjavacore.so']['sha256']
native=json.loads((a.native/'manifest.json').read_text());nbuilder=repo/'native/compat/build-zip-read-vm.py';nsource=repo/'native/compat/zip/zip-read.c';nsmeta=repo/'native/compat/zip/sources.json';ns=json.loads(nsmeta.read_text())
assert native['schema']=='saildroid-zip-read-native-v1'and native['passed']and native['baseline_rebuild_byte_identical']and native['baseline_openjdk_registration_preemptable']and native['all_previous_dynamic_symbols_preserved']and native['added_exports']==['ZipFile_read']and native['needed_identical']
assert sha(nbuilder)==native['builder_sha256']and sha(nsource)==native['source_sha256']==ns['adapter_sha256']and sha(a.native/'libsdhost29.so')==native['library_sha256']==original['actual_new_host_sha256']==own['actual_native_host_sha256']
assert sha(a.native/'manifest.json')==own['native_manifest_sha256']
assert sha(repo/ns['reference'])==ns['reference_sha256']and sha(repo/ns['reference_manifest'])==ns['reference_manifest_sha256']and sha(repo/ns['baseline_source'])==ns['baseline_source_sha256']
symbols=lambda f:set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
old_symbols,new_symbols=symbols(oldroot/'lib/libsdhost29.so'),symbols(a.native/'libsdhost29.so');assert not old_symbols-new_symbols and new_symbols-old_symbols=={'T ZipFile_read'}
assert native['baseline_library_sha256']==full['files']['lib/libsdhost29.so']['sha256']==original['actual_old_host_sha256']
assert all(sha(repo/n)==h for n,h in native['sources'].items())
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
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/zip-compat/'+n)
for n in module['sources']['files']:install(source/n,'share/build/zip-compat/sources/'+n)
for n,v in module['sources']['files'].items():install(repo/v['reference'],'share/build/zip-compat/references/'+n)
for f,n in [(a.native/'manifest.json','native-manifest.json'),(nbuilder,'native-builder.py'),(nsource,'zip-read.c'),(nsmeta,'native-sources.json'),(repo/ns['reference'],'references/ZipFile.c'),(repo/ns['reference_manifest'],'references/native-reference-manifest.json'),(repo/'scripts/runtime/tests/zip/ZipCompatibilityContract.java','tests/ZipCompatibilityContract.java')]:install(f,'share/build/zip-compat/'+n)
for f in proof_files:install(f,'share/build/zip-compat/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['zip_compat']=dict(schema=module['schema'],core_module_manifest_sha256=sha(a.module/'manifest.json'),native_manifest_sha256=sha(a.native/'manifest.json'),current_native_host_sha256=native['library_sha256'],selected_original_tests=67,selected_original_passed=65,selected_original_failed=2,own_checks=181,full_module_passed=False,original_libopenjdk_registration_and_backend_retained=True)
runtime['blockguard_runtime_compat']['current_native_host_sha256']=native['library_sha256']
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['zip_compat_overlay']=dict(schema='saildroid-zip-compat-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_other_native_art_media_manager_trust_bytes_unchanged=True,original_selected_tests=67,original_selected_passed=65,original_selected_failed=2,own_checks=181,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
assert sha(nbuilder)==native['builder_sha256']and sha(nsource)==native['source_sha256']and sha(a.native/'libsdhost29.so')==native['library_sha256']
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('ZIP_COMPAT_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
