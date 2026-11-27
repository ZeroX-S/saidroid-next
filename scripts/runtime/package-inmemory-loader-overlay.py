#!/usr/bin/env python3
"""Package verified classloader compatibility into a new private component only."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, stat, tarfile, zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','dex-module','loader-module','baseline-encoded','encoded','boot','output']:
    p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text())
assert before['schema']=='saildroid-native-overlay-v2' and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
    f=oldroot/n;assert not Path(n).is_absolute() and '..'not in Path(n).parts
    assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
modules=[]
for directory,kind in [(a.dex_module,'inmemory-dex'),(a.loader_module,'inmemory-loader')]:
    module=json.loads((directory/'manifest.json').read_text())
    assert module['schema']=='saildroid-'+kind+'-compat-v1' and module['passed']
    builder=repo/('scripts/runtime/build-'+kind+'-compat-vm.py');source=repo/('scripts/runtime/core/'+kind+'-compat')
    assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
    for n,v in module['sources']['files'].items():
        assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
    core=module['components']['core-libart']
    assert sha(directory/'core-libart-hostdex.jar')==core['sha256']and sha(directory/'core-libart-classes.jar')==core['class_jar_sha256']
    modules.append((directory,kind,module,builder,source))
assert modules[1][2]['inputs'][str(a.dex_module/'manifest.json')]==sha(a.dex_module/'manifest.json')
core=modules[1][2]['components']['core-libart'];runtime=json.loads((oldroot/'runtime.json').read_text())
encoded=json.loads((a.encoded/'manifest.json').read_text());old_encoded=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text())
assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old_encoded[k]
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('loader_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
promoted='Ldalvik/system/DexPathList;->makeInMemoryDexElements([Ljava/nio/ByteBuffer;Ljava/util/List;)[Ldalvik/system/DexPathList$Element;'
added=set();changed=[]
for n,v in encoded['files'].items():
    assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']
    assert sha(a.baseline_encoded/n)==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']
    with zipfile.ZipFile(a.baseline_encoded/n)as z:old,_=enc.dex_members(z.read('classes.dex'));old_resources={k:sha256 for k in z.namelist()if not k.endswith('.dex')for sha256 in [hashlib.sha256(z.read(k)).hexdigest()]}
    with zipfile.ZipFile(a.encoded/n)as z:new,_=enc.dex_members(z.read('classes.dex'));new_resources={k:hashlib.sha256(z.read(k)).hexdigest()for k in z.namelist()if not k.endswith('.dex')}
    assert old_resources==new_resources
    assert set(old)<=set(new)and all(old[k][0]==new[k][0]for k in old if k!=promoted)
    if promoted in old:assert old[promoted][0]==10 and new[promoted][0]==9
    assert {k:v[0]for k,v in old.items()if v[0]&0x100}=={k:v[0]for k,v in new.items()if v[0]&0x100}
    added|=set(new)-set(old)
    if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
assert changed==['java/dex/art/core-libart.jar']and len(added)==3 and added==set(core['added_members'])
assert encoded['files']['java/dex/art/core-libart.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_files=[evidence/n for n in ['original-loader203-paired-v1-audit.json','loader203-own-contract-v1.json','loader203-class-access-v1.json']]
original,own,access=[json.loads(f.read_text())for f in proof_files]
assert original['accepted_comparison']and original['tests']==47 and original['after_fail']==0 and original['before_fail']==31
assert sha(evidence/'original-loader203-selected-v1.json')==original['raw_paired_sha256']
assert own['passed']and access['passed']and access['after_class_jar_sha256']==core['class_jar_sha256']
for d in [original,own]:assert d['actual_core_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']and d['actual_boot_manifest_sha256']==sha(a.boot/'manifest.json')
assert own['actual_framework_sha256']==encoded['files']['java/dex/art/framework29-classes.jar']['sha256']
for n,h in own['sources'].items():assert sha(repo/n)==h
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
    v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for directory,kind,module,builder,source in modules:
    for f,n in [(directory/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py')]:install(f,'share/build/classloader/'+kind+'/'+n)
    for n in module['sources']['files']:install(source/n,'share/build/classloader/'+kind+'/sources/'+n)
install(Path(__file__),'share/build/classloader/packager.py')
for f in proof_files:install(f,'share/build/classloader/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['classloader_compat']=dict(schema='saildroid-inmemory-loader-compat-v1',dex_module_manifest_sha256=sha(a.dex_module/'manifest.json'),loader_module_manifest_sha256=sha(a.loader_module/'manifest.json'),canonical_access_promotions=dict(class_name='dalvik.system.DexPathList',method=promoted),native_binaries_unchanged=True)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['classloader_overlay']=dict(schema='saildroid-classloader-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_art_media_manager_trust_bytes_unchanged=True,original_selected_tests=47,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
for directory,kind,module,builder,source in modules:
    assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
    assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('CLASSLOADER_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
