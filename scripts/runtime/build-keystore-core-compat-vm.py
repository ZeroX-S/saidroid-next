#!/usr/bin/env python3
"""Opt-in private JKS/BKS compatibility module over verified existing core inputs.

Does not edit the normal core builder, hidden API policy, platform/test APKs,
provider registry, trust anchors or installed component. Encode the output with
normal Android hidden API metadata and rebuild matching boot images before use.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,zipfile,importlib.util
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','core-build','bc-classes','bc-dex','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/keystore-compat';meta=json.loads((source/'sources.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();a.output.mkdir(parents=True);java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar';assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c';assert sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
core_meta=json.loads((a.core_build/'manifest.json').read_text());core_classes=a.core_build/'core-oj-classes.jar';core_dex=a.core_build/'core-oj-hostdex.jar';assert sha(core_dex)==core_meta['core-oj']['sha256']
def entries(path):
 with zipfile.ZipFile(path)as z:
  assert len(z.namelist())==len(set(z.namelist())),path
  return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
before={'core-oj':entries(core_classes),'bouncycastle':entries(a.bc_classes)}
assert {n:hashlib.sha256(v).hexdigest()for n,v in before['core-oj'].items()}==core_meta['core-oj']['classes']
for n,v in meta['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']
classes=a.output/'classes';classes.mkdir();commands=[]
def run(command,name):
 commands.append(command)
 with(a.output/(name+'.log')).open('x')as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
run([str(java/'javac'),'-source','8','-target','8','-nowarn','-bootclasspath',str(core_classes)+':'+str(a.bc_classes)+':'+str(framework),'-d',str(classes),*[str(source/n)for n in sorted(meta['files'])]],'javac')
overlay={str(f.relative_to(classes)):f.read_bytes()for f in classes.rglob('*.class')};assert len(overlay)==12
spec=importlib.util.spec_from_file_location('core_api_boundary',repo/'scripts/runtime/encode-hiddenapi-vm.py');encoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(encoder)
records={}
for name,old_dex in [('core-oj',core_dex),('bouncycastle',a.bc_dex)]:
 applied={n:v for n,v in overlay.items()if n.startswith('sun/'if name=='core-oj'else'com/android/')};assert applied and set(applied)<=set(before[name])
 after=dict(before[name]);after.update(applied);assert set(after)==set(before[name]);assert all(v==after[n]for n,v in before[name].items()if n not in applied)
 jar=a.output/(name+'-classes.jar')
 with zipfile.ZipFile(jar,'x',zipfile.ZIP_DEFLATED)as z:
  for n,v in sorted(after.items()):z.writestr(n,v)
 target=a.output/(name+'-hostdex.jar');run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(jar)],name+'-d8')
 resources={n:v for n,v in entries(old_dex).items()if not n.endswith('.dex')}
 with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
  for n,v in resources.items():z.writestr(n,v)
 with zipfile.ZipFile(old_dex)as z:old_members,_=encoder.dex_members(z.read('classes.dex'))
 with zipfile.ZipFile(target)as z:new_members,_=encoder.dex_members(z.read('classes.dex'))
 assert set(old_members)<=set(new_members),(name,'Member removed')
 assert all(old_members[n][0]==new_members[n][0]for n in old_members),(name,'Access/native declaration changed')
 added=set(new_members)-set(old_members);signature='->engineSetEntry(Ljava/lang/String;Ljava/security/KeyStore$Entry;Ljava/security/KeyStore$ProtectionParameter;)V';expected={'Lsun/security/provider/JavaKeyStore'+n+';'+signature for n in ['', '$JKS','$CaseExactJKS']}if name=='core-oj'else {'Lcom/android/org/bouncycastle/crypto/CryptoServicesRegistrar$$ExternalSyntheticBackportWithForwarding0;->m(Ljava/util/concurrent/atomic/AtomicReference;Ljava/lang/Object;Ljava/lang/Object;)Z'};assert added==expected,(name,added)
 records[name]=dict(sha256=sha(target),class_jar_sha256=sha(jar),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=sorted(applied),resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_existing_member_flags_and_native_declarations_preserved=True,added_members=sorted(added))
record=dict(schema='saildroid-keystore-core-compat-v1',scope='Opt-in raw DEX/class module; requires normal hidden API encoding and exact matching boot images. No phone/full CTS acceptance.',passed=True,builder_sha256=sha(Path(__file__)),source_meta_sha256=sha(source/'sources.json'),source_meta=meta,inputs={str(f):sha(f)for f in [core_classes,core_dex,a.bc_classes,a.bc_dex,a.core_build/'manifest.json']},components=records,commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('KEYSTORE_CORE_MODULE=built|core_oj_and_BKS=true|existing_declarations_preserved=true|phone_touched=false')
