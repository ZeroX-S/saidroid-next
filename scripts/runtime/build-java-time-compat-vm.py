#!/usr/bin/env python3
"""Opt-in Android10 Java-time compatibility module, over verified private core inputs.

Uses unmodified Android10 sources and calendar data. Requires subsequent normal
hidden API encoding and matching boot images. Does not touch tests or the clock.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','core-module','icu-build','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/java-time-compat';sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest();meta=json.loads((source/'sources.json').read_text());a.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar'
assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
previous=json.loads((a.core_module/'manifest.json').read_text());assert previous['schema']=='saildroid-keystore-core-compat-v1'and previous['passed'];old=previous['components']['core-oj'];core=a.core_module/'core-oj-classes.jar';dex=a.core_module/'core-oj-hostdex.jar';assert sha(core)==old['class_jar_sha256']and sha(dex)==old['sha256']
icu=a.icu_build/'core-libart-classes.jar';im=json.loads((a.icu_build/'manifest.json').read_text())
def entries(f):
 with zipfile.ZipFile(f)as z:
  assert len(z.namelist())==len(set(z.namelist()))
  return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
before=entries(core);iclasses=entries(icu)
assert {n:hashlib.sha256(v).hexdigest()for n,v in before.items()}==old['classes']
assert {n:hashlib.sha256(v).hexdigest()for n,v in iclasses.items()}==im['core-libart']['classes']
assert b'icudt63b'in iclasses['android/icu/impl/ICUData.class']and b'icudt58b'not in iclasses['android/icu/impl/ICUData.class']
for n,v in meta['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']
classes=a.output/'classes';classes.mkdir();commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(a.output/(name+'.log')).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
run([str(java/'javac'),'-source','8','-target','8','-nowarn','-bootclasspath',str(core)+':'+str(icu)+':'+str(framework),'-d',str(classes),*[str(source/n)for n in meta['files']if n.endswith('.java')]],'javac')
overlay={str(f.relative_to(classes)):f.read_bytes()for f in classes.rglob('*.class')};expected={'java/time/chrono/JapaneseEra.class','java/time/format/DateTimeTextProvider.class','java/time/format/DateTimeTextProvider$LocaleStore.class','java/time/format/DateTimeTextProvider$1.class','java/time/format/DateTimeTextProvider$2.class'};assert set(overlay)==expected,set(overlay)
assert b'icudt63b'in overlay['java/time/format/DateTimeTextProvider.class']and b'icudt58b'not in overlay['java/time/format/DateTimeTextProvider.class']
after=dict(before);after.update(overlay);assert set(after)==set(before)and all(after[n]==v for n,v in before.items()if n not in overlay)
jar=a.output/'core-oj-classes.jar'
with zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as z:
 for n,v in sorted(after.items()):z.writestr(n,v)
target=a.output/'core-oj-hostdex.jar';run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(jar)],'d8')
resources={n:v for n,v in entries(dex).items()if not n.endswith('.dex')};assert resources['calendars.properties']==(repo/meta['files']['calendars.properties']['baseline_source']).read_bytes();resources['calendars.properties']=(source/'calendars.properties').read_bytes()
with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
 for n,v in resources.items():z.writestr(n,v)
spec=importlib.util.spec_from_file_location('encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(dex)as z:om,_=enc.dex_members(z.read('classes.dex'))
with zipfile.ZipFile(target)as z:nm,_=enc.dex_members(z.read('classes.dex'))
assert set(om)<=set(nm)and all(om[n][0]==nm[n][0]for n in om),'Existing member flags/native declarations must remain unchanged'
added=set(nm)-set(om);assert added=={'Ljava/time/chrono/JapaneseEra;->REIWA:Ljava/time/chrono/JapaneseEra;','Ljava/time/chrono/JapaneseEra;->getDisplayName(Ljava/time/format/TextStyle;Ljava/util/Locale;)Ljava/lang/String;'},added
record=dict(schema='saildroid-java-time-compat-v1',scope='Opt-in raw core module, unchanged Android10 sources and Reiwa data; ICU63 compile-time adapter correction. No phone/full CTS acceptance; requires hidden API encoding and matching boot images.',passed=True,builder_sha256=sha(Path(__file__)),sources=meta,source_meta_sha256=sha(source/'sources.json'),inputs={str(f):sha(f)for f in [core,dex,icu,a.core_module/'manifest.json',a.icu_build/'manifest.json']},components={'core-oj':dict(sha256=sha(target),class_jar_sha256=sha(jar),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=sorted(overlay),resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_existing_member_flags_and_native_declarations_preserved=True,added_members=sorted(added))},commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('JAVA_TIME_MODULE=built|reiwa=android10|icu_constant=63|phone_touched=false')
