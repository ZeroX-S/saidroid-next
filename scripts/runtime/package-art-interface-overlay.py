#!/usr/bin/env python3
"""Package an audited generic ART interface/Object dispatch build off-device.

Preserves the full predecessor manifest, existing imported/exported ABI and
matching JVMTI library; one explicitly audited weak inline helper may be added.
Does not activate a release or package the prototype Keystore service.
"""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,subprocess,tarfile
os.umask(0o022)
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','build','original_build','output']:p.add_argument(n,type=Path)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();repo=Path(__file__).resolve().parents[2];sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v1'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 r=Path(n);assert not r.is_absolute()and'..'not in r.parts
 f=oldroot/n;assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and stat.S_IMODE(f.stat().st_mode)==v['mode']and f.stat().st_size==v['size']and full['files'][n]==v
build=json.loads((a.build/'manifest.json').read_text())
assert build['passed']and build['existing_abi_unchanged']and not build['abi_symbol_set_exact']and build['vm_baseline_sources_and_objects_restored']
assert sha(a.build/'libart.so')==build['binary_sha256']
assert sha(a.original_build/'libart.so')==build['original_unstripped_binary_sha256']
assert set(build['patches'])=={'art-agent-bionic-symbol.patch','art-boot-resource-path.patch','art-interface-object-dispatch.patch'}
for n,h in build['patches'].items():assert sha(repo/'native/compat/patches'/n)==h
for n,v in build['source_manifest'].items():
 r=Path(n);assert not r.is_absolute()and'..'not in r.parts
 assert sha(a.original_build/'patched'/n)==v['patched_sha256']
# Compare the actual candidate to the actual packaged baseline. Addresses,
# sizes and symbol table indices are implementation details; type/binding/
# visibility/defined section/name/version are all retained in this audit.
def abi(file):
 text=subprocess.check_output(['readelf','--dyn-syms','--wide',str(file)],text=True)
 return set(' '.join(l.split()[3:])for l in text.splitlines()if l.strip()and l.strip()[0].isdigit())
old=abi(oldroot/'lib/libart.so');new=abi(a.build/'libart.so')
expected='FUNC WEAK PROTECTED 11 _ZN3art6mirror7IfTable20GetMethodArrayOrNullILNS_17VerifyObjectFlagsE0ELNS_17ReadBarrierOptionE0EEENS_6ObjPtrINS0_12PointerArrayEEEi'
assert not(old-new)and new-old=={expected}and build['added_weak_symbol']==expected
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir():d.chmod(0o755)
after=copy.deepcopy(before);manifest=after['install_manifest'];changes=after['changes'];updated=[]
def install(file,name,mode=0o644):
 target=root/name;assert not target.is_symlink();target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target);target.chmod(mode)
 value=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);changes[name]=manifest['files'][name]=value;assert name not in manifest['symlinks'];updated.append(name)
install(a.build/'libart.so','lib/libart.so',full['files']['lib/libart.so']['mode'])
install(a.build/'manifest.json','share/build/art-interface-dispatch/isolated-build.json')
for n in build['patches']:install(repo/'native/compat/patches'/n,'share/build/art-interface-dispatch/patches/'+n)
for n in build['source_manifest']:install(a.original_build/'patched'/n,'share/build/art-interface-dispatch/sources/'+n)
agent=json.loads((oldroot/'share/build/art-agent-manifest.json').read_text())
assert agent['files']['libart.so']['sha256']==full['files']['lib/libart.so']['sha256']
assert agent['files']['libopenjdkjvmti.so']['sha256']==full['files']['lib/libopenjdkjvmti.so']['sha256']
agent['files']['libart.so']['sha256']=build['binary_sha256']
if 'size'in agent['files']['libart.so']:agent['files']['libart.so']['size']=(a.build/'libart.so').stat().st_size
agent['exported_imported_abi_unchanged']=False
agent['existing_exported_imported_abi_unchanged']=True
agent['exported_imported_abi_backward_compatible']=True
agent['exact_symbol_set']=False
agent['added_weak_inline_helpers']=[expected]
agent['interface_object_dispatch']=dict(build_manifest_sha256=sha(a.build/'manifest.json'),source_patches=build['patches'])
tmp=a.output/'agent.json';tmp.write_text(json.dumps(agent,indent=2)+'\n');install(tmp,'share/build/art-agent-manifest.json');tmp.unlink()
runtime=json.loads((oldroot/'runtime.json').read_text());runtime['private_art_agent'].pop('native_abi_unchanged',None)
runtime['private_art_agent'].update(manifest_sha256=sha(root/'share/build/art-agent-manifest.json'),native_abi_backward_compatible=True,exact_symbol_set=False)
runtime['interface_object_dispatch']=dict(schema='saildroid-art-interface-object-v1',scope='All applications; resolve public Object methods through the actual class vtable before interface IMT dispatch',libart_sha256=build['binary_sha256'],existing_abi_preserved=True,added_weak_inline_helpers=[expected],phone_staged=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert after['product_manifest']==before['product_manifest']and manifest['symlinks']==full['symlinks']and set(full['files'])<=set(manifest['files'])
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert sha(root/'lib/libopenjdkjvmti.so')==full['files']['lib/libopenjdkjvmti.so']['sha256']
for n,v in changes.items():
 assert sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']
 parts=Path(n).parts;assert all(str(Path(*parts[:i]))not in manifest['symlinks']for i in range(1,len(parts)))
after['art_interface_overlay']=dict(schema='saildroid-art-interface-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,build_manifest_sha256=sha(a.build/'manifest.json'),packager_sha256=sha(Path(__file__)),updated_files=sorted(updated),existing_abi_preserved=True,exact_symbol_set=False,added_weak_inline_helpers=[expected],jvmti_library_unchanged=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(a.build/'libart.so')==build['binary_sha256']
for n,h in build['patches'].items():assert sha(repo/'native/compat/patches'/n)==h
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('ART_INTERFACE_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
