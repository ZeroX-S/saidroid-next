#!/usr/bin/env python3
"""Package verified canonical JAR providers and scoped classloader resource archives."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,stat,tarfile,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','core-module','libart-module','baseline-encoded','encoded','boot','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
modules={};provenance=[]
for key,directory,name in [('core-oj',a.core_module,'jar-verification'),('core-libart',a.libart_module,'classpath-resource')]:
 module=json.loads((directory/'manifest.json').read_text());assert module['schema']=='saildroid-'+name+'-compat-v1'and module['passed']
 source=repo/('scripts/runtime/core/'+name+'-compat');builder=repo/('scripts/runtime/build-'+name+'-compat-vm.py')
 assert sha(source/'sources.json')==module['source_meta_sha256']and sha(builder)==module['builder_sha256']
 for n,v in module['sources']['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
 core=module['components'][key];assert sha(directory/(key+'-hostdex.jar'))==core['sha256']and sha(directory/(key+'-classes.jar'))==core['class_jar_sha256']and core['all_existing_member_flags_preserved']and core['all_existing_members_and_native_declarations_preserved']
 modules[key]=module;provenance.append((directory,name,source,builder,module))
runtime=json.loads((oldroot/'runtime.json').read_text());old=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text());encoded=json.loads((a.encoded/'manifest.json').read_text());assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old[k]
assert encoded['files'].keys()==old['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('classpath_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
added=set();changed=[]
for n,v in encoded['files'].items():
 assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']and sha(a.baseline_encoded/n)==old['files'][n]['sha256']==full['files'][n]['sha256']
 with zipfile.ZipFile(a.baseline_encoded/n)as z:am,_=enc.dex_members(z.read('classes.dex'));ar={n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()if not n.endswith('.dex')}
 with zipfile.ZipFile(a.encoded/n)as z:bm,_=enc.dex_members(z.read('classes.dex'));br={n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()if not n.endswith('.dex')}
 assert ar==br and set(am)<=set(bm)and all(am[k][0]==bm[k][0]for k in am)
 assert {k:v[0]for k,v in am.items()if v[0]&0x100}=={k:v[0]for k,v in bm.items()if v[0]&0x100}
 added|=set(bm)-set(am)
 if old['files'][n]['sha256']!=v['sha256']:changed.append(n)
assert set(changed)=={'java/dex/art/core-oj.jar','java/dex/art/core-libart.jar'}and len(added)==23
assert added=={n for module in modules.values()for core in module['components'].values()for n in core['added_members']}
for key,module in modules.items():assert encoded['files']['java/dex/art/'+key+'.jar']['source_sha256']==module['components'][key]['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[k]==v for k,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text());assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}and all(sha(a.boot/n)==h for n,h in images.items())
b=repo/'build/evidence/cts-frame-repair-20261031';proofs=[b/n for n in ['original-classpath222-paired-v2-audit.json','classpath222-own-contract-v1.json','jar222-own-contract-v1.json']];original,own,crypto=[json.loads(f.read_text())for f in proofs]
assert original['accepted_comparison']and not original['full_module_passed']and original['before_fail']==2 and original['after_fail']==0 and original['after_pass']==original['tests']
assert sha(b/'original-classpath222-selected-v2.json')==original['raw_paired_sha256']
assert own['passed']and'checks=936|'in own['marker']and own['source_sha256']==sha(repo/'scripts/runtime/tests/classpath-resource/ClassPathResourceContract.java')and own['source_meta_sha256']==sha(repo/'scripts/runtime/core/classpath-resource-compat/sources.json')
assert crypto['passed']and'checks=110|'in crypto['marker']and crypto['source_sha256']==sha(repo/'scripts/runtime/tests/jar-verification/JarVerificationContract.java')and crypto['source_meta_sha256']==sha(repo/'scripts/runtime/core/jar-verification-compat/sources.json')
for d in [own,crypto]:
 assert d['actual_core_oj_sha256']==encoded['files']['java/dex/art/core-oj.jar']['sha256']and d['actual_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']
 assert d['actual_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and d['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')and d['actual_art_sha256']==full['files']['lib/libart.so']['sha256']and d['actual_new_javacore_sha256']==full['files']['lib/libjavacore.so']['sha256']and d['actual_native_host_sha256']==full['files']['lib/libsdhost29.so']['sha256']and d['actual_new_runtime_sha256']==full['files']['lib/runtime.jar']['sha256']
assert original['actual_new_core_oj_sha256']==own['actual_core_oj_sha256']and original['actual_new_core_libart_sha256']==own['actual_core_libart_sha256']and original['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and original['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')
assert original['actual_art_sha256']==own['actual_art_sha256']and original['actual_javacore_sha256']==own['actual_new_javacore_sha256']and original['actual_native_host_sha256']==own['actual_native_host_sha256']
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
for directory,name,source,builder,module in provenance:
 for f,n in [(directory/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py')]:install(f,'share/build/classpath-resource/'+name+'/'+n)
 for n,v in module['sources']['files'].items():
  install(source/n,'share/build/classpath-resource/'+name+'/sources/'+n);install(repo/v['reference'],'share/build/classpath-resource/'+name+'/references/'+n)
install(Path(__file__),'share/build/classpath-resource/packager.py')
for f in proofs:install(f,'share/build/classpath-resource/evidence/'+f.name)
for n in ['classpath-resource/ClassPathResourceContract.java','jar-verification/JarVerificationContract.java']:install(repo/'scripts/runtime/tests'/n,'share/build/classpath-resource/tests/'+n)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['classpath_resources']=dict(schema='saildroid-classpath-resource-compat-v1',scope='All classloader resource/zip-native lookups; actual scoped archive close, original explicit cached API retained; canonical Android10 JAR crypto allowlist. No guard suppression or signed-resource bypass.',core_module_manifest_sha256=sha(a.core_module/'manifest.json'),libart_module_manifest_sha256=sha(a.libart_module/'manifest.json'),original_selected_tests=original['tests'],original_selected_failures=0,own_resource_checks=936,own_crypto_checks=110,all_native_binaries_unchanged=True,full_module_passed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['classpath_resource_overlay']=dict(schema='saildroid-classpath-resource-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),original_selected_tests=original['tests'],original_selected_failures=0,all_native_runtime_framework_media_manager_trust_bytes_unchanged=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
for directory,name,source,builder,module in provenance:assert sha(source/'sources.json')==module['source_meta_sha256']and sha(builder)==module['builder_sha256']and all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('CLASSPATH_RESOURCE_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
