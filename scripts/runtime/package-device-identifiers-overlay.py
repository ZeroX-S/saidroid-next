#!/usr/bin/env python3
"""Compose the opt-in identifier access boundary over a verified v2 overlay.

Only the encoded implementation runtime JAR, its metadata and provenance change.
Original Java boot/native/manager bytes and duplicate-CA removals are retained.
"""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,tarfile
os.umask(0o022);p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline_encoded','encoded','output']:p.add_argument(n,type=Path)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29;full=before['install_manifest'];oldroot=a.baseline/'payload'
for n,v in before['changes'].items():
 f=oldroot/n;r=Path(n);assert not r.is_absolute()and'..'not in r.parts
 assert not f.is_symlink()and sha(f)==v['sha256']and stat.S_IMODE(f.stat().st_mode)==v['mode']and f.stat().st_size==v['size']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['passed']and module['schema']=='saildroid-device-identifiers-compat-v1'and module['builder_sha256']==sha(repo/'scripts/runtime/build-device-identifiers-compat-vm.py')and module['runtime_sha256']==sha(a.module/'runtime.jar');source=repo/'scripts/device/SdServices.java';identifier=repo/'scripts/runtime/device-identifiers-compat/SdDeviceIdentifiers.java';assert module['source_manifest']['baseline_services']==sha(source)and module['source_manifest']['identifiers']==sha(identifier)
expected=source.read_text();needle='        register("trust", SdKeyguard.binder());';assert expected.count(needle)==1;assert(a.module/'source/SdServices.java').read_text()==expected.replace(needle,needle+'\n        register("device_identifiers", SdDeviceIdentifiers.binder());')and sha(a.module/'source/SdServices.java')==module['source_manifest']['prepared_services']
old=json.loads((a.baseline_encoded/'manifest.json').read_text());new=json.loads((a.encoded/'manifest.json').read_text());assert old==json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text())
assert old['files'].keys()==new['files'].keys()
for field in ['canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert old[field]==new[field]
assert new['unknown_policy']=='implementation-private-blacklist'
changed=[]
for n,v in new['files'].items():
 r=Path(n);assert not r.is_absolute()and'..'not in r.parts
 assert old['files'][n]['sha256']==full['files'][n]['sha256']==sha(a.baseline_encoded/n)and sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']
 if v['sha256']!=old['files'][n]['sha256']:changed.append(n)
assert changed==['lib/runtime.jar']and old['files']['lib/runtime.jar']['source_sha256']==module['baseline_runtime_sha256']and new['files']['lib/runtime.jar']['source_sha256']==module['runtime_sha256']
flags=lambda d:dict(line.rsplit(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines());of=flags(a.baseline_encoded);nf=flags(a.encoded);assert all(nf[n]==v for n,v in of.items())and set(nf)-set(of)==set(module['new_members'])and all(nf[n]=='blacklist'for n in module['new_members'])
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir():d.chmod(0o755)
after=copy.deepcopy(before);manifest=after['install_manifest'];changes=after['changes'];updated=[]
def install(file,name,mode=0o644):
 t=root/name;t.parent.mkdir(parents=True,exist_ok=True);assert not t.is_symlink();shutil.copyfile(file,t);t.chmod(mode);v=dict(sha256=sha(t),size=t.stat().st_size,mode=mode);changes[name]=manifest['files'][name]=v;updated.append(name)
install(a.encoded/'lib/runtime.jar','lib/runtime.jar',full['files']['lib/runtime.jar']['mode']);install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json');install(a.module/'manifest.json','share/build/device-identifiers/manifest.json');install(a.module/'source/SdServices.java','share/build/device-identifiers/SdServices.java');install(identifier,'share/build/device-identifiers/SdDeviceIdentifiers.java');install(repo/'scripts/runtime/build-device-identifiers-compat-vm.py','share/build/device-identifiers/builder.py')
runtime=json.loads((oldroot/'runtime.json').read_text());runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['identifier_access_boundary']=dict(schema=module['schema'],module_manifest_sha256=sha(a.module/'manifest.json'),scope=module['scope'],privileged_identifier_backend=False,host_identifiers_read=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert before['remove_files']==after['remove_files']and before['ca_alias_cleanup']==after['ca_alias_cleanup']and before['product_manifest']==after['product_manifest']and full['symlinks']==manifest['symlinks']
assert set(full['files'])<=set(manifest['files'])and all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
for n,v in changes.items():assert sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']
after['device_identifier_overlay']=dict(schema='saildroid-device-identifier-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,module_manifest_sha256=sha(a.module/'manifest.json'),changed_encoded_jars=changed,updated_files=sorted(updated),all_native_boot_manager_bytes_unchanged=True,old_hidden_flags_preserved=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(a.module/'manifest.json')==after['device_identifier_overlay']['module_manifest_sha256']and sha(source)==module['source_manifest']['baseline_services']and sha(identifier)==module['source_manifest']['identifiers']
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('DEVICE_IDENTIFIER_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
