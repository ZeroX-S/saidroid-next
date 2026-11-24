#!/usr/bin/env python3
"""Package verified realpath/splice/native constants as a new isolated artifact.

No device writes or activation. Old Java/native members and all unrelated
product, framework, ART, media, trust and manager bytes remain unchanged.
"""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,stat,tarfile,zipfile

p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','native','output']:
    p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
    f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
    assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text())
assert module['schema']=='saildroid-os-extended-io-v1'and module['passed']
core_builder=repo/'scripts/runtime/build-os-extended-io-vm.py';source=repo/'scripts/runtime/core/os-extended-io';source_meta=source/'sources.json'
assert sha(core_builder)==module['builder_sha256']and sha(source_meta)==module['source_meta_sha256']
for n,v in module['sources']['files'].items():
    assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
core=module['components']['core-libart'];assert sha(a.module/'core-libart-hostdex.jar')==core['sha256']
native=json.loads((a.native/'manifest.json').read_text());assert native['schema']=='saildroid-os-extended-io-native-v1'and native['passed']and native['shared_tree_unchanged']and native['all_previous_dynamic_symbols_preserved']
native_builder=repo/'native/compat/build-os-extended-io-vm.py';assert sha(native_builder)==native['builder_sha256']
assert sha(a.native/'libjavacore.so')==native['library_sha256']and full['files']['lib/libjavacore.so']['sha256']==native['baseline_library_sha256']
assert len(native['added_dynamic_symbols'])==1 and next(iter(native['added_dynamic_symbols'])).split('@')[0]=='splice'
patchfiles=[]
for n,v in native['patches'].items():
    # Resolve the actual pinned patch, never select a newest file by timestamp.
    matches=[f for f in(repo/'native/compat/patches').glob('*.patch')if sha(f)==v['patch_sha256']]
    assert len(matches)==1;patch=matches[0]
    assert sha(patch.with_suffix('.source.json'))==v['patch_source_manifest_sha256']
    assert sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
    patchfiles.extend([patch,patch.with_suffix('.source.json')])
encoded=json.loads((a.encoded/'manifest.json').read_text());old_encoded=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text())
assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old_encoded[k]
runtime=json.loads((oldroot/'runtime.json').read_text());assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('os_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
added=set();changed=[]
for n,v in encoded['files'].items():
    assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']
    assert sha(a.baseline_encoded/n)==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']
    with zipfile.ZipFile(a.baseline_encoded/n)as z:old,_=enc.dex_members(z.read('classes.dex'))
    with zipfile.ZipFile(a.encoded/n)as z:new,_=enc.dex_members(z.read('classes.dex'))
    assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old)
    added|=set(new)-set(old)
    if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
assert changed==['java/dex/art/core-libart.jar']and added==set(core['added_members'])and len(added)==10
assert encoded['files'][changed[0]]['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proofs=[evidence/n for n in ['original-os199-paired-v1-audit.json','os199-kernel-contract-v2.json','native199-icu-preservation-v1.json']]
original,own,icu=[json.loads(f.read_text())for f in proofs]
assert original['accepted_product_changes']and not original['full_class_passed']and original['after_pass']==55 and original['after_fail']==2
assert own['passed']and icu['passed']and icu['library_sha256']==native['library_sha256']
for d in [original,own]:
    assert d['actual_core_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']and d['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')and d['actual_native_sha256']==native['library_sha256']
for n,h in own['sources'].items():assert sha(repo/n)==h
oldicu=json.loads((oldroot/'share/build/native-icu/manifest.json').read_text());assert oldicu['schema']=='saildroid-native-icu-linux-io-v2'
for n,v in oldicu['files'].items():assert full['files']['lib/'+n]['sha256']==v['sha256']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
    entry=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=entry;updated.append(n)
def generated(value,n):
    f=a.output/'generated.json';f.write_text(json.dumps(value,indent=2)+'\n');install(f,n);f.unlink()
install(a.encoded/'java/dex/art/core-libart.jar','java/dex/art/core-libart.jar',full['files']['java/dex/art/core-libart.jar']['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
install(a.native/'libjavacore.so','lib/libjavacore.so',full['files']['lib/libjavacore.so']['mode'])
for f,n in [(a.module/'manifest.json','core-manifest.json'),(a.native/'manifest.json','native-manifest.json'),(source_meta,'sources.json'),(core_builder,'core-builder.py'),(native_builder,'native-builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/os-extended-io/'+n)
for n in module['sources']['files']:install(source/n,'share/build/os-extended-io/sources/'+n)
for f in patchfiles:install(f,'share/build/os-extended-io/patches/'+f.name)
for f in proofs:install(f,'share/build/os-extended-io/evidence/'+f.name)
install(oldroot/'share/build/native-icu/manifest.json','share/build/native-icu/base-manifest-before-extended-io.json')
newicu=copy.deepcopy(oldicu);newicu.update(schema='saildroid-native-icu-os-extended-io-v3',base_manifest_sha256=sha(oldroot/'share/build/native-icu/manifest.json'),base_manifest_path='share/build/native-icu/base-manifest-before-extended-io.json',os_extended_io_manifest_sha256=sha(a.native/'manifest.json'),actual_native_icu_regression_sha256=sha(proofs[2]))
newicu['old_native_socket_constant_object_retained']=False
newicu['previous_socket_flag_initializers_retained']=True
newicu['added_dynamic_imports']=native['added_dynamic_symbols']
newicu['files']['libjavacore.so']=dict(sha256=native['library_sha256'],bytes=(a.native/'libjavacore.so').stat().st_size,dynamic=native['dynamic'])
generated(newicu,'share/build/native-icu/manifest.json')
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['private_native_icu'].update(schema=newicu['schema'],manifest_sha256=sha(root/'share/build/native-icu/manifest.json'),scope='All apps; actual ICU63 plus layered original Android10 Linux behavior and real splice/native constants')
assert runtime['socket_flags_api29']['native_library_sha256']==native['baseline_library_sha256'];runtime['socket_flags_api29']['native_library_sha256']=native['library_sha256']
runtime['linux_io_compat']['base_manifest_sha256']=runtime['linux_io_compat'].pop('manifest_sha256')
runtime['linux_io_compat'].update(schema='saildroid-linux-io-extended-v2',base_library_sha256=native['baseline_library_sha256'],library_sha256=native['library_sha256'],extension_manifest_sha256=sha(a.native/'manifest.json'))
runtime['os_extended_io']=dict(schema=module['schema'],core_manifest_sha256=sha(a.module/'manifest.json'),native_manifest_sha256=sha(a.native/'manifest.json'),scope='All apps; original Android10 realpath/splice adapters/native operation/BlockGuard callbacks and4 actual kernel constants; existing hidden API policy retained',original_whole_class_passed=False)
generated(runtime,'runtime.json');manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert manifest['symlinks']==full['symlinks']and set(full['files'])<=set(manifest['files'])
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert after[k]==before[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['os_extended_io_overlay']=dict(schema='saildroid-os-extended-io-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_other_framework_java_art_media_manager_trust_bytes_unchanged=True,original_selected_passed=55,original_selected_failed=2,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(a.native/'libjavacore.so')==native['library_sha256']and sha(core_builder)==module['builder_sha256']and sha(native_builder)==native['builder_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('OS_EXTENDED_IO_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
