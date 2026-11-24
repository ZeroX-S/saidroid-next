#!/usr/bin/env python3
"""Compile the five source-owned API29 legacy JSSE overlays; no device writes."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,zipfile
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--classes',type=Path,default=Path('/tmp/art-build/art-standalone/out/host/common/obj/JAVA_LIBRARIES/wolfssljni-hostdex_intermediates/classes.jar'));p.add_argument('--java-home',type=Path,default=Path('/tmp/jdkfull/jdk-21.0.13+9'));a=p.parse_args()
os.umask(0o022);repo=Path(__file__).resolve().parents[2];directory=repo/'scripts/runtime/jsse-compat';entry=json.loads((directory/'sources.json').read_text());sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
assert entry['schema']=='saildroid-jsse-compat-sources-v1'and len(entry['files'])==5
assert sha(a.classes)==entry['baseline_classes_sha256']
sources=[]
for name,value in entry['files'].items():
 assert sha(repo/value['baseline_source'])==value['baseline_sha256'],'Original source changed: '+name
 assert sha(directory/name)==value['sha256'],'Overlay source changed: '+name
 if 'upstream_algorithm'in value:assert sha(directory/value['upstream_algorithm'])==value['upstream_sha256']
 sources.append(directory/name)
assert not a.output.exists();a.output.mkdir(parents=True);compiled=a.output/'classes';compiled.mkdir();inputs=repo/'build/codex-api29/inputs';framework=inputs/'android-all-10-robolectric-5803371.jar';java=a.java_home/'bin'
with(a.output/'build.log').open('x')as log:
 subprocess.run([str(java/'javac'),'--release','8','-nowarn','-cp',str(a.classes)+':'+str(framework),'-d',str(compiled),*map(str,sources)],check=True,stdout=log,stderr=subprocess.STDOUT)
 generated={str(f.relative_to(compiled)):f for f in compiled.rglob('*.class')};expected={n.removesuffix('.java')+'.class'for n in entry['files']};assert generated.keys()==expected
 merged=a.output/'classes.jar';changed=[];unchanged=[]
 with zipfile.ZipFile(a.classes)as before,zipfile.ZipFile(merged,'x',zipfile.ZIP_DEFLATED)as after:
  assert len([n for n in before.namelist()if n.endswith('.class')])==73
  for name in before.namelist():
   data=generated[name].read_bytes()if name in generated else before.read(name);after.writestr(name,data)
   (changed if data!=before.read(name)else unchanged).append(name)
 assert set(changed)==expected
 dex=a.output/'wolfssljni-hostdex.jar';subprocess.run([str(java/'java'),'-cp',str(inputs/'r8-8.3.37.jar'),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(dex),str(merged)],check=True,stdout=log,stderr=subprocess.STDOUT)
notice=[]
for source in sources:
 text=source.read_text();notice.append(source.name+'\n'+text[:text.index('*/')+2])
reference=(directory/'reference/KeyManagerImpl.android10.java').read_text();notice.append('Android10 key alias algorithm reference\n'+reference[:reference.index('*/')+2])
(a.output/'NOTICE').write_text('\n\n'.join(notice)+'\n')
manifest=dict(schema='saildroid-jsse-compat-api29-v1',source=entry,source_manifest_sha256=sha(directory/'sources.json'),baseline_classes_sha256=sha(a.classes),classes_sha256=sha(merged),file='wolfssljni-hostdex.jar',sha256=sha(dex),changed_classfiles=sorted(changed),existing_other_classfiles_unchanged=68,original_class_count=73,added_or_removed_classfiles=0,native_binaries_changed=False,native_trust_backend='Matching Android10 TrustManagerImpl/BoringSSL PKIX',legacy_tls_backend='Original native WolfSSL',notice_sha256=sha(a.output/'NOTICE'),framework_compile_input_sha256=sha(framework),r8_sha256=sha(inputs/'r8-8.3.37.jar'))
(a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('JSSE_COMPAT=compiled|original_classes=73|changed_classes=5|other_classes_unchanged=68|native_binaries_unchanged=true')
