#!/usr/bin/env python3
"""Package real component hosts configuration and the verified Linux JNI lookup adapter."""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,subprocess,tarfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','native','data','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();b=repo/'build/evidence/cts-frame-repair-20261031'
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29;oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
build=json.loads((a.native/'manifest.json').read_text());builder=repo/'native/compat/build-component-hosts-vm.py'
assert build['schema']=='saildroid-component-hosts-native-v1'and build['passed']and build['shared_tree_unchanged']and build['all_previous_dynamic_symbols_preserved']and build['all_defined_exports_identical']and build['needed_identical']
assert sha(builder)==build['builder_sha256']and all(sha(repo/n)==h for n,h in build['headers'].items())and sha(a.native/'libjavacore.so')==build['library_sha256']and build['baseline_library_sha256']==full['files']['lib/libjavacore.so']['sha256']
def symbols(f):return set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
oldsymbols=symbols(oldroot/'lib/libjavacore.so');newsymbols=symbols(a.native/'libjavacore.so');assert not oldsymbols-newsymbols and newsymbols-oldsymbols==set(build['added_imports'])
data=json.loads((a.data/'manifest.json').read_text());assert sha(a.data/'hosts')==data['sha256']and(a.data/'hosts').stat().st_size==data['bytes']and data['source_path']=='/system/etc/hosts'and data['image_sha256']=='3292f3ab677b975e51566e53355ae9c268e17b86888a9a8b40f8e6c3372fc26c'
assert(a.data/'hosts').read_bytes()==b'127.0.0.1       localhost\n::1             ip6-localhost\n'
proofs=[b/n for n in ['original-component-hosts224-selected-v1-audit.json','original-component-hosts224-resolver-regression-v1-audit.json','component-hosts224-own-contract-v1.json','component-hosts224-native-contract-v1.json','component-hosts224-original-namespace-v1.json','component-hosts224-own-namespace-v1.json','component-hosts224-layout-env-v1.json']]
tls,resolver,own,native,tlsns,ownns,layout=[json.loads(p.read_text())for p in proofs]
for proof,count,assumptions in [(tls,180,2),(resolver,56,0)]:
 assert proof['accepted_no_regression']and proof['tests']==count and proof['before_fail']==proof['after_fail']==0 and proof['before_assumptions']==proof['after_assumptions']==assumptions and not proof['full_module_passed']and proof['actual_new_javacore_sha256']==build['library_sha256']and proof['native_manifest_sha256']==sha(a.native/'manifest.json')
 assert proof['actual_art_sha256']==full['files']['lib/libart.so']['sha256']and proof['actual_native_host_sha256']==full['files']['lib/libsdhost29.so']['sha256']
for proof,raw in [(tls,'original-component-hosts224-selected-v1.json'),(resolver,'original-component-hosts224-resolver-regression-v1.json')]:assert proof['raw_paired_sha256']==sha(b/raw)
assert own['passed']and'checks=245|'in own['marker']and own['source_sha256']==sha(repo/'scripts/runtime/tests/private-hosts/ComponentHostsContract.java')and own['actual_new_javacore_sha256']==build['library_sha256']and own['actual_native_manifest_sha256']==sha(a.native/'manifest.json')
assert own['actual_core_oj_sha256']==full['files']['java/dex/art/core-oj.jar']['sha256']and own['actual_core_libart_sha256']==full['files']['java/dex/art/core-libart.jar']['sha256']and own['actual_boot_manifest_sha256']==sha(oldroot/'share/build/boot-image-manifest.json')and own['actual_encoded_manifest_sha256']==sha(oldroot/'share/build/hiddenapi-manifest.json')and own['actual_new_runtime_sha256']==full['files']['lib/runtime.jar']['sha256']and own['actual_art_sha256']==full['files']['lib/libart.so']['sha256']
assert native['passed']and len(native['cases'])==12 and all(v['passed']for v in native['cases'])and native['headers']==build['headers']and native['source_sha256']==sha(repo/'native/compat/tests/private-hosts/resolver-contract.cpp')
assert tlsns['passed']and ownns['passed']and tlsns['global_parent_files_unchanged']and ownns['global_parent_files_unchanged']
assert layout['passed']and layout['hosts_source_manifest_sha256']==sha(a.data/'manifest.json')and own['layout_manifest_sha256']==tls['actual_layout_manifest_sha256']==resolver['actual_layout_manifest_sha256']==sha(proofs[-1])and layout['files']['system/etc/hosts']==data['sha256']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 t=root/n;t.parent.mkdir(parents=True,exist_ok=True);assert not t.is_symlink();shutil.copyfile(f,t);t.chmod(mode);v=dict(sha256=sha(t),size=t.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
def generated(value,n):
 t=a.output/'metadata.pending.json';t.write_text(json.dumps(value,indent=2)+'\n');install(t,n);t.unlink()
install(a.native/'libjavacore.so','lib/libjavacore.so',full['files']['lib/libjavacore.so']['mode']);install(a.data/'hosts','system/etc/hosts')
for f,n in [(a.native/'manifest.json','native-manifest.json'),(builder,'builder.py'),(Path(__file__),'packager.py'),(a.data/'manifest.json','hosts-source.json'),(a.native/'source/Portability.h','native-source/Portability.h'),(repo/'scripts/runtime/tests/private-hosts/ComponentHostsContract.java','tests/ComponentHostsContract.java'),(repo/'native/compat/tests/private-hosts/resolver-contract.cpp','tests/resolver-contract.cpp')]:install(f,'share/build/component-hosts/'+n)
for n in build['headers']:install(repo/n,'share/build/component-hosts/provenance/'+n)
for f in proofs:install(f,'share/build/component-hosts/evidence/'+f.name)
oldicu=json.loads((oldroot/'share/build/native-icu/manifest.json').read_text());assert oldicu['files']['libjavacore.so']['sha256']==build['baseline_library_sha256'];install(oldroot/'share/build/native-icu/manifest.json','share/build/native-icu/base-manifest-before-component-hosts.json')
icu=copy.deepcopy(oldicu);icu.update(schema='saildroid-native-icu-component-hosts-v6',base_manifest_sha256=sha(oldroot/'share/build/native-icu/manifest.json'),base_manifest_path='share/build/native-icu/base-manifest-before-component-hosts.json',component_hosts_manifest_sha256=sha(a.native/'manifest.json'));icu['files']['libjavacore.so']=dict(sha256=build['library_sha256'],bytes=(a.native/'libjavacore.so').stat().st_size,dynamic=subprocess.check_output(['readelf','-d',str(a.native/'libjavacore.so')],text=True));generated(icu,'share/build/native-icu/manifest.json')
runtime=json.loads((oldroot/'runtime.json').read_text());runtime['private_native_icu'].update(schema=icu['schema'],manifest_sha256=sha(root/'share/build/native-icu/manifest.json'))
for section,key in [('socket_flags_api29','native_library_sha256'),('linux_io_compat','library_sha256'),('os_extended_io','current_native_library_sha256'),('numeric_resolver','library_sha256'),('fdsan_ownership','libjavacore_sha256')]:
 assert runtime[section][key]==build['baseline_library_sha256'];runtime[section][key]=build['library_sha256']
runtime['component_hosts']=dict(schema=build['schema'],scope=build['scope'],native_manifest_sha256=sha(a.native/'manifest.json'),libjavacore_sha256=build['library_sha256'],hosts_sha256=data['sha256'],lookup='component-static-hosts-then-host-NSS-DNS',normal_apps=True,original_vm_regression_tests=236,original_vm_failures=0,original_vm_assumptions=2,own_java_checks=245,own_native_cases=12,phone_fix_unproven=True,full_module_passed=False)
generated(runtime,'runtime.json');manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert manifest['symlinks']==full['symlinks']and set(full['files'])<=set(manifest['files'])and all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert after[k]==before[k]
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['component_hosts_overlay']=dict(schema='saildroid-component-hosts-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_other_java_boot_art_hostshim_media_manager_trust_bytes_unchanged=True,all_old_dynamic_symbols_preserved=True,added_imports=build['added_imports'],phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(a.native/'libjavacore.so')==build['library_sha256']and sha(builder)==build['builder_sha256']and all(sha(repo/n)==h for n,h in build['headers'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('COMPONENT_HOSTS_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
