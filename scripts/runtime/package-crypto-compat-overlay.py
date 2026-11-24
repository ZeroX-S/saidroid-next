#!/usr/bin/env python3
"""Compose verified Android10 crypto policy/registration/resource compatibility.

Creates a new private artifact only. Does not modify any running component,
application/test archive, trust anchor, clock, native library or security policy.
"""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,stat,tarfile,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','policy-module','bc-module','resource-module','baseline-encoded','encoded','boot','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
modules=[]
for directory,kind,component in [(a.policy_module,'crypto-policy','core-oj'),(a.bc_module,'bc-registration','bouncycastle')]:
 m=json.loads((directory/'manifest.json').read_text());assert m['schema']=='saildroid-'+kind+'-compat-v1'and m['passed'];builder=repo/('scripts/runtime/build-'+kind+'-compat-vm.py');source=repo/('scripts/runtime/core/'+kind+'-compat')
 assert sha(builder)==m['builder_sha256']and sha(source/'sources.json')==m['source_meta_sha256']
 for n,v in m['sources']['files'].items():
  assert sha(source/n)==v['sha256']
  if'baseline_source'in v:assert sha(repo/v['baseline_source'])==v['baseline_sha256']
  if'reference'in v:assert sha(repo/v['reference'])==v['reference_sha256']
 c=m['components'][component];assert sha(directory/(component+'-hostdex.jar'))==c['sha256']and sha(directory/(component+'-classes.jar'))==c['class_jar_sha256']
 modules.append((directory,kind,component,m,builder,source))
policy=modules[0][3];bc=modules[1][3];bm=bc['sources'];graph=json.loads((repo/bm['reference_graph']).read_text());assert sha(repo/bm['reference_graph'])==bm['reference_graph_sha256']and graph['passed']and len(graph['properties'])==566
assert sha(repo/bm['closure_proof'])==bm['closure_proof_sha256']and json.loads((repo/bm['closure_proof']).read_text())['all_present']
assert sha(modules[1][-1]/'canonical-registrations.json')==bm['registration_data_sha256']
assert bc['inputs'][str(a.policy_module/'manifest.json')]==sha(a.policy_module/'manifest.json')
resource=json.loads((a.resource_module/'manifest.json').read_text());resource_builder=repo/'scripts/runtime/prepare-crypto-security-resource-vm.py'
assert resource['passed']and resource['schema']=='saildroid-crypto-resource-compat-v1'and sha(resource_builder)==resource['builder_sha256']and resource['baseline_manifest_sha256']==sha(a.policy_module/'manifest.json')
assert sha(Path(resource['reference']['path']))==resource['reference']['sha256']
core=resource['components']['core-oj'];assert sha(a.resource_module/'core-oj-hostdex.jar')==core['sha256']and sha(a.resource_module/'core-oj-classes.jar')==core['class_jar_sha256']==policy['components']['core-oj']['class_jar_sha256']
resource_name=core['resource_only_change'];assert resource_name=='java/security/security.properties'
with zipfile.ZipFile(a.policy_module/'core-oj-hostdex.jar')as z:previous_resources={n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()}
with zipfile.ZipFile(a.resource_module/'core-oj-hostdex.jar')as z:next_resources={n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()}
assert previous_resources.keys()==next_resources.keys()and[n for n in previous_resources if previous_resources[n]!=next_resources[n]]==[resource_name]
runtime=json.loads((oldroot/'runtime.json').read_text());encoded=json.loads((a.encoded/'manifest.json').read_text());old_encoded=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text());assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old_encoded[k]
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('crypto_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc);added=set();changed=[]
for n,v in encoded['files'].items():
 assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']and sha(a.baseline_encoded/n)==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']
 with zipfile.ZipFile(a.baseline_encoded/n)as z:old,_=enc.dex_members(z.read('classes.dex'));oldres={k:hashlib.sha256(z.read(k)).hexdigest()for k in z.namelist()if not k.endswith('.dex')}
 with zipfile.ZipFile(a.encoded/n)as z:new,_=enc.dex_members(z.read('classes.dex'));newres={k:hashlib.sha256(z.read(k)).hexdigest()for k in z.namelist()if not k.endswith('.dex')}
 assert oldres.keys()==newres.keys()and all(oldres[k]==newres[k]for k in oldres if n!='java/dex/art/core-oj.jar'or k!=resource_name)
 assert set(old)<=set(new)and all(old[k][0]==new[k][0]for k in old)
 assert{k:v[0]for k,v in old.items()if v[0]&0x100}=={k:v[0]for k,v in new.items()if v[0]&0x100}
 added|=set(new)-set(old)
 if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
expected=set(policy['components']['core-oj']['added_members'])|set(bc['components']['bouncycastle']['added_members']);assert len(expected)==11 and added==expected and set(changed)=={'java/dex/art/core-oj.jar','java/dex/art/bouncycastle-hostdex.jar'}
assert encoded['files']['java/dex/art/core-oj.jar']['source_sha256']==core['sha256']and encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['source_sha256']==bc['components']['bouncycastle']['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines());af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==expected and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text());assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys();assert{Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if'/framework29-'not in n};assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031';proof_names=['original-crypto205-paired-v1-audit.json','original-bc206-paired-v1-audit.json','original-crypto207-paired-v1-audit.json','crypto207-own-contract-v1.json'];proof_files=[evidence/n for n in proof_names];p205,p206,p207,own=[json.loads(f.read_text())for f in proof_files]
for d,raw in [(p205,'original-crypto205-selected-v1.json'),(p206,'original-bc206-selected-v2.json'),(p207,'original-crypto207-selected-v1.json')]:assert d['accepted_comparison']and d['tests']==102 and sha(evidence/raw)==d['raw_paired_sha256']and not d['full_module_passed']
assert(p205['before_fail'],p205['after_fail'],p206['before_fail'],p206['after_fail'],p207['before_fail'],p207['after_fail'])==(102,17,17,11,11,3)
assert own['passed']and own['phone_mutations']==0 and p207['actual_core_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']and own['actual_core_sha256']==encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['sha256']
for d in [p207,own]:assert d['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')
assert own['actual_framework_sha256']==encoded['files']['java/dex/art/framework29-classes.jar']['sha256']
for n,h in own['sources'].items():assert sha(repo/n)==h
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode);v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for directory,kind,component,m,builder,source in modules:
 for f,n in[(directory/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py')]:install(f,'share/build/crypto-compat/'+kind+'/'+n)
 for n in m['sources']['files']:install(source/n,'share/build/crypto-compat/'+kind+'/sources/'+n)
install(modules[1][-1]/'canonical-registrations.json','share/build/crypto-compat/bc-registration/canonical-registrations.json')
for f,n in[(a.resource_module/'manifest.json','resource-manifest.json'),(resource_builder,'resource-builder.py'),(Path(resource['reference']['path']),'security.properties'),(repo/bm['reference_graph'],'canonical-reference-graph.json'),(repo/bm['closure_proof'],'canonical-class-closure.json'),(Path(__file__),'packager.py')]:install(f,'share/build/crypto-compat/'+n)
for f in proof_files:install(f,'share/build/crypto-compat/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json');runtime['crypto_compat']=dict(schema='saildroid-crypto-compat-v1',policy_manifest_sha256=sha(a.policy_module/'manifest.json'),bc_manifest_sha256=sha(a.bc_module/'manifest.json'),resource_manifest_sha256=sha(a.resource_module/'manifest.json'),all_native_binaries_and_trust_anchors_unchanged=True,selected_original_tests=102,selected_original_passed=99,selected_original_failed=3,full_module_passed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated);assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['crypto_compat_overlay']=dict(schema='saildroid-crypto-compat-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_art_media_manager_trust_bytes_unchanged=True,selected_original_tests=102,selected_original_passed=99,selected_original_failed=3,full_module_passed=False,phone_staged=False);(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(resource_builder)==resource['builder_sha256']
for directory,kind,component,m,builder,source in modules:
 assert sha(builder)==m['builder_sha256']and sha(source/'sources.json')==m['source_meta_sha256']and all(sha(source/n)==v['sha256']for n,v in m['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('CRYPTO_COMPAT_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|original_selected=99/102|phone_staged=false')
