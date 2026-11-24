#!/usr/bin/env python3
"""Build genuine classpath cache lifetimes over hash-verified current core modules."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','core-module','libart-module','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/classpath-cache-lifecycle-compat';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();meta=json.loads((source/'sources.json').read_text());assert len(meta['files'])==2 and not a.output.exists();a.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar';assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
def entries(f):
 with zipfile.ZipFile(f)as z:assert len(z.namelist())==len(set(z.namelist()));return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
modules={'core-oj':a.core_module,'core-libart':a.libart_module};paths={};before={};commands=[]
for key,d in modules.items():
 m=json.loads((d/'manifest.json').read_text());assert m['passed'];bm=m['components'][key];jar=d/(key+'-classes.jar');dex=d/(key+'-hostdex.jar');assert sha(jar)==bm['class_jar_sha256']and sha(dex)==bm['sha256'];before[key]=entries(jar);assert {n:hashlib.sha256(v).hexdigest()for n,v in before[key].items()}==bm['classes'];paths[key]=(jar,dex)
for n,v in meta['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(source/(Path(n).stem+'.patch'))==v['patch_sha256']
def run(cmd,name):
 commands.append(cmd)
 with(a.output/name).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
def compile(folder,files,name):
 folder.mkdir()
 for i,f in enumerate(files):
  run([str(java/'javac'),'-source','8','-target','8','-nowarn',*(['-g']if f.name=='ClassLoader.java'else[]),'-bootclasspath',str(paths['core-oj'][0])+':'+str(paths['core-libart'][0])+':'+str(framework),'-d',str(folder),str(f)],str(i)+'-'+name)
 return {str(f.relative_to(folder)):f.read_bytes()for f in folder.rglob('*.class')}
unmodified=compile(a.output/'unmodified-classes',[repo/v['baseline_source']for n,v in sorted(meta['files'].items())],'unmodified-javac.log');reproduced={}
for n,v in unmodified.items():
 key='core-oj'if n.startswith('java/')else'core-libart';assert n in before[key]and before[key][n]==v,'Unmodified class must reproduce byte-identical: '+n;reproduced[n]=hashlib.sha256(v).hexdigest()
overlay=compile(a.output/'classes',[source/n for n in sorted(meta['files'])],'javac.log');assert set(unmodified)<=set(overlay)
spec=importlib.util.spec_from_file_location('lifecycle_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc);components={}
for key in modules:
 selected={n:v for n,v in overlay.items()if n.startswith('java/')==(key=='core-oj')};assert selected
 after=dict(before[key]);after.update(selected);assert all(after[n]==v for n,v in before[key].items()if n not in selected);jar=a.output/(key+'-classes.jar')
 with zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as z:
  for n,v in sorted(after.items()):z.writestr(n,v)
 target=a.output/(key+'-hostdex.jar');run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(jar)],key+'-d8.log');resources={n:v for n,v in entries(paths[key][1]).items()if not n.endswith('.dex')}
 with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
  for n,v in resources.items():z.writestr(n,v)
 with zipfile.ZipFile(paths[key][1])as z:old,_=enc.dex_members(z.read('classes.dex'))
 with zipfile.ZipFile(target)as z:new,_=enc.dex_members(z.read('classes.dex'))
 assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old);assert {n:v[0]for n,v in new.items()if v[0]&0x100}=={n:v[0]for n,v in old.items()if v[0]&0x100};added=set(new)-set(old)
 if key=='core-oj':assert not added
 else:assert added and all(n.startswith(('Llibcore/io/ClassPathURLStreamHandler;->scopedCache','Llibcore/io/ClassPathURLStreamHandler;->access$','Llibcore/io/ClassPathURLStreamHandler$ScopedArchiveCache','Llibcore/io/ClassPathURLStreamHandler$ScopedClassPathURLConnection;->useCachedArchive','Llibcore/io/ClassPathURLStreamHandler$ScopedClassPathURLConnection;->cachedArchive()Z'))for n in added),added
 components[key]=dict(sha256=sha(target),class_jar_sha256=sha(jar),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=sorted(n for n,v in selected.items()if before[key].get(n)!=v),resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_existing_members_and_native_declarations_preserved=True,all_existing_member_flags_preserved=True,added_members=sorted(added))
record=dict(schema='saildroid-classpath-cache-lifecycle-compat-v1',scope=meta['scope']+' Canonical hidden API and matching boot images required. No phone/full CTS acceptance.',passed=True,builder_sha256=sha(Path(__file__)),source_meta_sha256=sha(source/'sources.json'),sources=meta,unmodified_classfiles_byte_identical=True,reproduced_classfiles=reproduced,inputs={str(f):sha(f)for d in modules.values()for f in[d/'manifest.json',*d.glob('*-classes.jar'),*d.glob('*-hostdex.jar')]},components=components,commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('CLASSPATH_CACHE_LIFECYCLE_MODULE=built|unmodified_reproduced=true|native_unchanged=true|phone=false')
