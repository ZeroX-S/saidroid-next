#!/usr/bin/env python3
"""Package verified component-private reverse-hosts lookup, preserving original tests."""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,subprocess,tarfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','native','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();b=repo/'build/evidence/cts-frame-repair-20261031'
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v3'and before['api']==29;oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
build=json.loads((a.native/'manifest.json').read_text());builder=repo/'native/compat/build-reverse-component-hosts-vm.py';source=repo/'native/compat/reverse-hosts/sources.json';sources=json.loads(source.read_text())
assert build['schema']=='saildroid-reverse-component-hosts-native-v1'and build['passed']and all(build[k]for k in ['shared_tree_unchanged','all_previous_dynamic_symbols_preserved','all_defined_exports_identical','needed_identical'])
assert sha(builder)==build['builder_sha256']and all(sha(repo/n)==h for n,h in build['headers'].items())and sha(a.native/'libjavacore.so')==build['library_sha256']and build['baseline_library_sha256']==full['files']['lib/libjavacore.so']['sha256']
assert sha(a.native/'source/libcore_io_Linux.cpp')==build['linux_source_sha256']and sha(a.native/'source/Portability.h')==build['patched_portability_sha256']==build['baseline_portability_sha256']
assert all(sha(repo/n)==h for n,h in sources['unchanged_inputs'].items())
refs=b/'aosp-extra/reverse-hosts231-v1';assert json.loads((refs/'manifest.json').read_text())==sources['references']
assert all(sha(refs/n)==v['sha256']for n,v in sources['references'].items())
def symbols(f):return set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
oldsymbols=symbols(oldroot/'lib/libjavacore.so');newsymbols=symbols(a.native/'libjavacore.so');assert not oldsymbols-newsymbols and newsymbols-oldsymbols==set(build['added_imports'])
proofs=[b/n for n in ['original-reverse-hosts231-selected-v1-audit.json','original-reverse-hosts231-regression-v1-audit.json','reverse-hosts231-native-contract-v1.json','reverse-hosts231-original-namespace-v1.json','reverse-hosts231-regression-namespace-v1.json']]
selected,regression,contract,selectedns,regressionns=[json.loads(p.read_text())for p in proofs]
for proof,kind,counts in [(selected,'selected',(270,23,14)),(regression,'regression',(236,0,0))]:
 assert proof['accepted_comparison']and proof['accepted_no_regression']and proof['whole_original_classes']and proof['same_ordered_callbacks']and not proof['full_module_passed']and not proof['phone_executed']and proof['jni_registrations']==104
 assert(proof['tests'],proof['before_fail'],proof['after_fail'])==counts
 assert proof['actual_new_javacore_sha256']==build['library_sha256']and proof['native_manifest_sha256']==sha(a.native/'manifest.json')
 assert proof['raw_paired_sha256']==sha(b/('original-reverse-hosts231-'+kind+'-v1.json'))and proof['driver_sha256']==sha(b/('run-original-reverse-hosts231-'+kind+'-v1-vm.py'))and proof['driver_log_sha256']==sha(b/('original-reverse-hosts231-'+kind+'-v1-host.log'))
 assert all(proof[k]==full['files']['lib/'+name]['sha256']for k,name in [('actual_art_sha256','libart.so'),('actual_native_host_sha256','libsdhost29.so'),('actual_bridge_sha256','libsdbridge.so')])
assert len(selected['fixed_original_failures'])==9 and len(selected['remaining_original_failures'])==14 and regression['before_assumptions']==regression['after_assumptions']==2
assert contract['passed']and len(contract['cases'])==12 and all(row['passed']for row in contract['cases'])and'checks=1216|'in contract['cases'][0]['marker']and contract['headers']==build['headers']and contract['source_sha256']==sha(repo/'native/compat/tests/reverse-hosts/resolver-contract.cpp')
assert selectedns['passed']and regressionns['passed']and selectedns['global_parent_files_unchanged']and regressionns['global_parent_files_unchanged']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 t=root/n;t.parent.mkdir(parents=True,exist_ok=True);assert not t.is_symlink();shutil.copyfile(f,t);t.chmod(mode);v=dict(sha256=sha(t),size=t.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
def generated(value,n):
 t=a.output/'metadata.pending.json';t.write_text(json.dumps(value,indent=2)+'\n');install(t,n);t.unlink()
install(a.native/'libjavacore.so','lib/libjavacore.so',full['files']['lib/libjavacore.so']['mode'])
for f,n in [(a.native/'manifest.json','native-manifest.json'),(builder,'builder.py'),(Path(__file__),'packager.py'),(source,'sources.json'),(a.native/'source/Portability.h','native-source/Portability.h'),(a.native/'source/libcore_io_Linux.cpp','native-source/libcore_io_Linux.cpp'),(repo/'native/compat/tests/reverse-hosts/resolver-contract.cpp','tests/resolver-contract.cpp')]:install(f,'share/build/reverse-component-hosts/'+n)
for n in build['headers']:install(repo/n,'share/build/reverse-component-hosts/provenance/'+n)
for f in refs.iterdir():install(f,'share/build/reverse-component-hosts/references/'+f.name)
for f in proofs:install(f,'share/build/reverse-component-hosts/evidence/'+f.name)
oldicu=json.loads((oldroot/'share/build/native-icu/manifest.json').read_text());assert oldicu['files']['libjavacore.so']['sha256']==build['baseline_library_sha256'];install(oldroot/'share/build/native-icu/manifest.json','share/build/native-icu/base-manifest-before-reverse-hosts.json')
icu=copy.deepcopy(oldicu);icu.update(schema='saildroid-native-icu-reverse-hosts-v7',base_manifest_sha256=sha(oldroot/'share/build/native-icu/manifest.json'),base_manifest_path='share/build/native-icu/base-manifest-before-reverse-hosts.json',reverse_component_hosts_manifest_sha256=sha(a.native/'manifest.json'));icu['files']['libjavacore.so']=dict(sha256=build['library_sha256'],bytes=(a.native/'libjavacore.so').stat().st_size,dynamic=subprocess.check_output(['readelf','-d',str(a.native/'libjavacore.so')],text=True));generated(icu,'share/build/native-icu/manifest.json')
runtime=json.loads((oldroot/'runtime.json').read_text());runtime['private_native_icu'].update(schema=icu['schema'],manifest_sha256=sha(root/'share/build/native-icu/manifest.json'))
for section,key in [('socket_flags_api29','native_library_sha256'),('linux_io_compat','library_sha256'),('os_extended_io','current_native_library_sha256'),('numeric_resolver','library_sha256'),('fdsan_ownership','libjavacore_sha256'),('component_hosts','libjavacore_sha256')]:
 assert runtime[section][key]==build['baseline_library_sha256'];runtime[section][key]=build['library_sha256']
runtime['reverse_component_hosts']=dict(schema=build['schema'],scope=build['scope'],native_manifest_sha256=sha(a.native/'manifest.json'),libjavacore_sha256=build['library_sha256'],normal_apps=True,original_vm_tests=506,original_vm_before_failures=23,original_vm_after_failures=14,original_vm_assumptions=2,fixed_original_failures=9,own_native_valid_checks=1216,own_native_cases=12,phone_fix_unproven=True,full_module_passed=False)
generated(runtime,'runtime.json');manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert manifest['symlinks']==full['symlinks']and set(full['files'])<=set(manifest['files'])and all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert after[k]==before[k]
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['reverse_component_hosts_overlay']=dict(schema='saildroid-reverse-component-hosts-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_other_java_boot_art_hostshim_media_manager_trust_bytes_unchanged=True,all_old_dynamic_symbols_preserved=True,added_imports=build['added_imports'],phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(a.native/'libjavacore.so')==build['library_sha256']and sha(builder)==build['builder_sha256']and all(sha(repo/n)==h for n,h in build['headers'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('REVERSE_COMPONENT_HOSTS_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
