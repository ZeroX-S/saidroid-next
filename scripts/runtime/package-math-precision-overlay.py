#!/usr/bin/env python3
"""Package private five-function Math precision routing over an exact current component.

No Java/APK, trust, cleanup privilege, managed heap, clock or test changes.
Selected original classes and independent VM contracts are not full CTS acceptance.
"""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,subprocess,tarfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','host','art','companion','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];b=repo/'build/evidence/cts-frame-repair-20261031';sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v3'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
host=json.loads((a.host/'manifest.json').read_text());art=json.loads((a.art/'manifest.json').read_text());comp=json.loads((a.companion/'manifest.json').read_text())
assert host['schema']=='saildroid-math-precision-host-v1'and comp['schema']=='saildroid-math-precision-companion-v1'
assert all(d['passed']for d in [host,art,comp])
assert all(host[k]for k in ['unmodified_host_reproduced_byte_identical','all_dynamic_symbols_identical','needed_identical'])
assert art['unmodified_art_reproduced_byte_identical']and art['vm_baseline_sources_and_objects_restored']and art['old_dynamic_symbols_unchanged']
assert host['baseline_binary_sha256']==full['files']['libexec/saildroid-host']['sha256']and art['baseline_binary_sha256']==full['files']['lib/libart.so']['sha256']
assert comp['backend_sha256']==full['files']['lib/libsdstrictmath-fdlibm.so']['sha256']
assert sha(a.host/'saildroid-host')==host['binary_sha256']and sha(a.art/'libart.so')==art['binary_sha256']and sha(a.companion/'libsdmath-precision.so')==comp['library_sha256']
for record,builder in [(host,'build-math-precision-host-vm.py'),(art,'build-art-host-math-precision-vm.py'),(comp,'build-math-precision-companion-vm.py')]:assert sha(repo/'native/compat'/builder)==record['builder_sha256']
assert sha(repo/'native/compat/patches/host-math-precision.patch')==host['patch_sha256']
assert sha(a.host/'source/host-entry.cpp')==host['sources_after']['host-entry.cpp']
assert sha(repo/'native/compat/math-precision/MathPrecision.c')==comp['source_sha256']and sha(repo/'native/compat/math-precision/sources.json')==art['source_meta_sha256']
for n,h in art['patches'].items():assert sha(repo/'native/compat/patches'/n)==h
for n,v in art['sources'].items():assert sha(a.art/'patched'/n)==v['patched_sha256']
sy=lambda f:set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
assert sy(a.host/'baseline-host')==sy(a.host/'saildroid-host')
assert not sy(a.art/'baseline-libart.so')-sy(a.art/'libart.so')
assert sy(a.art/'libart.so')-sy(a.art/'baseline-libart.so')=={'w ieee_'+n for n in ['sin','cos','tan','cbrt','pow']}
assert set(comp['defined_symbols'])=={'Math_'+n for n in ['sin','cos','tan','cbrt','pow']}
proof_names=['math-precision240-boundaries-v1-audit.json','math-precision240-own-paths-v1.json','math-precision240-mpfr-sample-contract-v1.json','math-precision240-environment-v1.json','original-math-precision240-coupled-regression-v2.json']
proofs=[b/n for n in proof_names];original,own,oracle,environment,coupled=[json.loads(f.read_text())for f in proofs]
assert original['passed']and original['counts']['full240']==dict(tests=216,failures=0,assumptions=0,real_passed=216)and original['whole_csv_passed']and original['same_ordered_callbacks']and original['unique_original_tests']==216
assert original['raw_sha256']==sha(b/'original-math-precision240-selected-v1.json')and original['paths_sha256']==sha(proofs[1])and original['oracle_sha256']==sha(proofs[2])
raw=json.loads((b/'original-math-precision240-selected-v1.json').read_text())
assert raw['actual_art_candidate_sha256']==art['binary_sha256']and raw['actual_art_baseline_sha256']==art['baseline_binary_sha256']and raw['actual_companion_sha256']==comp['library_sha256']
assert own['passed']and own['art_candidate_sha256']==art['binary_sha256']and own['companion_sha256']==comp['library_sha256']and own['results'][-1]['marker']=='MATH_PRECISION240_CONTRACT=PASS|boundary=full240|checks=43'
contract=repo/'scripts/runtime/tests/application-cache-startup/MathPrecision240Contract.java'
assert own['source_sha256']==sha(contract)and own['runner_source_sha256']==sha(b/'MathPrecision240ContractRunner.java')
assert oracle['passed']and oracle['samples']==20575 and not oracle['failures']and max(oracle['max_error_ulps'].values())<=1 and oracle['companion_sha256']==comp['library_sha256']and oracle['backend_sha256']==comp['backend_sha256']
assert environment['passed']and environment['host_manifest_sha256']==sha(a.host/'manifest.json')and environment['companion_manifest_sha256']==sha(a.companion/'manifest.json')and environment['actual']['uid']==65534 and len(environment['actual']['owners'])==5
assert coupled['complete']and coupled['counts']==dict(started=145,passed=144,failed=1)
assert all(coupled.get(n)for n in ['private_state_and_apk_removed','owned_processes_reaped','binderfs_removed','private_bus_removed','private_data_mount_removed'])
assert coupled['actual_client_runtime_maps'][str(a.art/'libart.so')]==art['binary_sha256']
failed=[e['bundle']['class']+'#'+e['bundle']['test']for e in coupled['events']if e.get('event')=='status'and e.get('code')in[-1,-2]and e.get('bundle',{}).get('test')]
assert failed==['libcore.java.lang.SystemTest#testSystemProperties_mutable']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes=after['install_manifest'],after['changes'];updated=[]
def install(f,n,mode=0o644):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
 v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
def putjson(v,n):
 tmp=a.output/'metadata.pending.json';tmp.write_text(json.dumps(v,indent=2)+'\n');install(tmp,n);tmp.unlink()
install(a.host/'saildroid-host','libexec/saildroid-host',full['files']['libexec/saildroid-host']['mode']);install(a.art/'libart.so','lib/libart.so',full['files']['lib/libart.so']['mode']);install(a.companion/'libsdmath-precision.so','lib/libsdmath-precision.so')
for directory,label in [(a.host,'host'),(a.art,'art'),(a.companion,'companion')]:install(directory/'manifest.json','share/build/math-precision/'+label+'-manifest.json')
install(a.host/'source/host-entry.cpp','share/build/math-precision/host-entry.cpp')
source_names=['native/compat/build-math-precision-host-vm.py','native/compat/build-art-host-math-precision-vm.py','native/compat/build-math-precision-companion-vm.py','native/compat/patches/host-math-precision.patch','native/compat/patches/art-host-math-precision.patch','native/compat/math-precision/MathPrecision.c','native/compat/math-precision/sources.json','native/compat/tests/math-precision-environment.cpp','scripts/runtime/tests/application-cache-startup/MathPrecision240Contract.java']
for n in source_names:install(repo/n,'share/build/math-precision/sources/'+n)
for n in art['sources']:install(a.art/'patched'/n,'share/build/math-precision/art-sources/'+n)
install(Path(__file__),'share/build/math-precision/packager.py')
for f in proofs+[b/'math-precision240-original-input-oracle-v1.json']:install(f,'share/build/math-precision/evidence/'+f.name)
for n in ['MathPrecision240ContractRunner.java','run-math-precision240-own-paths-v1-vm.py','math-precision240-mpfr-sample-contract-v1-vm.py','prepare-math-precision240-oracle-v1-vm.py','audit-math-precision240-boundaries-v1.py','run-math-precision240-environment-v1-vm.py']:install(b/n,'share/build/math-precision/tests/'+n)
agent=json.loads((oldroot/'share/build/art-agent-manifest.json').read_text());assert agent['files']['libart.so']['sha256']==art['baseline_binary_sha256']
install(oldroot/'share/build/art-agent-manifest.json','share/build/math-precision/base-art-agent-manifest.json')
agent['files']['libart.so']=dict(sha256=art['binary_sha256'],size=(a.art/'libart.so').stat().st_size)
agent['host_math_precision']=dict(build_manifest_sha256=sha(a.art/'manifest.json'),only_added_weak_imports=art['only_new_weak_imports'],old_dynamic_symbols_unchanged=True)
putjson(agent,'share/build/art-agent-manifest.json')
runtime=json.loads((oldroot/'runtime.json').read_text())
def update_art(v):
 if isinstance(v,dict):return {k:update_art(x)for k,x in v.items()}
 if isinstance(v,list):return [update_art(x)for x in v]
 return art['binary_sha256']if v==art['baseline_binary_sha256']else v
runtime=update_art(runtime);runtime['private_art_agent']['manifest_sha256']=sha(root/'share/build/art-agent-manifest.json')
runtime['native_math_precision']=dict(schema='saildroid-native-math-precision-v1',scope='All apps: private Android fdlibm Math sin/cos/tan/cbrt/pow native, interpreter and ARM64 JIT entrypoints; ordinary libc and original libopenjdk unchanged.',host_manifest_sha256=sha(a.host/'manifest.json'),art_manifest_sha256=sha(a.art/'manifest.json'),companion_manifest_sha256=sha(a.companion/'manifest.json'),libart_sha256=art['binary_sha256'],library_sha256=comp['library_sha256'],original_selected_tests=216,original_selected_failed=0,mpfr_checks=20575,own_art_checks=43,coupled_tests=145,coupled_failed=1,phone_executed=False,full_module_passed=False)
putjson(runtime,'runtime.json');manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert set(full['files'])<=set(manifest['files'])and full['symlinks']==manifest['symlinks']
assert {n for n in updated if n in full['files']}=={'libexec/saildroid-host','lib/libart.so','share/build/art-agent-manifest.json','runtime.json'}
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert before[k]==after[k]
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['math_precision_overlay']=dict(schema='saildroid-math-precision-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_java_core_boot_jni_trust_manager_media_bytes_unchanged=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as t:t.add(root,arcname='payload');t.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('MATH_PRECISION_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
