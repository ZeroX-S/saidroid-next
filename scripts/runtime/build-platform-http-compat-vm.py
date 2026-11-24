#!/usr/bin/env python3
"""Compose one canonical API29 HTTP implementation and remove its framework duplicates.

All Java class bytes come from the pinned matching API29 input. Every other
accepted framework class/resource remains byte-identical. This explicitly
migrates obsolete pre-API29 HTTP implementation internals; it is not an ABI-
identical replacement and requires original HTTP and runtime regression gates.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,subprocess,zipfile,gzip
p=argparse.ArgumentParser(description=__doc__)
for n in ['inputs','baseline-framework','core-library','reference','baseline-http','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();framework=a.inputs/'android-all-10-robolectric-5803371.jar';r8=a.inputs/'r8-8.3.37.jar'
assert sha(framework)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'and sha(r8)=='59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
reference=a.reference/'okhttp.jar';refmeta=json.loads((a.reference/'manifest.json').read_text());assert refmeta['passed']and sha(reference)==refmeta['reference_jar_sha256']=='9a9e38f789ad754f5fd7a45e7c6e4d05cab2258f255344dfb9c2bc6c8f017c81'
assert not a.output.exists();a.output.mkdir(parents=True);java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin'
def entries(f):
 with zipfile.ZipFile(f)as z:
  assert len(z.namelist())==len(set(z.namelist()));return {n:z.read(n)for n in z.namelist()if not n.endswith('/')}
def writejar(f,values):
 with zipfile.ZipFile(f,'x',zipfile.ZIP_DEFLATED)as z:
  for n,v in sorted(values.items()):z.writestr(n,v)
all_input=entries(framework);http={n:v for n,v in all_input.items()if n.endswith('.class')and n.startswith('com/android/okhttp/')};assert len(http)==241
jar=a.output/'okhttp-classes.jar';writejar(jar,http);target=a.output/'okhttp-hostdex.jar';commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(a.output/(name+'.log')).open('x')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
run([str(java/'java'),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(target),str(jar)],'http-d8')
resources_before={n:v for n,v in entries(a.baseline_http).items()if not n.endswith('.dex')}
with zipfile.ZipFile(target,'a',zipfile.ZIP_DEFLATED)as z:
 for n,v in resources_before.items():z.writestr(n,v)
spec=importlib.util.spec_from_file_location('http_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(reference)as z:rm,_=enc.dex_members(z.read('classes.dex'))
with zipfile.ZipFile(target)as z:nm,_=enc.dex_members(z.read('classes.dex'))
# Compiler-generated accessors may differ. Every real canonical method/field is retained.
def generated(s):return '->access$'in s or '->$values()'in s or '$$ExternalSynthetic'in s or '$$Lambda$'in s or '$-CC;'in s
missing={s:rm[s][0]for s in set(rm)-set(nm)if not generated(s)};assert not missing,missing
native=lambda m:{n:v[0]for n,v in m.items()if v[0]&0x100};assert native(nm)==native(rm)=={}
fm=json.loads((a.baseline_framework/'manifest.json').read_text());oldclasses=entries(a.baseline_framework/'classes.jar');owned={n:v for n,v in oldclasses.items()if n.startswith('com/android/okhttp/')};assert owned.keys()==http.keys()and all(owned[n]==v for n,v in http.items()),'Refuse to remove differing canonical class bytes'
first=a.baseline_framework/'framework29-classes.jar';assert sha(first)==fm['files'][first.name]['sha256'];resources={n:v for n,v in entries(first).items()if not n.endswith('.dex')};assert {n:hashlib.sha256(v).hexdigest()for n,v in resources.items()}==fm['resources']
kept={n:v for n,v in oldclasses.items()if n not in http};source=a.output/'framework-source.jar';writejar(source,dict(kept,**resources));fw=a.output/'framework'
run(['python3',str(repo/'scripts/runtime/build-framework.py'),str(a.inputs),str(a.core_library),str(fw),'--source',str(source)],'framework-d8')
newclasses=entries(fw/'classes.jar');assert newclasses==kept;newfm=json.loads((fw/'manifest.json').read_text());assert newfm['resources']==fm['resources']and len(newfm['files'])==len(fm['files'])==5
# Check all canonical hidden-API members present after normal classfile D8. Compiler
# accessor names are private and are never exposed through an exemption.
flags=dict(line.split(',',1)for line in gzip.decompress((repo/'build/evidence/cts-frame-repair-20261031/aosp-extra/android10-hiddenapi-flags.csv.gz').read_bytes()).decode().splitlines())
missing_known=set(rm)&set(flags)-set(nm);assert not missing_known,missing_known
record=dict(schema='saildroid-platform-http-compat-v1',scope=__doc__,passed=True,builder_sha256=sha(Path(__file__)),source_input_sha256=sha(framework),reference_jar_sha256=sha(reference),reference_inventory_sha256=sha(a.reference/'manifest.json'),classfile_count=len(http),class_jar_sha256=sha(jar),http_jar_sha256=sha(target),baseline_http_jar_sha256=sha(a.baseline_http),retained_http_resources={n:hashlib.sha256(v).hexdigest()for n,v in resources_before.items()},classes={n:hashlib.sha256(v).hexdigest()for n,v in http.items()},reference_compiler_accessor_members_absent=sorted(set(rm)-set(nm)),all_canonical_non_generated_members_retained=True,canonical_native_declarations=native(nm),framework_baseline_manifest_sha256=sha(a.baseline_framework/'manifest.json'),framework_manifest_sha256=sha(fw/'manifest.json'),removed_framework_classes={n:hashlib.sha256(v).hexdigest()for n,v in owned.items()},all_other_framework_classes_and_resources_byte_identical=True,commands=commands)
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('PLATFORM_HTTP_MODULE=built|canonical_classes=241|framework_duplicate_sources_removed=241|all_other_framework_class_resources=unchanged|phone_changed=false')
