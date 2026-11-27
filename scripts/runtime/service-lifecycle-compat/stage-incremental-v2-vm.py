from pathlib import Path
import os,subprocess,json,base64,hashlib
r=Path('/media/psf/Home/WorkSpace/saidroid-next');b=Path(__file__).parent;env=dict(os.environ,SSHPASS=os.environ['SSHPASS']);held=False;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();proof=json.loads((b/'package.json').read_text());assert proof['passed'];bundle=Path(proof['bundle']);assert sha(bundle/'native-overlay.tar.gz')==proof['tarball_sha256'];meta=json.loads((bundle/'overlay.json').read_text());before=json.loads((r/'build/evidence/qq-camera-capability304-20261103-v1/bundle/overlay.json').read_text())['install_manifest'];wanted=meta['install_manifest'];diff=[n for n,v in wanted['files'].items()if before['files'].get(n)!=v];assert len(diff)==len(proof['updated_files'])and set(diff)==set(proof['updated_files']);payload=Path(proof['native_payload']);files={n:base64.b64encode((payload/n).read_bytes()).decode()for n in diff};assert sum(len(v)for v in files.values())<4000000
body=r'''from pathlib import Path
import json,os,subprocess,hashlib,shutil,stat,base64
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert 'ID=sailfishos'in Path('/etc/sailfish-release').read_text()
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()=='4fab5d11-f3fd-4a5f-8724-f20785e27485'
assert subprocess.check_output(['pidof','lipstick'],text=True).strip()=='9463'
assert Path('/sys/class/backlight/panel0-backlight/actual_brightness').read_text().strip()=='0'
assert str(Path('/home/art/api29-root').resolve())=='/home/art/releases/api29-r293-native-candidate'
base=Path('/home/art/releases/api29-r304-native-candidate');assert sha(base/'install-manifest.json')=='4a578c62268d5092cd92558f8a8b951a3199ca36ee99527216bb2590ed64d3d6'
old=json.loads((base/'install-manifest.json').read_text());assert old==BEFORE
for n,v in old['files'].items():
 p=base/n;assert p.is_file()and not p.is_symlink()and p.stat().st_size==v['size']and stat.S_IMODE(p.stat().st_mode)==v['mode']and sha(p)==v['sha256'],n
release=Path('/home/art/releases/api29-r305-native-candidate');assert not release.exists()
assert (base/'system/etc/hosts').stat().st_nlink==1
inventory=[]
free_before=shutil.disk_usage('/home/art').free
release.mkdir()
# Link only immutable, fully verified regular files. No source chmod or write.
for n,v in WANTED['files'].items():
 p=release/n;p.parent.mkdir(parents=True,exist_ok=True)
 if n in FILES:
  data=base64.b64decode(FILES[n]);assert hashlib.sha256(data).hexdigest()==v['sha256'];p.write_bytes(data);p.chmod(v['mode'])
 elif n=='system/etc/hosts':
  assert old['files'][n]==v;shutil.copyfile(base/n,p);p.chmod(v['mode'])
 else:
  assert old['files'][n]==v;os.link(base/n,p)
for n,target in WANTED['symlinks'].items():
 p=release/n;p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(target)
for n,v in WANTED['files'].items():
 p=release/n;assert p.is_file()and not p.is_symlink()and p.stat().st_size==v['size']and stat.S_IMODE(p.stat().st_mode)==v['mode']and sha(p)==v['sha256'],n
assert {str(p.relative_to(release)):os.readlink(p)for p in release.rglob('*')if p.is_symlink()}==WANTED['symlinks']
assert (base/'system/etc/hosts').stat().st_nlink==1 and (release/'system/etc/hosts').stat().st_nlink==1
assert subprocess.check_output(['getcap',str(base/'libexec/saildroid-host')],text=True).split(' ',1)[-1]==subprocess.check_output(['getcap',str(release/'libexec/saildroid-host')],text=True).split(' ',1)[-1]
(release/'install-manifest.json').write_text(json.dumps(WANTED,indent=2)+'\n');(release/'install-manifest.json').chmod(0o644)
assert {str(p.relative_to(release))for p in release.rglob('*')if p.is_file()and not p.is_symlink()}==set(WANTED['files'])|{'install-manifest.json'}
print(json.dumps(dict(passed=True,release=str(release),files=len(WANTED['files']),links=len(WANTED['symlinks']),shared_immutable_files=len(WANTED['files'])-len(FILES),copied_files=len(FILES),copied_bytes=sum(len(base64.b64decode(v))for v in FILES.values()),manifest_sha256=sha(release/'install-manifest.json'),free_before=free_before,free_after=shutil.disk_usage('/home/art').free,hosts_nlink=(release/'system/etc/hosts').stat().st_nlink,source_hosts_nlink=(base/'system/etc/hosts').stat().st_nlink,brightness=Path('/sys/class/backlight/panel0-backlight/actual_brightness').read_text().strip(),daily=str(Path('/home/art/api29-root').resolve()),incomplete_inventory=inventory)))
'''
try:
 p=subprocess.run(['bash',str(r/'scripts/devlock.sh'),'acquire','0','lifecycle305-incremental-v2'],env=env,capture_output=True,text=True,timeout=20);print(p.stdout,p.stderr,flush=True);assert p.returncode==0;held=True
 body='WANTED='+repr(wanted)+'\nBEFORE='+repr(before)+'\nFILES='+repr(files)+'\nARCHIVE_SHA='+repr(proof['tarball_sha256'])+'\n'+body
 p=subprocess.run(['sshpass','-e','ssh','-o','ConnectTimeout=6','root@bonito','python3','-'],input=body,env=env,capture_output=True,text=True,timeout=90);(b/'stage-incremental-v2.stdout').write_text(p.stdout);(b/'stage-incremental-v2.stderr').write_text(p.stderr);print(p.stdout,p.stderr,flush=True);assert p.returncode==0;(b/'stage-incremental-v2.json').write_text(json.dumps(json.loads(p.stdout),indent=2)+'\n')
finally:
 if held:
  p=subprocess.run(['bash',str(r/'scripts/devlock.sh'),'release','lifecycle305-incremental-v2'],env=env,capture_output=True,text=True,timeout=20);print(p.stdout,p.stderr,flush=True)
