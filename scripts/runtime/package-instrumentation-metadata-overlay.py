#!/usr/bin/env python3
"""Package generic instrumentation metadata propagation over verified API29 bytes."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,stat,tarfile,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v3'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['passed']and module['schema']=='saildroid-instrumentation-metadata-compat-v1'and module['unmodified_classfiles_byte_identical']and module['all_existing_member_flags_and_native_declarations_preserved']
builder=repo/'scripts/runtime/build-instrumentation-metadata-compat-vm.py';source=repo/'scripts/runtime/instrumentation-metadata-compat';assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']and sha(a.module/'runtime.jar')==module['runtime_sha256']
for n,v in module['sources']['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(source/(Path(n).stem+'.patch'))==v['patch_sha256']
assert set(module['new_members'])=={'LSdInstrumentation;->info(Landroid/content/ComponentName;I)Landroid/content/pm/InstrumentationInfo;'}
runtime=json.loads((oldroot/'runtime.json').read_text());old=json.loads((a.baseline_encoded/'manifest.json').read_text());new=json.loads((a.encoded/'manifest.json').read_text());assert old==json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text());assert old['files'].keys()==new['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert old[k]==new[k]
spec=importlib.util.spec_from_file_location('metadata_packager_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc);changed=[];added=set()
for n,v in new['files'].items():
 assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']and sha(a.baseline_encoded/n)==old['files'][n]['sha256']==full['files'][n]['sha256']
 with zipfile.ZipFile(a.baseline_encoded/n)as z:am,_=enc.dex_members(z.read('classes.dex'));ar={k:z.read(k)for k in z.namelist()if not k.endswith('.dex')}
 with zipfile.ZipFile(a.encoded/n)as z:bm,_=enc.dex_members(z.read('classes.dex'));br={k:z.read(k)for k in z.namelist()if not k.endswith('.dex')}
 assert ar==br and set(am)<=set(bm)and all(am[k][0]==bm[k][0]for k in am)
 assert {k:v[0]for k,v in am.items()if v[0]&0x100}=={k:v[0]for k,v in bm.items()if v[0]&0x100};added|=set(bm)-set(am)
 if old['files'][n]['sha256']!=v['sha256']:changed.append(n)
assert changed==['lib/runtime.jar']and added==set(module['new_members'])and new['files']['lib/runtime.jar']['source_sha256']==module['runtime_sha256']and old['files']['lib/runtime.jar']['source_sha256']==module['baseline_runtime_sha256']
flags=lambda d:dict(l.split(',',1)for l in(d/'effective-api-flags.csv').read_text().splitlines());af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[k]==v for k,v in af.items())and all(bf[k]=='blacklist'for k in added)
images=json.loads((a.boot/'manifest.json').read_text());assert len(images)==27 and all(sha(a.boot/n)==v for n,v in images.items());recipe=json.loads((a.boot/'recipe.json').read_text());assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:new['files'][n]['sha256']for n in runtime['boot_jars']if'/framework29-'not in n}
b=repo/'build/evidence/cts-frame-repair-20261031';proofs=[b/n for n in ['instrumentation-metadata260-paired-v1-audit.json','instrumentation-metadata260-own-contract-v4.json','instrumentation-metadata260-encoded-v1-boundary.json']];audit,own,boundary=[json.loads(f.read_text())for f in proofs];assert audit['passed']and audit['tests']==80 and audit['before_pass']==79 and audit['before_fail']==1 and audit['after_pass']==80 and audit['after_fail']==0 and not audit['full_module_passed']and not audit['phone_tested']and audit['exact_original_ids']and audit['own_contract_checks']==14
assert not audit['records'][0]['original_declared_listener_loaded']and audit['records'][1]['original_declared_listener_loaded']and all(v['all_cleanup_safe']for v in audit['records'])
for which,info in audit['components'].items():
 e=old if which=='before'else new
 assert info['runtime_sha256']==e['files']['lib/runtime.jar']['sha256']and info['hidden_manifest_sha256']==sha((a.baseline_encoded if which=='before'else a.encoded)/'manifest.json')
assert audit['components']['after']['boot_manifest_sha256']==sha(a.boot/'manifest.json')and audit['own_contract_sha256']==sha(proofs[1])and own['passed']and 'checks=14|'in own['results'][1]['marker']
assert boundary['passed']and boundary['core_module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and boundary['boot_manifest_sha256']==sha(a.boot/'manifest.json')and boundary['changed_jars']==changed
frozen=json.loads((b/'original-instrumentation-metadata260-coupled-v1-frozen-inputs.json').read_text());assert all(sha(repo/n)==h for n,h in frozen['sources'].items())and all(sha(b/n)==h for n,h in frozen['proofs'].items())
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root)
after=copy.deepcopy(before);manifest=after['install_manifest'];changes=after['changes'];updated=[]
def install(f,n,mode=0o644):
 t=root/n;t.parent.mkdir(parents=True,exist_ok=True);assert not t.is_symlink();shutil.copyfile(f,t);t.chmod(mode);v=dict(sha256=sha(t),size=t.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
install(a.encoded/'lib/runtime.jar','lib/runtime.jar',full['files']['lib/runtime.jar']['mode']);install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
changed_images=[]
for n in images:
 key='system/framework/'+n
 if images[n]!=full['files'][key]['sha256']:install(a.boot/n,key,full['files'][key]['mode']);changed_images.append(n)
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','module-manifest.json'),(builder,'builder.py'),(Path(__file__),'packager.py'),(b/'run-original-instrumentation-metadata260-coupled-v1-vm.py','tests/run-original.py'),(b/'audit-instrumentation-metadata260-paired-v1-vm.py','tests/audit-paired.py'),(b/'run-instrumentation-metadata260-own-contract-v4-vm.py','tests/run-own.py'),(b/'InstrumentationMetadata260ContractRunner.java','tests/ContractRunner.java'),(repo/'scripts/runtime/tests/instrumentation-metadata/InstrumentationMetadata260Contract.java','tests/Contract.java')]:install(f,'share/build/instrumentation-metadata/'+n)
for f in source.iterdir():
 if f.is_file():install(f,'share/build/instrumentation-metadata/sources/'+f.name)
for f in proofs:install(f,'share/build/instrumentation-metadata/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json');runtime['instrumentation_metadata']=dict(schema=module['schema'],module_manifest_sha256=sha(a.module/'manifest.json'),generic_get_meta_data=True,defensive_bundle_copy=True,original_whole_class_tests=80,original_whole_class_failures=0,own_checks=14,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert set(full['files'])<=set(manifest['files'])and full['symlinks']==manifest['symlinks']and all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert before[k]==after[k]
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['instrumentation_metadata_overlay']=dict(schema='saildroid-instrumentation-metadata-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,module_manifest_sha256=sha(a.module/'manifest.json'),updated_files=sorted(updated),changed_images=changed_images,all_boot_jars_native_art_media_manager_trust_bytes_unchanged=True,original_whole_class_tests=80,original_whole_class_failures=0,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as arc:arc.add(root,arcname='payload');arc.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and all(sha(repo/n)==h for n,h in frozen['sources'].items())and all(sha(b/n)==h for n,h in frozen['proofs'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('INSTRUMENTATION_METADATA_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
