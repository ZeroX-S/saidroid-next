#!/usr/bin/env python3
"""Actual root-owned isolated filesystem regression for v2 duplicate CA cleanup."""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ca_overlay_removals import apply_ca_removals
p=argparse.ArgumentParser();p.add_argument('--certificate',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert os.getuid()==0 and not a.output.exists();cert=a.certificate.read_bytes();digest=hashlib.sha256(cert).hexdigest();name='system/etc/security/cacerts/'+digest+'.pem';target='system/etc/security/cacerts/11223344.0';entry=dict(sha256=digest,size=len(cert),mode=0o644)
work=Path(tempfile.mkdtemp(prefix='saidroid-ca-overlay-contract-'));results=[]
def fixture(label):
 folder=work/label;folder.mkdir();base=folder/'predecessor';root=folder/'new-release'
 for d in [base,root]:
  (d/Path(name).parent).mkdir(parents=True)
  for q in [d,*[q for q in d.rglob('*')if q.is_dir()]]:q.chmod(0o755)
 (base/name).write_bytes(cert);(base/name).chmod(0o644);os.link(base/name,root/name);(root/target).write_bytes(cert);(root/target).chmod(0o644)
 prior=dict(files={name:copy.deepcopy(entry)},symlinks={})
 meta=dict(schema='saildroid-native-overlay-v2',remove_files={name:copy.deepcopy(entry)},ca_alias_cleanup=dict(certificates={name:dict(target=target,sha256=digest)}),install_manifest=dict(files={target:copy.deepcopy(entry)},symlinks={}),changes={target:copy.deepcopy(entry)})
 return base,root,prior,meta
try:
 base,root,prior,meta=fixture('positive');assert(base/name).stat().st_nlink==2;assert apply_ca_removals(root,meta,prior)==1
 assert not(root/name).exists()and(base/name).read_bytes()==cert and(root/target).read_bytes()==cert and(base/name).stat().st_nlink==1
 results.append(dict(case='new-hardlinked-release-only',passed=True))
 cases=['schema-v1','writable-root','writable-parent','source-symlink','canonical-symlink','source-wrong-mode','canonical-wrong-mode','source-wrong-owner','canonical-wrong-owner','missing-canonical','canonical-wrong-bytes','old-entry-mismatch','removed-name-still-installed','mapping-missing','canonical-not-payload','arbitrary-path']
 for case in cases:
  base,root,prior,meta=fixture(case)
  if case=='schema-v1':meta['schema']='saildroid-native-overlay-v1'
  elif case=='writable-root':root.chmod(0o777)
  elif case=='writable-parent':(root/Path(name).parent).chmod(0o777)
  elif case=='source-symlink':(root/name).unlink();(root/name).symlink_to(base/name)
  elif case=='canonical-symlink':(root/target).unlink();(root/target).symlink_to(base/name)
  elif case=='source-wrong-mode':(root/name).chmod(0o640)
  elif case=='canonical-wrong-mode':(root/target).chmod(0o640)
  elif case=='source-wrong-owner':os.chown(root/name,65534,65534)
  elif case=='canonical-wrong-owner':os.chown(root/target,65534,65534)
  elif case=='missing-canonical':(root/target).unlink()
  elif case=='canonical-wrong-bytes':(root/target).write_bytes(b'not the original certificate')
  elif case=='old-entry-mismatch':prior['files'][name]['sha256']='f'*64
  elif case=='removed-name-still-installed':meta['install_manifest']['files'][name]=entry
  elif case=='mapping-missing':meta['ca_alias_cleanup']['certificates']={}
  elif case=='canonical-not-payload':meta['changes']={}
  elif case=='arbitrary-path':meta['remove_files']={'usr/bin/real-program':entry}
  rejected=False
  try:apply_ca_removals(root,meta,prior)
  except (AssertionError,FileNotFoundError,KeyError):rejected=True
  predecessor_bytes_unchanged=(base/name).read_bytes()==cert
  source_not_unlinked=(root/name).exists()or(root/name).is_symlink()
  results.append(dict(case=case,passed=rejected and predecessor_bytes_unchanged and source_not_unlinked,rejected=rejected,predecessor_bytes_unchanged=predecessor_bytes_unchanged,source_not_unlinked=source_not_unlinked))
finally:shutil.rmtree(work)
v=dict(scope='Real root-owned private filesystem only: exact duplicate CA removal from new hardlinked release, predecessor bytes preserved, malformed/schema/owner/mode/link/hash cases fail before unlink. No phone, installed CA or system trust store mutation.',passed=all(v['passed']for v in results),source_sha256=hashlib.sha256((Path(__file__).resolve().parents[1]/'ca_overlay_removals.py').read_bytes()).hexdigest(),test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),cases=results,private_fixture_removed=not work.exists());a.output.write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v,indent=2));assert v['passed']and v['private_fixture_removed']
