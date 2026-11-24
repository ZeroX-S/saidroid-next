#!/usr/bin/env python3
"""Wrap verified224 payload with explicit new-root-only CA/TZ relocation deployment schema."""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,tarfile
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--expected-baseline-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2';full=before['install_manifest'];oldroot=a.baseline/'payload'
for n,v in before['changes'].items():assert sha(oldroot/n)==v['sha256']and stat.S_IMODE((oldroot/n).stat().st_mode)==v['mode']
assert set(before['remove_files'])-set(before['ca_alias_cleanup']['certificates'])=={'usr/share/zoneinfo/tzlookup.xml'}
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root)
for p in [root,*root.rglob('*')]:
 if p.is_dir()and not p.is_symlink():p.chmod(0o755)
after=copy.deepcopy(before);after['schema']='saildroid-native-overlay-v3';manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target);target.chmod(0o644);v=dict(sha256=sha(target),size=target.stat().st_size,mode=0o644);manifest['files'][n]=changes[n]=v;updated.append(n)
deployers=['ca_overlay_removals.py','overlay_v3_removals.py','deploy-native-overlay-v3.py','native-overlay-device-v3.py']
for n in deployers:install(repo/'scripts/runtime'/n,'share/build/deployment-v3/'+n)
install(Path(__file__),'share/build/deployment-v3/packager.py')
name='usr/share/zoneinfo/tzlookup.xml';target='apex/com.android.runtime.debug/etc/tz/tzlookup.xml'
after['release_file_cleanup']=dict(schema='saildroid-timezone-file-relocation-v1',scope='New release only; oldXML removed only if present in exact original predecessor, replacement runtime module XML verified first. Predecessor and active release untouched.',relocations={name:dict(old_entry=before['remove_files'][name],target=target,target_entry=full['files'][target])},deployment_sources_sha256={n:sha(repo/'scripts/runtime'/n)for n in deployers})
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)and manifest['symlinks']==full['symlinks'];after['deployment_v3_overlay']=dict(schema='saildroid-deployment-v3-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=updated,all_runtime_binary_java_data_bytes_unchanged=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('OVERLAY_V3_DEPLOYMENT=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|runtime_binary_java_data=unchanged|phone_staged=false')
