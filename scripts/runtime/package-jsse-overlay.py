#!/usr/bin/env python3
"""Compose validated source-owned JSSE and its exact encoded boot image over an overlay.

The source overlay and all existing product/native/manager files remain unchanged.
This creates a new isolated artifact; it does not stage or activate a device release.
"""
from pathlib import Path
import argparse,copy,hashlib,json,shutil,stat,tarfile
from jsse_runtime import validate_jsse

parser=argparse.ArgumentParser()
for name in ['baseline','jsse','encoded','boot','output']:parser.add_argument(name,type=Path)
parser.add_argument('--expected-baseline-sha256',required=True)
a=parser.parse_args();repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256,'Baseline archive changed'
before=json.loads((a.baseline/'overlay.json').read_text())
assert before['schema']=='saildroid-native-overlay-v1'and before['api']==29
full=before['install_manifest'];baseline_root=a.baseline/'payload'
for name,entry in before['changes'].items():
    path=Path(name);assert not path.is_absolute()and '..'not in path.parts
    file=baseline_root/path
    assert file.is_file()and not file.is_symlink()and sha(file)==entry['sha256']
    assert stat.S_IMODE(file.stat().st_mode)==entry['mode']and file.stat().st_size==entry['size']
    assert full['files'][name]==entry
runtime=json.loads((baseline_root/'runtime.json').read_text())
assert runtime['api']==29 and runtime['native_host']and runtime['hidden_api']['policy']=='enabled'
jsse=validate_jsse(a.jsse,repo)
encoded=json.loads((a.encoded/'manifest.json').read_text())
old_encoded=json.loads((baseline_root/'share/build/hiddenapi-manifest.json').read_text())
assert encoded['schema']==old_encoded['schema']=='saildroid-hiddenapi-v1'
for field in ['canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:
    assert encoded[field]==old_encoded[field],field
assert encoded['unknown_policy']=='implementation-private-blacklist'
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
wolf='java/dex/art/wolfssljni-hostdex.jar'
assert encoded['files'][wolf]['source_sha256']==jsse['sha256']
changed_jars=[]
for name,entry in encoded['files'].items():
    path=Path(name);assert not path.is_absolute()and '..'not in path.parts
    assert entry['executable_code_unchanged']and sha(a.encoded/name)==entry['sha256']
    assert old_encoded['files'][name]['sha256']==full['files'][name]['sha256']
    if entry['sha256']!=full['files'][name]['sha256']:changed_jars.append(name)
assert changed_jars==[wolf],changed_jars
recipe=json.loads((a.boot/'recipe.json').read_text());images=json.loads((a.boot/'manifest.json').read_text())
old_images=json.loads((baseline_root/'share/build/boot-image-manifest.json').read_text())
assert images.keys()==old_images.keys()
expected={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert {Path(n).name:v for n,v in recipe['files'].items()}==expected
for name,value in images.items():
    path=Path(name);assert len(path.parts)==2 and path.parts[0]=='arm64'and path.suffix in ['.art','.oat','.vdex']
    assert sha(a.boot/path)==value
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload'
shutil.copytree(baseline_root,root)
after=copy.deepcopy(before);changes=after['changes'];manifest=after['install_manifest']
updated=[]
def install(source,name,mode=0o644):
    target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
    assert not target.is_symlink();shutil.copyfile(source,target);target.chmod(mode)
    entry=dict(sha256=sha(target),size=target.stat().st_size,mode=mode)
    changes[name]=entry;manifest['files'][name]=entry;assert name not in manifest['symlinks']
    updated.append(name)
install(a.encoded/wolf,wolf,full['files'][wolf]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for name in images:install(a.boot/name,'system/framework/'+name,full['files']['system/framework/'+name]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
install(a.jsse/'manifest.json','share/build/jsse-compat/manifest.json')
install(repo/'scripts/runtime/jsse-compat/sources.json','share/build/jsse-compat/sources.json')
install(a.jsse/'NOTICE','share/licenses/jsse-compat-NOTICE')
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json')
runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['legacy_jsse_compat']=dict(schema=jsse['schema'],manifest_sha256=sha(a.jsse/'manifest.json'),scope='All applications; initialized factories, actual key aliases, configured native PKIX trust and native client/server authentication',original_class_count=73,changed_classfiles=5,native_binaries_unchanged=True)
temporary=a.output/'runtime.json';temporary.write_text(json.dumps(runtime,indent=2)+'\n');install(temporary,'runtime.json');temporary.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert manifest['symlinks']==full['symlinks']and after['product_manifest']==before['product_manifest']
assert {n:v for n,v in manifest['files'].items()if n not in updated}=={n:v for n,v in full['files'].items()if n not in updated}
assert not(set(full['files'])-set(manifest['files']))
for name,entry in changes.items():
    assert sha(root/name)==entry['sha256']and stat.S_IMODE((root/name).stat().st_mode)==entry['mode']
    parts=Path(name).parts
    assert all(str(Path(*parts[:i]))not in manifest['symlinks']for i in range(1,len(parts)))
provenance=dict(schema='saildroid-jsse-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,baseline_overlay_sha256=sha(a.baseline/'overlay.json'),source_manifest_sha256=sha(repo/'scripts/runtime/jsse-compat/sources.json'),jsse_manifest_sha256=sha(a.jsse/'manifest.json'),changed_boot_jars=changed_jars,updated_files=sorted(updated),product_manifest_unchanged=True,native_files_unchanged=True,phone_staged=False)
after['jsse_overlay']=provenance
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:
    archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
# Close the transaction against concurrent edits to its actual source inputs.
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert validate_jsse(a.jsse,repo)==jsse
assert sha(repo/'scripts/runtime/jsse-compat/sources.json')==provenance['source_manifest_sha256']
print('JSSE_OVERLAY=packaged|files='+str(len(manifest['files']))+'|sha256='+sha(a.output/'native-overlay.tar.gz'))
