#!/usr/bin/env python3
"""Restore canonical Android10 initial provider order and TLS factory resource."""
from pathlib import Path
import argparse,hashlib,json,zipfile,shutil,os
p=argparse.ArgumentParser(description=__doc__)
for n in ['core-module','reference','reference-manifest','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);assert not a.output.exists();a.output.mkdir(parents=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();meta=json.loads((a.core_module/'manifest.json').read_text());assert meta['passed'];core=meta['components']['core-oj'];reference=json.loads(a.reference_manifest.read_text());assert sha(a.reference)==reference[a.reference.name]['sha256'];name='java/security/security.properties'
classes=a.core_module/'core-oj-classes.jar';dex=a.core_module/'core-oj-hostdex.jar';assert sha(classes)==core['class_jar_sha256']and sha(dex)==core['sha256']
shutil.copyfile(classes,a.output/classes.name);(a.output/classes.name).chmod(0o644)
with zipfile.ZipFile(dex)as z:entries={n:z.read(n)for n in z.namelist()};assert name in entries;before={n:hashlib.sha256(v).hexdigest()for n,v in entries.items()};old=before[name];entries[name]=a.reference.read_bytes()
with zipfile.ZipFile(a.output/dex.name,'x',zipfile.ZIP_DEFLATED)as z:
 for n,v in entries.items():z.writestr(n,v)
with zipfile.ZipFile(a.output/dex.name)as z:after={n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()}
assert before.keys()==after.keys()and[n for n in before if before[n]!=after[n]]==[name]
newmeta=dict(schema='saildroid-crypto-resource-compat-v1',scope='Resource-only canonical Android10 initial crypto provider order and socketfactory settings. All Java class/DEX bytes unchanged. Existing product SdTls later reorders JSSE as before; no code/clock/anchors/assertions change. Requires matching images. No phone/fullCTS acceptance.',passed=True,builder_sha256=sha(Path(__file__)),reference=dict(path=str(a.reference),sha256=sha(a.reference),url=reference[a.reference.name]['url']),baseline_manifest_sha256=sha(a.core_module/'manifest.json'),baseline_manifest_path=str(a.core_module/'manifest.json'),components={'core-oj':dict(sha256=sha(a.output/dex.name),class_jar_sha256=sha(a.output/classes.name),classes=core['classes'],resources={**core['resources'],name:sha(a.reference)},added_members=[],all_existing_member_flags_and_native_declarations_preserved=True,resource_only_change=name,resource_before_sha256=old)},phone_mutations=0)
(a.output/'manifest.json').write_text(json.dumps(newmeta,indent=2)+'\n');print('CRYPTO_SECURITY_RESOURCE=BUILT|class_and_DEX_bytes=unchanged|canonical_provider_order=true|phone_changed=false')
