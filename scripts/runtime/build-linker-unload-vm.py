#!/usr/bin/env python3
"""Build one reviewed fix in a private copy of the accepted VM linker source.

Neither the workspace's nested checkout nor the accepted VM build is edited.
The unpatched and patched libraries use the same copied source/configuration.
"""
from pathlib import Path
import argparse,hashlib,json,re,shutil,subprocess
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path);p.add_argument('--additional-patch',type=Path,action='append',default=[]);p.add_argument('--allow-added-export',action='append',default=[]);a=p.parse_args()
assert not a.output.exists();a.output.mkdir(parents=True)
repo=Path(__file__).resolve().parents[2];source=a.output/'source'
shutil.copytree(a.source,source,ignore=shutil.ignore_patterns('.git','builddir','__pycache__'),symlinks=True)
inputs={str(f.relative_to(source)):hashlib.sha256(f.read_bytes()).hexdigest()for f in source.rglob('*')if f.is_file()and not f.is_symlink()}
build=a.output/'build';log=a.output/'build.log'
with log.open('w')as out:
 subprocess.run(['meson','setup',str(build),str(source)],check=True,stdout=out,stderr=subprocess.STDOUT)
 subprocess.run(['ninja','-C',str(build),'libdl_bio.so.0.0.1'],check=True,stdout=out,stderr=subprocess.STDOUT)
control=a.output/'control/libdl_bio.so.0';control.parent.mkdir();shutil.copyfile(build/'libdl_bio.so.0.0.1',control)
patch=repo/'native/compat/patches/bionic-unload-debug-map.patch';shutil.copyfile(patch,a.output/patch.name)
file=source/'linker/linker.c';before=file.read_bytes()
assert b'glibc' in before and b'static void apkenv_notify_gdb_of_load_unused' in before,'Expected accepted glibc debug-map policy'
subprocess.run(['patch','-p1','--fuzz=0','-i',str(patch)],cwd=source,check=True)
additional=[]
for extra in a.additional_patch:
 assert extra.is_file()
 subprocess.run(['patch','-p1','--fuzz=0','-i',str(extra.resolve())],cwd=source,check=True)
 shutil.copyfile(extra,a.output/extra.name)
 additional.append(dict(name=extra.name,sha256=hashlib.sha256(extra.read_bytes()).hexdigest()))
with log.open('a')as out:subprocess.run(['ninja','-C',str(build),'libdl_bio.so.0.0.1'],check=True,stdout=out,stderr=subprocess.STDOUT)
fixed=a.output/'libdl_bio.so.0';shutil.copyfile(build/'libdl_bio.so.0.0.1',fixed)
def exports(file):
 s=subprocess.check_output(['readelf','--dyn-syms','--wide',str(file)],text=True)
 return sorted(' '.join(line.split()[3:])for line in s.splitlines()if len(line.split())>=8 and line.split()[4]in['GLOBAL','WEAK'])
# Compare names, binding, visibility and definition/undefined status, not addresses.
def signatures(file):
 s=subprocess.check_output(['readelf','--dyn-syms','--wide',str(file)],text=True);result=[]
 for line in s.splitlines():
  v=line.split()
  if len(v)>=8 and v[4]in['GLOBAL','WEAK']:result.append((v[3],v[4],v[5],v[6]=='UND',v[7]))
 return sorted(result)
old=set(signatures(control));new=set(signatures(fixed));added=new-old
allowed=set(a.allow_added_export);assert all(re.fullmatch(r'bionic_[A-Za-z0-9_]+',name)for name in allowed)
assert not old-new,'Patch removed or changed an existing linker ABI signature'
assert all(row[:4]==('FUNC','GLOBAL','DEFAULT',False)and row[4]in allowed for row in added),'Unexpected linker ABI/import addition'
assert {row[4]for row in added}==allowed,'Declared linker API addition differs from the actual export delta'
manifest=dict(scope='Private accepted-source snapshot plus reviewed linker patches',source=str(a.source),source_files=inputs,additional_patches=additional,patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),changed_source='linker/linker.c',before_source_sha256=hashlib.sha256(before).hexdigest(),after_source_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),control_sha256=hashlib.sha256(control.read_bytes()).hexdigest(),sha256=hashlib.sha256(fixed.read_bytes()).hexdigest(),library=str(fixed),exported_abi_unchanged=not added,exported_abi_backward_compatible=True,added_function_exports=sorted(allowed))
(a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps({k:v for k,v in manifest.items()if k!='source_files'},indent=2))
