#!/usr/bin/env python3
"""Propagate declared instrumentation metadata through generic package APIs."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','product','baseline','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();repo=Path(__file__).resolve().parents[2];os.umask(0o022);assert not a.output.exists();a.output.mkdir(parents=True);sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();product=json.loads((a.product/'manifest.json').read_text());baseline=json.loads((a.baseline/'manifest.json').read_text());assert baseline['passed']and baseline['schema']=='saildroid-application-code-cache-compat-v1'and baseline['product_manifest_sha256']==sha(a.product/'manifest.json')and sha(a.baseline/'runtime.jar')==baseline['runtime_sha256']
source=repo/'scripts/runtime/instrumentation-metadata-compat';meta=json.loads((source/'sources.json').read_text());assert set(meta['files'])=={'SdInstrumentation.java','SdPackageManagerService.java','SdApkPackage.java'}
for n,v in meta['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']==product['sources'][v['baseline_source']]and sha(source/(Path(n).stem+'.patch'))==v['patch_sha256']
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar';assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439';commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(a.output/name).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
def entries(jar):
 with zipfile.ZipFile(jar)as z:assert len(z.namelist())==len(set(z.namelist()));return {n:z.read(n)for n in z.namelist()}
def dex(folder,target,name):run([str(java/'java'),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),*map(str,sorted(folder.rglob('*.class')))],name)
before={str(f.relative_to(a.baseline/'classes')):sha(f)for f in(a.baseline/'classes').rglob('*.class')};assert before==baseline['classfiles_after'];dex(a.baseline/'classes',a.output/'baseline-runtime.jar','baseline-d8.log');assert entries(a.output/'baseline-runtime.jar')==entries(a.baseline/'runtime.jar')
oldclasses=a.output/'unmodified-classes';oldclasses.mkdir();run([str(java/'javac'),'--release','8','-nowarn','-cp',str(framework)+':'+str(a.baseline/'classes'),'-d',str(oldclasses),*[str(repo/v['baseline_source'])for n,v in sorted(meta['files'].items())]],'unmodified-javac.log');reproduced={str(f.relative_to(oldclasses)):sha(f)for f in oldclasses.rglob('*.class')};assert reproduced and all(h==before[n]for n,h in reproduced.items()),'Unmodified existing classes must reproduce byte-identical'
classes=a.output/'overlay-classes';classes.mkdir();run([str(java/'javac'),'--release','8','-nowarn','-cp',str(framework)+':'+str(a.baseline/'classes'),'-d',str(classes),*[str(source/n)for n in sorted(meta['files'])]],'javac.log')
merged=a.output/'classes';shutil.copytree(a.baseline/'classes',merged)
for f in classes.rglob('*.class'):
 n=str(f.relative_to(classes));assert n in before and n.split('$')[0].removesuffix('.class')in ['SdInstrumentation','SdPackageManagerService','SdApkPackage'];dst=merged/n;shutil.copyfile(f,dst)
after={str(f.relative_to(merged)):sha(f)for f in merged.rglob('*.class')};assert after.keys()==before.keys();changed=sorted(n for n,h in before.items()if after[n]!=h);assert {'SdInstrumentation.class','SdPackageManagerService.class','SdApkPackage.class'}<=set(changed)<=set(reproduced);dex(merged,a.output/'runtime.jar','d8.log')
spec=importlib.util.spec_from_file_location('metadata_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc);old,_=enc.dex_members(entries(a.baseline/'runtime.jar')['classes.dex']);new,_=enc.dex_members(entries(a.output/'runtime.jar')['classes.dex']);assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old);added=set(new)-set(old);assert added=={'LSdInstrumentation;->info(Landroid/content/ComponentName;I)Landroid/content/pm/InstrumentationInfo;'}
assert {n:v[0]for n,v in old.items()if v[0]&0x100}=={n:v[0]for n,v in new.items()if v[0]&0x100}
record=dict(schema='saildroid-instrumentation-metadata-compat-v1',scope=meta['scope'],passed=True,builder_sha256=sha(Path(__file__)),sources=meta,source_meta_sha256=sha(source/'sources.json'),baseline_manifest_sha256=sha(a.baseline/'manifest.json'),baseline_runtime_sha256=sha(a.baseline/'runtime.jar'),product_manifest_sha256=sha(a.product/'manifest.json'),unmodified_classfiles_byte_identical=True,reproduced_classfiles=reproduced,classfiles_before=before,classfiles_after=after,changed_classes=changed,new_members=sorted(added),all_existing_member_flags_and_native_declarations_preserved=True,runtime_sha256=sha(a.output/'runtime.jar'),commands=commands,phone_staged=False)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('INSTRUMENTATION_METADATA_RUNTIME=compiled|existing_baseline_byteidentical=true|added_members=1|native_unchanged=true|phone_staged=false')
