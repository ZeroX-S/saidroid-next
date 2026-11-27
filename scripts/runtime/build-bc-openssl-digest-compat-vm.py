#!/usr/bin/env python3
"""Append canonical Android10 OpenSSLDigest to the current verified BC class module."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','bc-module','core-module','libart-module','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];source=repo/'scripts/runtime/core/bc-openssl-digest-compat';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();meta=json.loads((source/'sources.json').read_text());assert len(meta['files'])==1 and not a.output.exists();a.output.mkdir(parents=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar';assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
base=json.loads((a.bc_module/'manifest.json').read_text());assert base['passed'];baseline=base['components']['bouncycastle'];jar=a.bc_module/'bouncycastle-classes.jar';dex=a.bc_module/'bouncycastle-hostdex.jar';assert sha(jar)==baseline['class_jar_sha256']and sha(dex)==baseline['sha256']
core=a.core_module/'core-oj-classes.jar';cm=json.loads((a.core_module/'manifest.json').read_text());assert cm['passed']and sha(core)==cm['components']['core-oj']['class_jar_sha256']
libart=a.libart_module/'core-libart-classes.jar';lm=json.loads((a.libart_module/'manifest.json').read_text());assert lm['passed']and sha(libart)==lm['components']['core-libart']['class_jar_sha256']
def entries(p):
 with zipfile.ZipFile(p)as z:
  assert len(z.namelist())==len(set(z.namelist()))
  return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
before=entries(jar);assert {n:hashlib.sha256(v).hexdigest()for n,v in before.items()}==baseline['classes']
for n,v in meta['files'].items():
 assert sha(source/n)==v['sha256']and sha(repo/v['reference'])==v['reference_sha256']
 assert (source/n).read_text()==(repo/v['reference']).read_text().replace('org.bouncycastle.','com.android.org.bouncycastle.')
# The exact existing dependency definitions are verified through the whole pinned BC input manifest.
newclass='com/android/org/bouncycastle/crypto/digests/OpenSSLDigest.class';assert newclass not in before
for n in ['com/android/org/bouncycastle/crypto/digests/AndroidDigestFactory.class','com/android/org/bouncycastle/crypto/digests/AndroidDigestFactoryBouncyCastle.class','com/android/org/bouncycastle/crypto/digests/SHA1Digest.class']:assert n in before,n
classes=a.output/'classes';classes.mkdir();commands=[]
def run(cmd,n):
 commands.append(cmd)
 with(a.output/(n+'.log')).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
run([str(java/'javac'),'-source','8','-target','8','-nowarn','-bootclasspath',str(core)+':'+str(libart)+':'+str(jar)+':'+str(framework),'-d',str(classes),*[str(source/n)for n in meta['files']]],'javac')
overlay={str(f.relative_to(classes)):f.read_bytes()for f in classes.rglob('*.class')};assert set(overlay)=={newclass}|{'com/android/org/bouncycastle/crypto/digests/OpenSSLDigest$'+n+'.class'for n in ['MD5','SHA1','SHA224','SHA256','SHA384','SHA512']}
after=dict(before);after.update(overlay);assert set(after)-set(before)==set(overlay)and all(after[n]==v for n,v in before.items())
out=a.output/'bouncycastle-classes.jar'
with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED)as z:
 for n,v in sorted(after.items()):z.writestr(n,v)
target=a.output/'bouncycastle-hostdex.jar';run([str(java/'java'),'-Xmx4g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(out)],'d8');resources={n:v for n,v in entries(dex).items()if not n.endswith('.dex')}
with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
 for n,v in resources.items():z.writestr(n,v)
spec=importlib.util.spec_from_file_location('bc_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(dex)as z:old,_=enc.dex_members(z.read('classes.dex'))
with zipfile.ZipFile(target)as z:new,_=enc.dex_members(z.read('classes.dex'))
assert set(old)<=set(new)and all(old[n][0]==new[n][0]for n in old)
expected=set(new)-set(old);assert expected and all(n.startswith('Lcom/android/org/bouncycastle/crypto/digests/OpenSSLDigest')for n in expected)
assert{n:v[0]for n,v in new.items()if v[0]&0x100}=={n:v[0]for n,v in old.items()if v[0]&0x100}
record=dict(schema='saildroid-bc-openssl-digest-compat-v1',scope=meta['scope']+' Raw opt-in module, requires canonical encoding/matching images. No phone/fullCTS acceptance.',passed=True,builder_sha256=sha(Path(__file__)),sources=meta,source_meta_sha256=sha(source/'sources.json'),inputs={str(f):sha(f)for f in[jar,dex,core,libart,a.bc_module/'manifest.json',a.core_module/'manifest.json',a.libart_module/'manifest.json']},all_previous_class_bytes_identical=True,canonical_namespace_relocation_only=True,components={'bouncycastle':dict(sha256=sha(target),class_jar_sha256=sha(out),classes={n:hashlib.sha256(v).hexdigest()for n,v in after.items()},changed_classes=sorted(overlay),resources={n:hashlib.sha256(v).hexdigest()for n,v in resources.items()},all_existing_member_flags_and_native_declarations_preserved=True,added_members=sorted(expected))},commands=commands);(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('BC_OPENSSL_DIGEST_MODULE=built|canonical_class_added=true|all_old_class_bytes_identical=true|all_old_members_retained=true|phone_changed=false')
