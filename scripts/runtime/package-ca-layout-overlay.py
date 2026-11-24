#!/usr/bin/env python3
"""Create a v2 overlay with identical trust anchors under canonical CA aliases.

The146 redundant SHA256.pem directory entries are removed only from a new
release. Old overlay deployers reject schema v2. No certificate bytes change.
"""
from pathlib import Path
import argparse,copy,hashlib,json,os,re,shutil,stat,subprocess,tarfile
from ca_overlay_removals import validate_ca_removals
os.umask(0o022);p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','output']:p.add_argument(n,type=Path)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v1'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;r=Path(n);assert not r.is_absolute()and'..'not in r.parts
 assert not f.is_symlink()and sha(f)==v['sha256']and stat.S_IMODE(f.stat().st_mode)==v['mode']and f.stat().st_size==v['size']and full['files'][n]==v
deployment_sources={n:sha(repo/'scripts/runtime'/n)for n in ['ca_overlay_removals.py','deploy-native-overlay-v2.py','native-overlay-device-v2.py']}
index_path=oldroot/'share/build/ca-subject-index.json';index=json.loads(index_path.read_text());certificates=index['certificates'];assert len(certificates)==146
removed={};mapping={};targets=set();fingerprints={};groups={}
for entry in certificates:
 source,target=entry['source'],entry['target'];assert re.fullmatch(r'system/etc/security/cacerts/[a-f0-9]{64}\.pem',source)
 assert re.fullmatch(r'system/etc/security/cacerts/[a-f0-9]{8}\.[0-9]+',target)
 assert source not in removed and target not in targets;targets.add(target)
 assert full['files'][source]['sha256']==full['files'][target]['sha256']==entry['sha256']
 assert sha(oldroot/target)==entry['sha256']
 subject=subprocess.check_output(['openssl','x509','-in',str(oldroot/target),'-noout','-subject_hash_old'],text=True).strip();assert subject==Path(target).name.split('.')[0]
 groups.setdefault(subject,[]).append(int(Path(target).suffix[1:]))
 der=subprocess.check_output(['openssl','x509','-in',str(oldroot/target),'-outform','DER']);fingerprints[target]=hashlib.sha256(der).hexdigest()
 removed[source]=full['files'][source];mapping[source]=dict(target=target,sha256=entry['sha256'])
assert len(set(fingerprints.values()))==146 and all(sorted(v)==list(range(len(v)))for v in groups.values())
assert {n for n in full['files']if n.startswith('system/etc/security/cacerts/')}==set(removed)|targets
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir():d.chmod(0o755)
after=copy.deepcopy(before);after['schema']='saildroid-native-overlay-v2';manifest=after['install_manifest'];changes=after['changes'];after['remove_files']=removed
after['ca_alias_cleanup']=dict(schema='saildroid-canonical-ca-aliases-v1',certificates=mapping,unique_der_sha256=sorted(fingerprints.values()),root_count=146,trust_anchor_bytes_unchanged=True,predecessor_archive_sha256=a.expected_baseline_sha256,source_index_sha256=sha(index_path),requires_deployer_schema='saildroid-native-overlay-v2',deployment_source_sha256=deployment_sources,phone_staged=False)
for n in removed:
 manifest['files'].pop(n);changes.pop(n,None)
 if (root/n).exists():assert not(root/n).is_symlink();(root/n).unlink()
updated=[]
def install(file,name,mode=0o644):
 t=root/name;t.parent.mkdir(parents=True,exist_ok=True);assert not t.is_symlink();shutil.copyfile(file,t);t.chmod(mode);v=dict(sha256=sha(t),size=t.stat().st_size,mode=mode);changes[name]=manifest['files'][name]=v;updated.append(name)
for n in ['ca_overlay_removals.py','deploy-native-overlay-v2.py','native-overlay-device-v2.py']:install(repo/'scripts/runtime'/n,'share/build/ca-alias-cleanup/'+n)
runtime=json.loads((oldroot/'runtime.json').read_text());runtime['canonical_ca_layout']=dict(schema='saildroid-canonical-ca-aliases-v1',scope='All apps; same146 unique trust anchors and identical certificate bytes under Android subject_hash_old.N filenames only',roots=146,unique_der_sha256=sorted(fingerprints.values()),redundant_legacy_aliases_removed=146)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values());validate_ca_removals(after,full)
assert manifest['symlinks']==full['symlinks']and after['product_manifest']==before['product_manifest']
assert set(full['files'])-set(manifest['files'])==set(removed)
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in removed and n not in updated)
for n,v in changes.items():assert sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
for n,h in deployment_sources.items():assert sha(repo/'scripts/runtime'/n)==h
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('CA_LAYOUT_OVERLAY=packaged|schema=v2|same_unique_roots=146|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
