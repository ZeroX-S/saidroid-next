#!/usr/bin/env python3
"""Package the verified real Linux JNI numeric resolver over a private component.

Java, ART, boot images, Bionic shim, media, manager and trust bytes remain exact.
This creates an isolated artifact and never stages or activates it on a device.
"""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,subprocess,tarfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','native','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022)
repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();evidence=repo/'build/evidence/cts-frame-repair-20261031'
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
build=json.loads((a.native/'manifest.json').read_text());builder=repo/'native/compat/build-numeric-resolver-vm.py';source=repo/'native/compat/resolver';meta=json.loads((source/'sources.json').read_text())
assert build['schema']=='saildroid-libcore-numeric-resolver-v1'and build['passed']and build['shared_tree_unchanged']and build['all_previous_dynamic_symbols_preserved']and build['all_defined_exports_identical']and build['added_imports']==['U snprintf@GLIBC_2.17']
assert sha(builder)==build['builder_sha256']and sha(a.native/'libjavacore.so')==build['library_sha256']and full['files']['lib/libjavacore.so']['sha256']==build['baseline_library_sha256']
assert meta['schema']=='saildroid-libcore-numeric-resolver-sources-v1'and sha(repo/meta['header']['path'])==meta['header']['sha256']==build['header_sha256']
assert sha(repo/meta['baseline_portability']['path'])==meta['baseline_portability']['sha256']==build['baseline_portability_sha256']
for v in meta['references'].values():assert sha(repo/v['path'])==v['sha256']
def symbols(f):return set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
oldsymbols=symbols(oldroot/'lib/libjavacore.so');newsymbols=symbols(a.native/'libjavacore.so');assert not oldsymbols-newsymbols and newsymbols-oldsymbols=={'U snprintf@GLIBC_2.17'}
proofs=[evidence/n for n in ['original-resolver208-paired-v1-audit.json','resolver208-own-contract-v3.json','resolver208-icu-preservation-v1.json','resolver208-os-regression-v1-audit.json']]
original,own,icu,osproof=[json.loads(p.read_text())for p in proofs]
assert original['accepted_comparison']and original['tests']==56 and original['before_fail']==17 and original['after_fail']==0
assert sha(evidence/'original-resolver208-selected-v3.json')==original['raw_paired_sha256']and sha(proofs[1])==original['own_contract_sha256']
assert original['new_javacore_sha256']==own['new_native_sha256']==icu['library_sha256']==osproof['new_javacore_sha256']==build['library_sha256']
assert original['old_javacore_sha256']==own['old_native_sha256']==build['baseline_library_sha256']
assert original['actual_core_sha256']==full['files']['java/dex/art/core-libart.jar']['sha256']and original['actual_boot_manifest_sha256']==sha(oldroot/'share/build/boot-image-manifest.json')
assert own['passed']and 'checks=6177|'in own['results'][1]['marker']and sha(repo/'scripts/runtime/tests/resolver/NumericResolverContract.java')==own['source_sha256']
assert icu['passed']and all(sha(repo/n)==h for n,h in icu['sources'].items())and osproof['accepted_no_regression']and osproof['after_fail']==osproof['before_fail']==3
assert sha(evidence/'original-resolver208-os-regression-v1.json')==osproof['raw_paired_sha256']
oldicu=json.loads((oldroot/'share/build/native-icu/manifest.json').read_text());assert oldicu['schema']=='saildroid-native-icu-os-extended-io-v3'
assert all(full['files']['lib/'+n]['sha256']==v['sha256']for n,v in oldicu['files'].items())
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 t=root/n;t.parent.mkdir(parents=True,exist_ok=True);assert not t.is_symlink();shutil.copyfile(f,t);t.chmod(mode);v=dict(sha256=sha(t),size=t.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
def generated(value,n):
 t=a.output/'generated.json';t.write_text(json.dumps(value,indent=2)+'\n');install(t,n);t.unlink()
install(a.native/'libjavacore.so','lib/libjavacore.so',full['files']['lib/libjavacore.so']['mode'])
for f,n in [(a.native/'manifest.json','native-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(source/'libcore-numeric-host.h','libcore-numeric-host.h'),(Path(__file__),'packager.py'),(repo/'scripts/runtime/tests/resolver/NumericResolverContract.java','tests/NumericResolverContract.java')]:install(f,'share/build/numeric-resolver/'+n)
for f in proofs:install(f,'share/build/numeric-resolver/evidence/'+f.name)
for n,v in meta['references'].items():install(repo/v['path'],'share/build/numeric-resolver/references/'+n)
install(oldroot/'share/build/native-icu/manifest.json','share/build/native-icu/base-manifest-before-numeric-resolver.json')
newicu=copy.deepcopy(oldicu);newicu.update(schema='saildroid-native-icu-numeric-resolver-v4',base_manifest_sha256=sha(oldroot/'share/build/native-icu/manifest.json'),base_manifest_path='share/build/native-icu/base-manifest-before-numeric-resolver.json',numeric_resolver_manifest_sha256=sha(a.native/'manifest.json'),actual_native_icu_regression_sha256=sha(proofs[2]))
newicu['files']['libjavacore.so']=dict(sha256=build['library_sha256'],bytes=(a.native/'libjavacore.so').stat().st_size,dynamic=build['dynamic']);generated(newicu,'share/build/native-icu/manifest.json')
runtime=json.loads((oldroot/'runtime.json').read_text());runtime['private_native_icu'].update(schema=newicu['schema'],manifest_sha256=sha(root/'share/build/native-icu/manifest.json'),scope='All apps; actual ICU63 and layered Linux JNI behavior, real splice and numeric-host adapter')
for section,key in [('socket_flags_api29','native_library_sha256'),('linux_io_compat','library_sha256')]:
 assert runtime[section][key]==build['baseline_library_sha256'];runtime[section][key]=build['library_sha256']
runtime['os_extended_io']['current_native_library_sha256']=build['library_sha256']
runtime['numeric_resolver']=dict(schema=build['schema'],library_sha256=build['library_sha256'],manifest_sha256=sha(a.native/'manifest.json'),scope=meta['scope'],original_selected_passed=56,original_selected_failed=0,phone_staged=False)
generated(runtime,'runtime.json');manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert manifest['symlinks']==full['symlinks']and set(full['files'])<=set(manifest['files'])and all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert after[k]==before[k]
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['numeric_resolver_overlay']=dict(schema='saildroid-numeric-resolver-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_java_boot_art_bionic_shim_media_manager_trust_bytes_unchanged=True,all_old_dynamic_symbols_preserved=True,added_imports=build['added_imports'],phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(a.native/'libjavacore.so')==build['library_sha256']and sha(builder)==build['builder_sha256']and sha(source/'libcore-numeric-host.h')==build['header_sha256']
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('NUMERIC_RESOLVER_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
