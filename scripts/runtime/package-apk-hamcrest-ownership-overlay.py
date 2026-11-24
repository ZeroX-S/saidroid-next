#!/usr/bin/env python3
"""Package APK-owned Hamcrest class resolution without changing dependency/test code."""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,tarfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','ownership','baseline-encoded','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];b=repo/'build/evidence/cts-frame-repair-20261031';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v3'and before['api']==29;oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.ownership/'manifest.json').read_text());builder=repo/'scripts/runtime/prepare-apk-hamcrest-ownership-vm.py';assert module['schema']=='saildroid-apk-hamcrest-ownership-v1'and module['passed']and module['remaining_encoded_jars_byte_identical']and module['remaining_native_and_access_flags_unchanged']and sha(builder)==module['builder_sha256']
remove='java/dex/art/hamcrest-hostdex.jar';assert module['removed_boot_jar']==remove and module['removed_boot_jar_sha256']==full['files'][remove]['sha256']
runtime=json.loads((oldroot/'runtime.json').read_text());expected_boot=[n for n in runtime['boot_jars']if n!=remove];assert len(expected_boot)==len(runtime['boot_jars'])-1 and module['remaining_boot_jars']==expected_boot
encoded=a.ownership/'encoded';boot=a.ownership/'boot';raw_runtime=json.loads((encoded/'runtime.json').read_text());assert raw_runtime['boot_jars']==expected_boot
old_encoded=json.loads((a.baseline_encoded/'manifest.json').read_text());new_encoded=json.loads((encoded/'manifest.json').read_text());assert old_encoded==json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text())and sha(a.baseline_encoded/'manifest.json')==module['baseline_encoded_manifest_sha256']and sha(encoded/'manifest.json')==module['encoded_manifest_sha256']
assert set(new_encoded['files'])==set(old_encoded['files'])-{remove}==set(expected_boot)|{'lib/runtime.jar'}
for n,v in new_encoded['files'].items():assert sha(encoded/n)==v['sha256']==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']and v['executable_code_unchanged']
for key in ['schema','canonical_flags_sha256','tool_sha256','unknown_policy']:assert new_encoded[key]==old_encoded[key]
assert new_encoded['public_library_apis']=={n:v for n,v in old_encoded['public_library_apis'].items()if n!=remove}
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines());af,bf=flags(a.baseline_encoded),flags(encoded);assert set(af)-set(bf)==set(module['removed_effective_members'])and not(set(bf)-set(af))and all(bf[n]==af[n]for n in bf)and all(n.startswith('Lorg/hamcrest/')for n in set(af)-set(bf))
images=json.loads((boot/'manifest.json').read_text());old_images=json.loads((oldroot/'share/build/boot-image-manifest.json').read_text());inactive_images={n for n in old_images if 'boot-hamcrest-hostdex.'in n};assert len(inactive_images)==3 and len(images)==27 and set(images)==set(old_images)-inactive_images and sha(boot/'manifest.json')==module['boot_manifest_sha256']and all(sha(boot/n)==h for n,h in images.items())
recipe=json.loads((boot/'recipe.json').read_text());assert {Path(n).name:h for n,h in recipe['files'].items()}=={Path(n).name:v['sha256']for n,v in new_encoded['files'].items()if n!='lib/runtime.jar'and'/framework29-'not in n}
proof_files=[b/n for n in ['original-apk-hamcrest235-selected-v1-audit.json','original-apk-hamcrest235-regression-v1-audit.json','apk-hamcrest235-ownership-v2-boundary.json','test-library235-current-definition-ownership-v1.json','test-library235-original-boot-classpath-v1.json']]
selected,regression,boundary,definitions,reference=[json.loads(f.read_text())for f in proof_files]
assert boundary==module and sha(proof_files[3])==module['original_apk_ownership_proof_sha256']and sha(proof_files[4])==module['original_boot_classpath_proof_sha256']and reference['passed']and sha(repo/reference['reference'])==reference['reference_sha256']and not any('hamcrest'in n for n in reference['boot_jars'])
assert selected['accepted_comparison']and selected['accepted_no_new_failures']and selected['tests']==58 and selected['before_fail']==3 and selected['after_fail']==1 and selected['before_passed']==55 and selected['after_passed']==57 and selected['same_ordered_callbacks']and selected['actual_everyItem_after']and selected['actual_class_owner_after']=='original-APK44classes'and not selected['full_module_passed']and not selected['phone_executed']
assert selected['remaining_actual_error']=='InvalidAlgorithmParameterException: No IV set when using PBE key'
assert regression['accepted_no_regression']and regression['tests']==291 and regression['before_passed']==regression['after_passed']==286 and regression['before_fail']==regression['after_fail']==3 and regression['before_assumptions']==regression['after_assumptions']==2 and regression['same_ordered_callbacks']and not regression['full_module_passed']and not regression['phone_executed']
for proof,raw,driver,log in [(selected,'original-apk-hamcrest235-selected-v3.json','run-original-apk-hamcrest235-selected-v3-vm.py','original-apk-hamcrest235-selected-v3-host.log'),(regression,'original-apk-hamcrest235-regression-v1.json','run-original-apk-hamcrest235-regression-v1-vm.py','original-apk-hamcrest235-regression-v1-host.log')]:
 assert proof['raw_paired_sha256']==sha(b/raw)and proof['driver_sha256']==sha(b/driver)and proof['driver_log_sha256']==sha(b/log)and proof['runner_source_sha256']==sha(b/'Hamcrest235OriginalJUnitEventRunnerV2.java')and proof['jni_registrations']==104
 assert proof['actual_ownership_manifest_sha256']==sha(a.ownership/'manifest.json')and proof['actual_new_encoded_manifest_sha256']==sha(encoded/'manifest.json')and proof['actual_new_boot_manifest_sha256']==sha(boot/'manifest.json')
 assert all(proof[key]==full['files'][name]['sha256']for key,name in [('actual_new_bouncycastle_sha256','java/dex/art/bouncycastle-hostdex.jar'),('actual_new_core_oj_sha256','java/dex/art/core-oj.jar'),('actual_new_core_libart_sha256','java/dex/art/core-libart.jar'),('actual_art_sha256','lib/libart.so'),('actual_javacore_sha256','lib/libjavacore.so'),('actual_native_host_sha256','lib/libsdhost29.so'),('actual_bridge_sha256','lib/libsdbridge.so')])
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 t=root/n;t.parent.mkdir(parents=True,exist_ok=True);assert not t.is_symlink();shutil.copyfile(f,t);t.chmod(mode);v=dict(sha256=sha(t),size=t.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
install(encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(builder,'builder.py'),(Path(__file__),'packager.py'),(a.ownership/'manifest.json','manifest.json'),(boot/'recipe.json','boot-recipe.json'),(b/'Hamcrest235OriginalJUnitEventRunnerV2.java','tests/OriginalJUnitEventRunner.java')]:install(f,'share/build/apk-hamcrest-ownership/'+n)
for f in proof_files:install(f,'share/build/apk-hamcrest-ownership/evidence/'+f.name)
install(repo/reference['reference'],'share/build/apk-hamcrest-ownership/references/init.environ.rc')
reference_dir=b/'aosp-extra/test-library235-boot-v1';refs=json.loads((reference_dir/'manifest.json').read_text());install(reference_dir/'manifest.json','share/build/apk-hamcrest-ownership/references/source-manifest.json')
for n,v in refs.items():assert sha(reference_dir/n)==v['sha256'];install(reference_dir/n,'share/build/apk-hamcrest-ownership/references/'+n)
# Preserve the narrow existing CA/TZ cleanup protocol and rollback bytes.
# These installed old artifacts are deliberately absent from the runtime boot
# list and active image manifest, verified by the actual nine-image/App-loader run.
inactive={remove:full['files'][remove],**{'system/framework/'+n:full['files']['system/framework/'+n]for n in sorted(inactive_images)}}
assert all(manifest['files'][n]==v and sha(root/n)==v['sha256']for n,v in inactive.items())
runtime['boot_jars']=expected_boot;runtime['hidden_api']['manifest_sha256']=sha(encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(boot/'manifest.json');runtime['apk_hamcrest_ownership']=dict(schema=module['schema'],ownership_manifest_sha256=sha(a.ownership/'manifest.json'),removed_from_boot_classpath=remove,dependency_owner='original-APK-classloader',active_boot_images=9,active_boot_image_files=27,retained_inactive_artifacts=inactive,all_remaining_encoded_jars_byte_identical=True,original_selected_tests=349,original_selected_passed=343,original_selected_failed=4,original_selected_assumptions=2,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.pending.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert after[k]==before[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)and all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['apk_hamcrest_ownership_overlay']=dict(schema='saildroid-apk-hamcrest-ownership-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_java_jar_bytes_and_native_art_manager_media_trust_unchanged=True,retained_inactive_artifacts=inactive,active_boot_image_files=27,original_selected_tests=349,original_selected_failed=4,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(builder)==module['builder_sha256']
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('APK_HAMCREST_OWNERSHIP_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|active_boot_images=9|original_APK_classes_unchanged=true|phone_staged=false')
