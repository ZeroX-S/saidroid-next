#!/usr/bin/env python3
"""Package canonical HTTP ownership plus real TLS ALPN base APIs after strict paired gates."""
from pathlib import Path
import argparse,copy,gzip,hashlib,importlib.util,json,os,shutil,stat,tarfile,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','http-module','tls-module','baseline-framework','baseline-encoded','encoded','boot','inputs','reference','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest'];runtime=json.loads((oldroot/'runtime.json').read_text())
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
hm=json.loads((a.http_module/'manifest.json').read_text());tm=json.loads((a.tls_module/'manifest.json').read_text());fw=a.http_module/'framework';fm=json.loads((fw/'manifest.json').read_text())
hbuilder=repo/'scripts/runtime/build-platform-http-compat-vm.py';tbuilder=repo/'scripts/runtime/build-tls-protocol-compat-vm.py';source=repo/'scripts/runtime/core/tls-protocol-compat'
assert hm['schema']=='saildroid-platform-http-compat-v1'and hm['passed']and sha(hbuilder)==hm['builder_sha256']
assert tm['schema']=='saildroid-tls-protocol-compat-v1'and tm['passed']and sha(tbuilder)==tm['builder_sha256']and sha(source/'sources.json')==tm['source_meta_sha256']
for n,v in tm['sources']['files'].items():assert sha(source/n)==v['sha256']==sha(repo/v['reference'])and sha(repo/v['baseline_source'])==v['baseline_sha256']
core=tm['components']['core-oj'];assert sha(a.tls_module/'core-oj-hostdex.jar')==core['sha256']and sha(a.tls_module/'core-oj-classes.jar')==core['class_jar_sha256']and len(core['added_members'])==8
assert sha(a.inputs/'android-all-10-robolectric-5803371.jar')==hm['source_input_sha256']=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'
assert sha(a.reference/'okhttp.jar')==hm['reference_jar_sha256']=='9a9e38f789ad754f5fd7a45e7c6e4d05cab2258f255344dfb9c2bc6c8f017c81'and sha(a.reference/'manifest.json')==hm['reference_inventory_sha256']
assert sha(a.http_module/'okhttp-hostdex.jar')==hm['http_jar_sha256']and sha(a.http_module/'okhttp-classes.jar')==hm['class_jar_sha256']and sha(fw/'manifest.json')==hm['framework_manifest_sha256']and sha(a.baseline_framework/'manifest.json')==hm['framework_baseline_manifest_sha256']
def entries(f):
 with zipfile.ZipFile(f)as z:
  assert len(z.namelist())==len(set(z.namelist()));return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
httpclasses=entries(a.http_module/'okhttp-classes.jar');oldclasses=entries(a.baseline_framework/'classes.jar');newclasses=entries(fw/'classes.jar');assert len(httpclasses)==241 and set(oldclasses)-set(newclasses)==set(httpclasses)and not(set(newclasses)-set(oldclasses))
assert all(newclasses[n]==v for n,v in oldclasses.items()if n in newclasses)and all(oldclasses[n]==v for n,v in httpclasses.items())and {n:hashlib.sha256(v).hexdigest()for n,v in httpclasses.items()}==hm['classes']==hm['removed_framework_classes']
with zipfile.ZipFile(a.inputs/'android-all-10-robolectric-5803371.jar')as z:assert all(z.read(n)==v for n,v in httpclasses.items())
encoded=json.loads((a.encoded/'manifest.json').read_text());old_encoded=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text());assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old_encoded[k]
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
assert old_encoded['files']['java/dex/art/okhttp-hostdex.jar']['source_sha256']==hm['baseline_http_jar_sha256']
spec=importlib.util.spec_from_file_location('http_tls_packager_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
allold={};allnew={};changed=[]
for n,v in encoded['files'].items():
 assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']and sha(a.baseline_encoded/n)==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']
 oldentries,newentries=entries(a.baseline_encoded/n),entries(a.encoded/n);assert {k:v for k,v in oldentries.items()if not k.endswith('.dex')}=={k:v for k,v in newentries.items()if not k.endswith('.dex')}
 om,_=enc.dex_members(oldentries['classes.dex']);nm,_=enc.dex_members(newentries['classes.dex']);allold.update(om);allnew.update(nm)
 if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
 if n=='java/dex/art/core-oj.jar':assert v['source_sha256']==core['sha256']
 elif n=='java/dex/art/okhttp-hostdex.jar':assert v['source_sha256']==hm['http_jar_sha256']
 elif '/framework29-'in n:assert sha(fw/Path(n).name)==v['source_sha256']==fm['files'][Path(n).name]['sha256']
 else:assert v['sha256']==old_encoded['files'][n]['sha256'],n
removed=set(allold)-set(allnew);added=set(allnew)-set(allold)
assert len(removed)==330 and all(n.startswith('Lcom/android/okhttp/')for n in removed)and added==set(core['added_members'])
assert {n:v[0]for n,v in allold.items()if v[0]&0x100}=={n:v[0]for n,v in allnew.items()if v[0]&0x100}
assert all(allnew[n][0]==v[0]for n,v in allold.items()if not n.startswith('Lcom/android/okhttp/'))
canonicalflags=dict(line.split(',',1)for line in gzip.decompress((repo/'build/evidence/cts-frame-repair-20261031/aosp-extra/android10-hiddenapi-flags.csv.gz').read_bytes()).decode().splitlines());assert not(set(canonicalflags)&removed)
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines());af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(af)-set(bf)==removed and set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items()if n in bf)
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text());assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()and all(sha(a.boot/n)==h for n,h in images.items())
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
evidence=repo/'build/evidence/cts-frame-repair-20261031';proof_files=[evidence/n for n in ['original-http213-whole-v1-paired-audit.json','original-tls213-regression-v1-audit.json','original-http213-url-regression-v1-audit.json','tls213-own-contract-v2.json']];http,tls,url,own=[json.loads(f.read_text())for f in proof_files]
assert http['accepted_comparison']and http['tests']==147 and http['before_fail']==27 and http['after_fail']==11
assert tls['accepted_comparison']and tls['tests']==75 and tls['before_fail']==2 and tls['after_fail']==0
assert url['accepted_comparison']and url['tests']==129 and url['before_fail']==url['after_fail']==1
for audit,rawname in [(http,'original-http213-whole-v1.json'),(tls,'original-tls213-regression-v1.json'),(url,'original-http213-url-regression-v1.json')]:assert sha(evidence/rawname)==audit['raw_paired_sha256']
assert own['passed']and not own['results'][0]['passed']and own['results'][1]['passed']and 'checks=29|'in own['results'][1]['marker']and 'real_alpn_rounds=2|'in own['results'][1]['marker']and sha(repo/'scripts/runtime/tests/tls-protocol/TlsApplicationProtocolContract.java')==own['source_sha256']
assert http['actual_new_core_oj_sha256']==tls['actual_core_oj_sha256']==url['actual_core_oj_sha256']==own['actual_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']
assert http['actual_new_core_libart_sha256']==tls['actual_core_libart_sha256']==url['actual_core_libart_sha256']==own['actual_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']
assert http['actual_new_boot_manifest_sha256']==tls['actual_boot_manifest_sha256']==url['actual_boot_manifest_sha256']==own['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')and http['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
assert http['actual_javacore_sha256']==tls['actual_javacore_sha256']==full['files']['lib/libjavacore.so']['sha256']and http['actual_new_host_sha256']==tls['actual_host_sha256']==own['new_native_sha256']==own['old_native_sha256']==full['files']['lib/libsdhost29.so']['sha256']
assert http['actual_new_http_jar_sha256']==encoded['files']['java/dex/art/okhttp-hostdex.jar']['sha256']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode);manifest['files'][n]=changes[n]=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);updated.append(n)
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.http_module/'manifest.json','http-manifest.json'),(a.tls_module/'manifest.json','tls-manifest.json'),(source/'sources.json','sources.json'),(hbuilder,'http-builder.py'),(tbuilder,'tls-builder.py'),(Path(__file__),'packager.py'),(a.reference/'okhttp.jar','reference/okhttp.jar'),(a.reference/'manifest.json','reference/manifest.json'),(a.http_module/'okhttp-classes.jar','http-classes.jar'),(repo/'scripts/runtime/tests/tls-protocol/TlsApplicationProtocolContract.java','tests/TlsApplicationProtocolContract.java')]:install(f,'share/build/platform-http-tls/'+n)
for n,v in tm['sources']['files'].items():install(source/n,'share/build/platform-http-tls/sources/'+n);install(repo/v['reference'],'share/build/platform-http-tls/references/'+n)
for f in proof_files:install(f,'share/build/platform-http-tls/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json');runtime['platform_http_tls_compat']=dict(schema='saildroid-platform-http-tls-v1',http_module_manifest_sha256=sha(a.http_module/'manifest.json'),tls_module_manifest_sha256=sha(a.tls_module/'manifest.json'),canonical_http_single_owner=True,retired_noncanonical_implementation_members=330,canonical_ssl_api_members_added=8,original_selected_tests=351,original_selected_passed=339,original_selected_failed=12,real_tls_alpn_rounds=2,hostname_and_trust_validation_retained=True,full_module_passed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)and all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['platform_http_tls_overlay']=dict(schema='saildroid-platform-http-tls-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_art_media_manager_trust_bytes_unchanged=True,original_selected_tests=351,original_selected_passed=339,original_selected_failed=12,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(hbuilder)==hm['builder_sha256']and sha(tbuilder)==tm['builder_sha256']and sha(source/'sources.json')==tm['source_meta_sha256']
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('PLATFORM_HTTP_TLS_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
