#!/usr/bin/env python3
"""Compose the validated JKS/BKS core module and matching encoded boot over an overlay.

The source overlay and all existing product/native/manager files remain unchanged.
This creates a new isolated artifact; it does not stage or activate a device release.
"""
from pathlib import Path
import argparse,copy,hashlib,json,shutil,stat,tarfile
import zipfile
import importlib.util
import os
os.umask(0o022)

parser=argparse.ArgumentParser(description=__doc__)
for name in ['baseline','module','baseline_encoded','encoded','boot','output']:parser.add_argument(name,type=Path)
parser.add_argument('--expected-baseline-sha256',required=True)
a=parser.parse_args();repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256,'Baseline archive changed'
before=json.loads((a.baseline/'overlay.json').read_text())
assert before['schema']=='saildroid-native-overlay-v1'and before['api']==29
full=before['install_manifest'];baseline_root=a.baseline/'payload'
for name,entry in before['changes'].items():
    path=Path(name);assert not path.is_absolute()and '..'not in path.parts
    file=baseline_root/path
    assert file.is_file()and not file.is_symlink()and sha(file)==entry['sha256']
    assert stat.S_IMODE(file.stat().st_mode)==entry['mode']and file.stat().st_size==entry['size']
    assert full['files'][name]==entry
runtime=json.loads((baseline_root/'runtime.json').read_text())
assert runtime['api']==29 and runtime['native_host']and runtime['hidden_api']['policy']=='enabled'
module=json.loads((a.module/'manifest.json').read_text())
assert module['passed']
assert module['builder_sha256']==sha(repo/'scripts/runtime/build-keystore-core-compat-vm.py')
source_meta=repo/'scripts/runtime/core/keystore-compat/sources.json'
assert module['source_meta_sha256']==sha(source_meta)
source=json.loads(source_meta.read_text())
for name,entry in source['files'].items():
    assert sha(source_meta.parent/name)==entry['sha256']
    assert sha(repo/entry['baseline_source'])==entry['baseline_sha256']
assert set(module['components'])=={'core-oj','bouncycastle'}
for name,entry in module['components'].items():assert sha(a.module/(name+'-hostdex.jar'))==entry['sha256']
encoded=json.loads((a.encoded/'manifest.json').read_text())
old_encoded=json.loads((baseline_root/'share/build/hiddenapi-manifest.json').read_text())
assert encoded['schema']==old_encoded['schema']=='saildroid-hiddenapi-v1'
for field in ['canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:
    assert encoded[field]==old_encoded[field],field
assert encoded['unknown_policy']=='implementation-private-blacklist'
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
core={'java/dex/art/core-oj.jar':'core-oj','java/dex/art/bouncycastle-hostdex.jar':'bouncycastle'}
for name,component in core.items():assert encoded['files'][name]['source_sha256']==module['components'][component]['sha256']
changed_jars=[]
for name,entry in encoded['files'].items():
    path=Path(name);assert not path.is_absolute()and '..'not in path.parts
    assert entry['executable_code_unchanged']and sha(a.encoded/name)==entry['sha256']
    assert old_encoded['files'][name]['sha256']==full['files'][name]['sha256']
    if entry['sha256']!=full['files'][name]['sha256']:changed_jars.append(name)
assert set(changed_jars)==set(core),changed_jars
assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
spec=importlib.util.spec_from_file_location('keystore_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py')
encoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(encoder)
added=set()
for name in encoded['files']:
    assert sha(a.baseline_encoded/name)==old_encoded['files'][name]['sha256']
    with zipfile.ZipFile(a.baseline_encoded/name)as z:old,_=encoder.dex_members(z.read('classes.dex'))
    with zipfile.ZipFile(a.encoded/name)as z:new,_=encoder.dex_members(z.read('classes.dex'))
    assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old)
    added.update(set(new)-set(old))
expected={'Lsun/security/provider/JavaKeyStore'+n+';->engineSetEntry(Ljava/lang/String;Ljava/security/KeyStore$Entry;Ljava/security/KeyStore$ProtectionParameter;)V'for n in['','$JKS','$CaseExactJKS']}|{'Lcom/android/org/bouncycastle/crypto/CryptoServicesRegistrar$$ExternalSyntheticBackportWithForwarding0;->m(Ljava/util/concurrent/atomic/AtomicReference;Ljava/lang/Object;Ljava/lang/Object;)Z'}
assert added==expected
flags=lambda d:dict(line.rsplit(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
old_flags=flags(a.baseline_encoded);new_flags=flags(a.encoded)
assert set(new_flags)-set(old_flags)==expected and all(new_flags[n]==v for n,v in old_flags.items())
assert all(new_flags[n]=='blacklist'for n in expected)
recipe=json.loads((a.boot/'recipe.json').read_text());images=json.loads((a.boot/'manifest.json').read_text())
old_images=json.loads((baseline_root/'share/build/boot-image-manifest.json').read_text())
assert images.keys()==old_images.keys()
expected={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert {Path(n).name:v for n,v in recipe['files'].items()}==expected
for name,value in images.items():
    path=Path(name);assert len(path.parts)==2 and path.parts[0]=='arm64'and path.suffix in ['.art','.oat','.vdex']
    assert sha(a.boot/path)==value
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload'
shutil.copytree(baseline_root,root)
# Archive extraction on-device normalizes directories to0755. Normalize the
# source artifact too, so an unprivileged VM can inspect the same complete
# payload and inherited restrictive builder umasks cannot hide native paths.
root.chmod(0o755)
for directory in root.rglob("*"):
    if directory.is_dir():directory.chmod(0o755)
after=copy.deepcopy(before);changes=after['changes'];manifest=after['install_manifest']
updated=[]
def install(source,name,mode=0o644):
    target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
    assert not target.is_symlink();shutil.copyfile(source,target);target.chmod(mode)
    entry=dict(sha256=sha(target),size=target.stat().st_size,mode=mode)
    changes[name]=entry;manifest['files'][name]=entry;assert name not in manifest['symlinks']
    updated.append(name)
for name in sorted(core):install(a.encoded/name,name,full['files'][name]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for name in images:install(a.boot/name,'system/framework/'+name,full['files']['system/framework/'+name]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
install(a.module/'manifest.json','share/build/keystore-core-compat/manifest.json')
install(source_meta,'share/build/keystore-core-compat/sources.json')
install(repo/'scripts/runtime/build-keystore-core-compat-vm.py','share/build/keystore-core-compat/builder.py')
for name in source['files']:install(source_meta.parent/name,'share/build/keystore-core-compat/sources/'+name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json')
runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['keystore_core_compat']=dict(schema='saildroid-keystore-core-compat-v1',manifest_sha256=sha(a.module/'manifest.json'),scope='All applications; restore BKS store-error compatibility and reject unsupported password protection on JKS trusted certificates; provider registry, native declarations and existing hidden API policy retained',native_binaries_unchanged=True)
temporary=a.output/'runtime.json';temporary.write_text(json.dumps(runtime,indent=2)+'\n');install(temporary,'runtime.json');temporary.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert manifest['symlinks']==full['symlinks']and after['product_manifest']==before['product_manifest']
assert {n:v for n,v in manifest['files'].items()if n not in updated}=={n:v for n,v in full['files'].items()if n not in updated}
assert not(set(full['files'])-set(manifest['files']))
for name,entry in changes.items():
    assert sha(root/name)==entry['sha256']and stat.S_IMODE((root/name).stat().st_mode)==entry['mode']
    parts=Path(name).parts
    assert all(str(Path(*parts[:i]))not in manifest['symlinks']for i in range(1,len(parts)))
provenance=dict(schema='saildroid-keystore-core-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,baseline_overlay_sha256=sha(a.baseline/'overlay.json'),source_manifest_sha256=sha(source_meta),core_manifest_sha256=sha(a.module/'manifest.json'),changed_boot_jars=changed_jars,updated_files=sorted(updated),product_manifest_unchanged=True,native_files_unchanged=True,phone_staged=False)
after['keystore_core_overlay']=provenance
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:
    archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
# Close the transaction against concurrent edits to its actual source inputs.
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(a.module/'manifest.json')==provenance['core_manifest_sha256']
assert sha(source_meta)==provenance['source_manifest_sha256']
for name,entry in source['files'].items():assert sha(source_meta.parent/name)==entry['sha256']
assert sha(repo/'scripts/runtime/build-keystore-core-compat-vm.py')==module['builder_sha256']
for name,entry in module['components'].items():assert sha(a.module/(name+'-hostdex.jar'))==entry['sha256']
assert sha(a.encoded/'manifest.json')==runtime['hidden_api']['manifest_sha256']
for name,entry in encoded['files'].items():assert sha(a.encoded/name)==entry['sha256']
assert sha(a.boot/'manifest.json')==runtime['boot_image']['manifest_sha256']
for name,digest in images.items():assert sha(a.boot/name)==digest
print('KEYSTORE_CORE_OVERLAY=packaged|files='+str(len(manifest['files']))+'|sha256='+sha(a.output/'native-overlay.tar.gz'))
