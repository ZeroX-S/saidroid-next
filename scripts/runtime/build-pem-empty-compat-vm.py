#!/usr/bin/env python3
"""Build zero-payload PEM compatibility, retaining strict nonempty parsing."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','bc-module','core-module','libart-module','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/pem-empty-compat';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();meta=json.loads((source/'sources.json').read_text());assert len(meta['files'])==1 and not a.output.exists();a.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar';assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439';base=json.loads((a.bc_module/'manifest.json').read_text());assert base['passed'];component=base['components']['bouncycastle'];jar=a.bc_module/'bouncycastle-classes.jar';dex=a.bc_module/'bouncycastle-hostdex.jar';assert sha(jar)==component['class_jar_sha256']and sha(dex)==component['sha256'];core=a.core_module/'core-oj-classes.jar';libart=a.libart_module/'core-libart-classes.jar'
for k,m,f in [('core-oj',a.core_module,core),('core-libart',a.libart_module,libart)]:
 v=json.loads((m/'manifest.json').read_text());assert v['passed']and sha(f)==v['components'][k]['class_jar_sha256']
def entries(f):
 with zipfile.ZipFile(f)as z:assert len(z.namelist())==len(set(z.namelist()));return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
before=entries(jar);assert {n:hashlib.sha256(v).hexdigest()for n,v in before.items()}==component['classes'];prepared=a.output/'baseline-sources';prepared.mkdir();files=[];candidate_files=[]
jarjar=repo/'third_party/art-standalone/prebuilts/misc/common/jarjar/jarjar-1.4.jar';assert sha(jarjar)=='d816cd2000afb2b787b473df2bd82dad9bb4e2ae0b72b0b1b6d8a914f40c68dd'
for n,v in meta['files'].items():
 assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']and sha(source/'pem-empty.patch')==v['patch_sha256'];s=(repo/v['baseline_source']).read_text().replace('org.bouncycastle.','com.android.org.bouncycastle.');assert hashlib.sha256(s.encode()).hexdigest()==v['relocated_baseline_sha256'];f=prepared/Path(n).name;f.write_text((repo/v['baseline_source']).read_text());files.append(f);candidate=a.output/('candidate-source/'+Path(n).name);candidate.parent.mkdir(exist_ok=True);candidate.write_text((source/n).read_text().replace('com.android.org.bouncycastle.','org.bouncycastle.'));candidate_files.append(candidate)
commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(a.output/name).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
reverse=a.output/'reverse-rules.txt';reverse.write_text('rule com.android.org.bouncycastle.** org.bouncycastle.@1\n');forward=repo/'third_party/art-standalone/external/bouncycastle/jarjar-rules.txt';assert forward.read_text().strip()=='rule org.bouncycastle.** com.android.@0';unrelocated=a.output/'unrelocated-dependencies.jar';run([str(java/'java'),'-jar',str(jarjar),'process',str(reverse),str(jar),str(unrelocated)],'reverse-jarjar.log')
def compile(directory,sources,name):
 directory.mkdir();run([str(java/'javac'),'-g','-source','8','-target','8','-nowarn','-bootclasspath',str(core)+':'+str(libart)+':'+str(unrelocated)+':'+str(framework),'-d',str(directory),*map(str,sources)],name)
 raw=a.output/(directory.name+'-raw.jar');relocated=a.output/(directory.name+'-relocated.jar')
 with zipfile.ZipFile(raw,'x',zipfile.ZIP_DEFLATED)as z:
  for f in sorted(directory.rglob('*.class')):z.writestr(str(f.relative_to(directory)),f.read_bytes())
 run([str(java/'java'),'-jar',str(jarjar),'process',str(forward),str(raw),str(relocated)],directory.name+'-jarjar.log');return {n:v for n,v in entries(relocated).items()if n.endswith('.class')}
reproduced=compile(a.output/'unmodified-classes',files,'unmodified-javac.log');assert reproduced and all(n in before and before[n]==v for n,v in reproduced.items()),'Unmodified PEM classes must reproduce byte-identical'
overlay=compile(a.output/'classes',candidate_files,'javac.log');assert overlay.keys()==reproduced.keys();after=dict(before);after.update(overlay);assert all(after[n]==v for n,v in before.items()if n not in overlay);changed=sorted(n for n,v in overlay.items()if before[n]!=v);assert changed==['com/android/org/bouncycastle/jcajce/provider/asymmetric/x509/PEMUtil.class']
out=a.output/'bouncycastle-classes.jar'
with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED)as z:
 for n,v in sorted(after.items()):z.writestr(n,v)
target=a.output/'bouncycastle-hostdex.jar';run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(out)],'d8.log');resources={n:v for n,v in entries(dex).items()if not n.endswith('.dex')}
with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
 for n,v in resources.items():z.writestr(n,v)
spec=importlib.util.spec_from_file_location('pem_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(dex)as z:old,_=enc.dex_members(z.read('classes.dex'))
with zipfile.ZipFile(target)as z:new,_=enc.dex_members(z.read('classes.dex'))
assert set(old)==set(new)and all(old[n][0]==new[n][0]for n in old)and {n:v[0]for n,v in old.items()if v[0]&0x100}=={n:v[0]for n,v in new.items()if v[0]&0x100}
record=dict(schema='saildroid-pem-empty-compat-v1',scope=meta['scope']+' Raw module requires canonical hidden API and matching boot images; not phone/fullCTS acceptance.',passed=True,builder_sha256=sha(Path(__file__)),source_meta_sha256=sha(source/'sources.json'),sources=meta,unmodified_classfiles_byte_identical=True,reproduced_classfiles={n:hashlib.sha256(v).hexdigest()for n,v in reproduced.items()},inputs={str(f):sha(f)for f in[jar,dex,core,libart,jarjar,forward,a.bc_module/'manifest.json',a.core_module/'manifest.json',a.libart_module/'manifest.json']},components={'bouncycastle':dict(sha256=sha(target),class_jar_sha256=sha(out),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=changed,resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_existing_member_flags_and_native_declarations_preserved=True,added_members=[])},commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('PEM_EMPTY_MODULE=built|unmodified_reproduced=true|no_new_members=true|native_unchanged=true|phone=false')
