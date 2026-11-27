#!/usr/bin/env python3
"""Compose private property reads and consistent component metadata in isolation.
No device staging, system partition, signing-key change or shared property
service is implied by this artifact.
"""
from pathlib import Path
import argparse,copy,hashlib,json,shutil,stat,tarfile,os
os.umask(0o022)
from component_properties import update_properties
from private_getprop_runtime import validate_getprop
p=argparse.ArgumentParser()
for name in ['baseline','commands','output']:p.add_argument(name,type=Path)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args()
repo=Path(__file__).resolve().parents[2];sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v1'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for name,entry in before['changes'].items():
    path=Path(name);assert not path.is_absolute()and '..'not in path.parts
    f=oldroot/path;assert f.is_file()and not f.is_symlink()and sha(f)==entry['sha256']
    assert f.stat().st_size==entry['size']and stat.S_IMODE(f.stat().st_mode)==entry['mode']and entry==full['files'][name]
command=validate_getprop(a.commands,repo)
oldrt=json.loads((oldroot/'runtime.json').read_text());assert oldrt['api']==29 and oldrt['native_host']and oldrt['hidden_api']['policy']=='enabled'
property_source=repo/'native/commands/component-properties.json';property_source_sha=sha(property_source)
newprops,metadata=update_properties((oldroot/'build.prop').read_text(),oldrt,property_source)
newnames=['bin/getprop','lib/private-getprop/libc_bio.so.0','share/build/private-getprop/manifest.json','share/build/private-getprop/component-properties.json','share/licenses/private-getprop-NOTICE']
assert not(set(newnames)&(full['files'].keys()|full['symlinks'].keys()))
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root)
after=copy.deepcopy(before);updated=[];created_directories=[]
def install(data,name,mode=0o644):
    path=Path(name);assert not path.is_absolute()and '..'not in path.parts
    assert all(str(Path(*path.parts[:i]))not in full['symlinks']for i in range(1,len(path.parts)+1))
    target=root/path
    for index in range(1,len(path.parts)):
        directory=root/Path(*path.parts[:index])
        if not directory.exists():
            directory.mkdir(mode=0o755);directory.chmod(0o755);created_directories.append(str(directory.relative_to(root)))
        assert directory.is_dir()and not directory.is_symlink()
    assert not target.is_symlink()
    target.write_bytes(data);target.chmod(mode)
    entry=dict(sha256=sha(target),size=target.stat().st_size,mode=mode)
    after['changes'][name]=entry;after['install_manifest']['files'][name]=entry;updated.append(name)
install((a.commands/'getprop').read_bytes(),'bin/getprop',0o755)
install((a.commands/'libc_bio.so.0').read_bytes(),'lib/private-getprop/libc_bio.so.0',0o444)
install((a.commands/'manifest.json').read_bytes(),'share/build/private-getprop/manifest.json')
install(property_source.read_bytes(),'share/build/private-getprop/component-properties.json')
install((a.commands/'NOTICE').read_bytes(),'share/licenses/private-getprop-NOTICE')
install(newprops.encode(),'build.prop')
rt=copy.deepcopy(oldrt);rt['private_getprop']=dict(schema=command['schema'],manifest_sha256=sha(a.commands/'manifest.json'),binary_sha256=command['binary_sha256'],native_property_backend_sha256=command['property_backend_sha256'],scope='Every app; own read-only component property backend; no shared property service or secure host certification')
rt['component_properties']=dict(metadata,source_sha256=property_source_sha)
install((json.dumps(rt,indent=2)+'\n').encode(),'runtime.json')
m=after['install_manifest'];m['bytes']=sum(v['size']for v in m['files'].values())
assert m['symlinks']==full['symlinks']and after['product_manifest']==before['product_manifest']
assert {n:v for n,v in m['files'].items()if n not in updated}=={n:v for n,v in full['files'].items()if n not in updated}
assert not(set(full['files'])-set(m['files']))
provenance=dict(schema='saildroid-property-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,baseline_overlay_sha256=sha(a.baseline/'overlay.json'),command_manifest_sha256=sha(a.commands/'manifest.json'),property_source_sha256=property_source_sha,updated_files=sorted(updated),created_directories={n:0o755 for n in created_directories},metadata=metadata,existing_native_java_boot_manager_bytes_unchanged=True,phone_staged=False)
assert all(stat.S_IMODE((root/n).stat().st_mode)==0o755 for n in created_directories)
after['property_overlay']=provenance
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:
    archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert validate_getprop(a.commands,repo)==command and sha(property_source)==property_source_sha
print('PROPERTY_OVERLAY=packaged|files='+str(len(m['files']))+'|sha256='+sha(a.output/'native-overlay.tar.gz'))
