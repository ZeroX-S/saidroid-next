#!/usr/bin/env python3
"""Restore the exact pre-native entries saved by the first overlay activation.
Run inside MeeGo Build while the device lock is held and all native hosts are
quiescent (scripts/perf/close-owned-vm.py). Does not delete any release.
"""
from pathlib import Path
import argparse,json,os,re,subprocess
p=argparse.ArgumentParser();p.add_argument('--backup-stage',default='/home/art/test/native-overlay-r89-native-gate');p.add_argument('--expected-active',default='/home/art/releases/api29-r95-native-gate');a=p.parse_args();assert re.fullmatch('/home/art/test/native-overlay-[a-z0-9-]+',a.backup_stage);assert re.fullmatch('/home/art/releases/api29-[a-z0-9-]+',a.expected_active)
ssh=['ssh','-o','ConnectTimeout=8','root@bonito']
if os.environ.get('SSHPASS'):ssh=['sshpass','-e']+ssh
body='CONFIG='+repr(dict(backup_stage=a.backup_stage,expected_active=a.expected_active))+'\n'+r'''
from pathlib import Path
import os,json,pwd,subprocess,stat,hashlib
assert Path('/home/art/test/.device-lock/owner').is_file(),'Acquire the device lock before restoring'
root=Path('/home/art/api29-root');assert root.is_symlink() and str(root.resolve())==CONFIG['expected_active']
assert Path('/sys/class/backlight/panel0-backlight/actual_brightness').read_text().strip()=='0'
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:exe=os.readlink(proc/'exe')
 except OSError:continue
 assert not(exe.startswith('/home/art/releases/')and exe.endswith('/libexec/saildroid-host')),'Close native hosts/manager before restoring'
backup=json.loads((Path(CONFIG['backup_stage'])/'activation-backup.json').read_text());assert backup['/home/art/api29-root']['link']=='/home/art/releases/api29-r86-compat'
u=pwd.getpwnam('defaultuser');desktop=Path(u.pw_dir)/'.local/share/applications';allowed={Path('/home/art/api29-root'),Path('/home/art/bin/saildroid-open')}
for name,entry in backup.items():
 path=Path(name);assert path in allowed or(path.parent==desktop and path.name.startswith('org.saildroid.app.p')and path.suffix=='.desktop')
 if 'link'in entry:assert name in ['/home/art/api29-root','/home/art/bin/saildroid-open']
for name,entry in reversed(list(backup.items())):
 path=Path(name)
 if entry.get('absent'):
  if path.exists()or path.is_symlink():path.unlink()
  continue
 temporary=path.with_name('.'+path.name+'-native-restore');assert not temporary.exists()and not temporary.is_symlink()
 if 'link'in entry:temporary.symlink_to(entry['link'])
 else:temporary.write_text(entry['text']);temporary.chmod(entry['mode'])
 os.lchown(temporary,entry['uid'],entry['gid']);os.replace(temporary,path)
assert root.resolve()==Path('/home/art/releases/api29-r86-compat')
print('NATIVE_BASELINE=restored|root='+str(root.resolve())+'|brightness=0')
'''
r=subprocess.run(ssh+['python3','-'],input=body.encode(),capture_output=True,timeout=35);print(r.stdout.decode());print(r.stderr.decode());r.check_returncode()
