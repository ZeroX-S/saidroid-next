#!/usr/bin/env python3
"""Build canonical Android10 JAR verification provider compatibility over a verified current core."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','core-module','libart-module','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/jar-verification-compat';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();meta=json.loads((source/'sources.json').read_text());assert len(meta['files'])==1 and not a.output.exists();a.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar'
assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
def entries(f):
 with zipfile.ZipFile(f)as z:
  assert len(z.namelist())==len(set(z.namelist()))
  return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
modules={'core-oj':a.core_module,'core-libart':a.libart_module};paths={};baselines={}
for key,d in modules.items():
 m=json.loads((d/'manifest.json').read_text());assert m['passed'];bm=m['components'][key];jar=d/(key+'-classes.jar');dex=d/(key+'-hostdex.jar');assert sha(jar)==bm['class_jar_sha256']and sha(dex)==bm['sha256'];assert {n:hashlib.sha256(v).hexdigest()for n,v in entries(jar).items()}==bm['classes'];baselines[key]=bm;paths[key]=(jar,dex)
for n,v in meta['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['reference'])==v['reference_sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']
classes=a.output/'classes';classes.mkdir();commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(a.output/(name+'.log')).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
run([str(java/'javac'),'-source','8','-target','8','-nowarn','-bootclasspath',str(paths['core-oj'][0])+':'+str(paths['core-libart'][0])+':'+str(framework),'-d',str(classes),*[str(source/n)for n in sorted(meta['files'])]],'javac')
overlay={str(f.relative_to(classes)):f.read_bytes()for f in classes.rglob('*.class')};assert set(overlay)=={'sun/security/jca/Providers.class'}
before=entries(paths['core-oj'][0]);assert set(overlay)<=set(before);after=dict(before);after.update(overlay);assert all(after[n]==v for n,v in before.items()if n not in overlay)
jar=a.output/'core-oj-classes.jar'
with zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as z:
 for n,v in sorted(after.items()):z.writestr(n,v)
target=a.output/'core-oj-hostdex.jar';run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(jar)],'core-oj-d8')
resources={n:v for n,v in entries(paths['core-oj'][1]).items()if not n.endswith('.dex')}
with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
 for n,v in resources.items():z.writestr(n,v)
spec=importlib.util.spec_from_file_location('url_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(paths['core-oj'][1])as z:old,_=enc.dex_members(z.read('classes.dex'))
with zipfile.ZipFile(target)as z:new,_=enc.dex_members(z.read('classes.dex'))
assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old)
assert {n:v[0]for n,v in new.items()if v[0]&0x100}=={n:v[0]for n,v in old.items()if v[0]&0x100}
added=set()
assert set(new)-set(old)==added,(set(new)-set(old),added-(set(new)-set(old)))
components={'core-oj':dict(sha256=sha(target),class_jar_sha256=sha(jar),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=sorted(overlay),resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_existing_members_and_native_declarations_preserved=True,all_existing_member_flags_preserved=True,added_members=sorted(added))}
record=dict(schema='saildroid-jar-verification-compat-v1',scope=meta['scope']+' Requires canonical hiddenAPI encoding and matching images. No phone/full CTS acceptance.',passed=True,builder_sha256=sha(Path(__file__)),source_meta_sha256=sha(source/'sources.json'),sources=meta,inputs={str(f):sha(f)for d in modules.values()for f in[d/'manifest.json',*d.glob('*-classes.jar'),*d.glob('*-hostdex.jar')]},components=components,commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('JAR_VERIFICATION_MODULE=built|new_members='+str(len(added))+'|existing_member_flags=unchanged|native_declarations=unchanged|phone_changed=false')
