#!/usr/bin/env python3
"""Build canonical Android10 system-BC policy over verified raw core modules."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','core-module','libart-module','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/crypto-policy-compat'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();meta=json.loads((source/'sources.json').read_text());assert len(meta['files'])==12 and sum(v.get('checks_added',0)for v in meta['files'].values())==21 and not a.output.exists();a.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar'
assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
previous=json.loads((a.core_module/'manifest.json').read_text());assert previous['passed'];baseline=previous['components']['core-oj'];core=a.core_module/'core-oj-classes.jar';dex=a.core_module/'core-oj-hostdex.jar'
assert sha(core)==baseline['class_jar_sha256']and sha(dex)==baseline['sha256']
libart=a.libart_module/'core-libart-classes.jar';lm=json.loads((a.libart_module/'manifest.json').read_text());assert lm['passed']and sha(libart)==lm['components']['core-libart']['class_jar_sha256']
def entries(f):
 with zipfile.ZipFile(f)as z:
  assert len(z.namelist())==len(set(z.namelist()))
  return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
before=entries(core);assert {n:hashlib.sha256(v).hexdigest()for n,v in before.items()}==baseline['classes']
for n,v in meta['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
classes=a.output/'classes';classes.mkdir();commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(a.output/(name+'.log')).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
run([str(java/'javac'),'-source','8','-target','8','-nowarn','-bootclasspath',str(core)+':'+str(libart)+':'+str(framework),'-d',str(classes),*[str(source/n)for n in sorted(meta['files'])]],'javac')
overlay={str(f.relative_to(classes)):f.read_bytes()for f in classes.rglob('*.class')};tops=[n[:-5]for n in meta['files']];expected_classes={n for n in before if n.endswith('.class')and any(n==top+'.class'or n.startswith(top+'$')for top in tops)}
assert set(overlay)==expected_classes,(set(overlay)-expected_classes,expected_classes-set(overlay))
after=dict(before);after.update(overlay);assert after.keys()==before.keys()and all(after[n]==v for n,v in before.items()if n not in overlay)
jar=a.output/'core-oj-classes.jar'
with zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as z:
 for n,v in sorted(after.items()):z.writestr(n,v)
target=a.output/'core-oj-hostdex.jar';run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(jar)],'d8')
resources={n:v for n,v in entries(dex).items()if not n.endswith('.dex')}
with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
 for n,v in resources.items():z.writestr(n,v)
spec=importlib.util.spec_from_file_location('crypto_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(dex)as z:old,_=enc.dex_members(z.read('classes.dex'))
with zipfile.ZipFile(target)as z:new,_=enc.dex_members(z.read('classes.dex'))
assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old)
expected={
'Lsun/security/jca/Providers;->SYSTEM_BOUNCY_CASTLE_PROVIDER:Ljava/security/Provider;',
'Lsun/security/jca/Providers;->DEFAULT_MAXIMUM_ALLOWABLE_TARGET_API_LEVEL_FOR_BC_DEPRECATION:I',
'Lsun/security/jca/Providers;->maximumAllowableApiLevelForBcDeprecation:I',
'Lsun/security/jca/Providers;->DEPRECATED_ALGORITHMS:Ljava/util/Set;',
'Lsun/security/jca/Providers;->setMaximumAllowableApiLevelForBcDeprecation(I)V',
'Lsun/security/jca/Providers;->getMaximumAllowableApiLevelForBcDeprecation()I',
'Lsun/security/jca/Providers;->checkBouncyCastleDeprecation(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V',
'Lsun/security/jca/Providers;->checkBouncyCastleDeprecation(Ljava/security/Provider;Ljava/lang/String;Ljava/lang/String;)V',
'Lsun/security/jca/Providers;->checkBouncyCastleDeprecation(Ljava/lang/String;Ljava/lang/String;)V'}
assert set(new)-set(old)==expected,set(new)-set(old)
assert {n:v[0]for n,v in new.items()if v[0]&0x100}=={n:v[0]for n,v in old.items()if v[0]&0x100}
record=dict(schema='saildroid-crypto-policy-compat-v1',scope=meta['scope']+' Raw opt-in module; requires canonical hiddenAPI encoding/matching images. No phone/full CTS acceptance.',passed=True,builder_sha256=sha(Path(__file__)),source_meta_sha256=sha(source/'sources.json'),sources=meta,inputs={str(f):sha(f)for f in[core,dex,libart,a.core_module/'manifest.json',a.libart_module/'manifest.json']},components={'core-oj':dict(sha256=sha(target),class_jar_sha256=sha(jar),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=sorted(overlay),resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_existing_member_flags_and_native_declarations_preserved=True,added_members=sorted(expected))},commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('CRYPTO_POLICY_MODULE=built|new_members=9|canonical_selection_checks=21|native_declarations=unchanged|phone_changed=false')
