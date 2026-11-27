#!/usr/bin/env python3
"""Bind documented DexMaker interop to the actual app cache before its class loader.

Changes one existing boot implementation class and adds one cache helper over
an exact prior runtime class tree. Frozen shared runtime sources stay untouched.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','product','baseline','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();repo=Path(__file__).resolve().parents[2];os.umask(0o022);assert not a.output.exists();a.output.mkdir(parents=True);sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();product=json.loads((a.product/'manifest.json').read_text());baseline=json.loads((a.baseline/'manifest.json').read_text());assert baseline['passed']and baseline['schema']=='saildroid-device-identifiers-compat-v1'and baseline['product_manifest_sha256']==sha(a.product/'manifest.json')and sha(a.baseline/'runtime.jar')==baseline['runtime_sha256']
source=repo/'scripts/device/SdClassLoaderNamespaces.java';helper=repo/'scripts/runtime/application-code-cache-compat/SdApplicationCodeCache.java';assert sha(source)==product['sources']['scripts/device/SdClassLoaderNamespaces.java'];text=source.read_text();needle='        System.err.println("SDNAMESPACE=code_cache_bound|package="';assert text.count(needle)==1
prepared=a.output/'source';prepared.mkdir();namespace=prepared/'SdClassLoaderNamespaces.java';namespace.write_text(text.replace(needle,'        SdApplicationCodeCache.bind(app);'+needle.lstrip()))
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar';assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439';commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(a.output/name).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
def entries(jar):
 with zipfile.ZipFile(jar)as z:
  assert len(z.namelist())==len(set(z.namelist()));return {n:z.read(n)for n in z.namelist()}
def dex(folder,target,name):run([str(java/'java'),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),*map(str,sorted(folder.rglob('*.class')))],name)
before={str(f.relative_to(a.baseline/'classes')):sha(f)for f in(a.baseline/'classes').rglob('*.class')};assert before==baseline['classfiles_after'];dex(a.baseline/'classes',a.output/'baseline-runtime.jar','baseline-d8.log');assert entries(a.output/'baseline-runtime.jar')==entries(a.baseline/'runtime.jar')
classes=a.output/'overlay-classes';classes.mkdir();run([str(java/'javac'),'--release','8','-nowarn','-cp',str(framework)+':'+str(a.baseline/'classes'),'-d',str(classes),str(namespace),str(helper)],'javac.log')
merged=a.output/'classes';shutil.copytree(a.baseline/'classes',merged)
for f in classes.rglob('*.class'):dst=merged/f.relative_to(classes);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dst)
after={str(f.relative_to(merged)):sha(f)for f in merged.rglob('*.class')};assert set(after)-set(before)=={'SdApplicationCodeCache.class'}and all(after[n]==h for n,h in before.items()if n!='SdClassLoaderNamespaces.class')and before['SdClassLoaderNamespaces.class']!=after['SdClassLoaderNamespaces.class'];dex(merged,a.output/'runtime.jar','d8.log')
spec=importlib.util.spec_from_file_location('cache_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc);old,_=enc.dex_members(entries(a.baseline/'runtime.jar')['classes.dex']);new,_=enc.dex_members(entries(a.output/'runtime.jar')['classes.dex']);assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old);added=set(new)-set(old);assert added=={'LSdApplicationCodeCache;-><init>()V','LSdApplicationCodeCache;->directory(Ljava/io/File;IZ)V','LSdApplicationCodeCache;->bind(Landroid/content/pm/ApplicationInfo;)V'}
record=dict(schema='saildroid-application-code-cache-compat-v1',scope=__doc__,passed=True,builder_sha256=sha(Path(__file__)),baseline_manifest_sha256=sha(a.baseline/'manifest.json'),baseline_runtime_sha256=sha(a.baseline/'runtime.jar'),product_manifest_sha256=sha(a.product/'manifest.json'),source_manifest=dict(baseline_namespaces=sha(source),prepared_namespaces=sha(namespace),cache_helper=sha(helper)),classfiles_before=before,classfiles_after=after,new_members=sorted(added),all_existing_member_flags_and_native_declarations_preserved=True,runtime_sha256=sha(a.output/'runtime.jar'),commands=commands,phone_staged=False)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('APPLICATION_CODE_CACHE_RUNTIME=compiled|existing_classes_changed=1|new_helper=1|existing_members_native=retained|phone_staged=false')
