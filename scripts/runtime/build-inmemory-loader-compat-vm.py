#!/usr/bin/env python3
"""Opt-in Android10 in-memory loader native-path signatures and canonical class access.

Retains all native declarations; requires canonical hidden API encoding
and matching boot images before execution. Never changes APKs or shared sources.
"""
from pathlib import Path
import argparse, hashlib, importlib.util, json, os, subprocess, zipfile

p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','core-module','java-time-module','output']:
    p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022)
repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/inmemory-loader-compat'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
meta=json.loads((source/'sources.json').read_text())
assert len(meta['files'])==3 and not a.output.exists()
a.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin'
framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar'
assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'
assert sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
baseline=json.loads((a.core_module/'manifest.json').read_text())['components']['core-libart']
core=a.core_module/'core-libart-classes.jar';dex=a.core_module/'core-libart-hostdex.jar'
assert sha(dex)==baseline['sha256']
oj=a.java_time_module/'core-oj-classes.jar'
ojmeta=json.loads((a.java_time_module/'manifest.json').read_text())
assert ojmeta['passed'] and sha(oj)==ojmeta['components']['core-oj']['class_jar_sha256']
def entries(f):
    with zipfile.ZipFile(f)as z:
        assert len(z.namelist())==len(set(z.namelist()))
        return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
before=entries(core)
assert {n:hashlib.sha256(v).hexdigest()for n,v in before.items()}==baseline['classes']
for n,v in meta['files'].items():
    assert sha(source/n)==v['sha256'] and sha(repo/v['baseline_source'])==v['baseline_sha256']
    assert sha(repo/v['reference'])==v['reference_sha256']
classes=a.output/'classes';classes.mkdir();commands=[]
def run(cmd,name):
    commands.append(cmd)
    with(a.output/(name+'.log')).open('x')as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
run([str(java/'javac'),'-source','8','-target','8','-nowarn','-bootclasspath',
     str(oj)+':'+str(core)+':'+str(framework),'-d',str(classes),
     *[str(source/n)for n in sorted(meta['files'])]],'javac')
overlay={str(f.relative_to(classes)):f.read_bytes()for f in classes.rglob('*.class')}
assert set(overlay)=={n for n in before if any(n.startswith('dalvik/system/'+top)for top in ['BaseDexClassLoader','DexPathList','InMemoryDexClassLoader']) and n.endswith('.class')}
after=dict(before);after.update(overlay)
assert after.keys()==before.keys() and all(after[n]==v for n,v in before.items()if n not in overlay)
import struct
# javap emits full class/member visibility for this small changed set.
for label,jarpath in [('before',core)]:
    run([str(java/'javap'),'-p','-s','-classpath',str(jarpath),'dalvik.system.DexPathList'],'javap-'+label)
jar=a.output/'core-libart-classes.jar'
with zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as z:
    for n,v in sorted(after.items()):z.writestr(n,v)
target=a.output/'core-libart-hostdex.jar'
run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release',
     '--min-api','29','--lib',str(framework),'--output',str(target),str(jar)],'d8')
resources={n:v for n,v in entries(dex).items()if not n.endswith('.dex')}
with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
    for n,v in resources.items():z.writestr(n,v)
spec=importlib.util.spec_from_file_location('os199encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py')
enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(dex)as z:old,_=enc.dex_members(z.read('classes.dex'))
with zipfile.ZipFile(target)as z:new,_=enc.dex_members(z.read('classes.dex'))
promoted='Ldalvik/system/DexPathList;->makeInMemoryDexElements([Ljava/nio/ByteBuffer;Ljava/util/List;)[Ldalvik/system/DexPathList$Element;'
assert old[promoted][0]==10 and new[promoted][0]==9
assert set(old)<=set(new) and all(old[n][0]==new[n][0]for n in old if n!=promoted)
expected={'Ldalvik/system/InMemoryDexClassLoader;-><init>([Ljava/nio/ByteBuffer;Ljava/lang/String;Ljava/lang/ClassLoader;)V','Ldalvik/system/BaseDexClassLoader;-><init>([Ljava/nio/ByteBuffer;Ljava/lang/String;Ljava/lang/ClassLoader;)V','Ldalvik/system/DexPathList;-><init>(Ljava/lang/ClassLoader;[Ljava/nio/ByteBuffer;Ljava/lang/String;)V'}
assert set(new)-set(old)==expected
assert {n:v[0]for n,v in new.items()if v[0]&0x100}=={n:v[0]for n,v in old.items()if v[0]&0x100}
record=dict(schema='saildroid-inmemory-loader-compat-v1',scope='Opt-in raw core-libart module: Android10 in-memory loader native-path constructors/search ordering and canonical DexPathList public/legacy method access. All old declarations/native flags retained except documented canonical access promotion. Requires canonical encoding/matching images. No phone/full CTS acceptance',passed=True,
    builder_sha256=sha(Path(__file__)),source_meta_sha256=sha(source/'sources.json'),sources=meta,
    inputs={str(f):sha(f)for f in [core,dex,oj,a.core_module/'manifest.json',a.java_time_module/'manifest.json']},
    components={'core-libart':dict(sha256=sha(target),class_jar_sha256=sha(jar),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=sorted(overlay),resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_old_members_and_native_declarations_preserved=True,canonical_method_access_promotions={promoted:dict(before=10,after=9)},added_members=sorted(expected))},commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print('INMEMORY_LOADER_COMPAT=built|added_members=3|old_members_and_natives=preserved|canonical_access_promoted=1|phone_changed=false')
