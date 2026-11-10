#!/usr/bin/env python3
"""Install one verified API29 component under /home/art and the user's launcher."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);p.add_argument('run');a=p.parse_args();assert re.fullmatch('[a-z0-9-]+',a.run)
archive=a.bundle/'component.tar.gz';manifest=json.loads((a.bundle/'manifest.json').read_text());assert manifest['api']==29
sha=hashlib.sha256(archive.read_bytes()).hexdigest();stage='/home/art/test/api29-deploy-'+a.run
ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','root@bonito']
subprocess.run(ssh+['test ! -e '+stage+' && install -d -m0700 '+stage],check=True,timeout=8)
subprocess.run(['scp','-O','-o','BatchMode=yes',str(archive),'root@bonito:'+stage+'/component.tar.gz'],check=True,timeout=180)
identity=subprocess.check_output(ssh+['/bin/cat /etc/sailfish-release'],text=True,timeout=8);assert 'ID=sailfishos' in identity
expected_boot=subprocess.check_output(ssh+['/bin/cat /proc/sys/kernel/random/boot_id'],text=True,timeout=8).strip();assert re.fullmatch('[0-9a-f-]{36}',expected_boot)
body=('CONFIG='+repr(dict(stage=stage,sha256=sha,run=a.run,bytes=manifest['bytes'],expected_boot=expected_boot))+'\n'+r'''
from pathlib import Path
import os,stat,tarfile,json,hashlib,subprocess,pwd,shutil
assert 'ID=sailfishos'in Path('/etc/sailfish-release').read_text()
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==CONFIG['expected_boot']
lipstick=subprocess.check_output(['pidof','lipstick'],text=True).strip()
base=Path('/home/art');assert base.is_dir()and not base.is_symlink()and base.stat().st_uid==0
account=pwd.getpwnam('defaultuser');stage=Path(CONFIG['stage']);archive=stage/'component.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==CONFIG['sha256'];assert shutil.disk_usage(base).free>CONFIG['bytes']*2+1024*1024*1024
for process in Path('/proc').iterdir():
 if not process.name.isdigit():continue
 try:
  command=(process/'cmdline').read_bytes()
  executable=os.readlink(process/'exe')
  assert not(executable=='/home/art/bin/dalvikvm' or(executable.startswith('/home/art/apps/')and executable.endswith('/dalvikvm'))or(executable.startswith('/home/art/releases/')and executable.endswith('/libexec/saildroid-host'))or b'api29-root/lib/runtime.jar'in command or b'api29-root/libexec/saildroid-open'in command or command.startswith((b'org.saildroid.manager\0',b'saildroid-supervisor:'))),'Close all owned SailDroid applications before component update'
 except (OSError,PermissionError):pass
unpacked=stage/'unpacked';unpacked.mkdir()
with tarfile.open(archive,'r:gz')as source:
 for member in source:
  name=Path(member.name);assert not name.is_absolute()and '..'not in name.parts and name.parts[0]in ['root','manifest.json']
  target=unpacked/name
  if member.isdir():target.mkdir(parents=True,exist_ok=True);target.chmod(0o755)
  elif member.isfile():
   target.parent.mkdir(parents=True,exist_ok=True)
   with source.extractfile(member)as input,target.open('xb')as output:shutil.copyfileobj(input,output,1024*1024)
   target.chmod(member.mode&0o777)
  elif member.issym():
   assert not Path(member.linkname).is_absolute();resolved=(target.parent/member.linkname).resolve();assert unpacked.resolve()in resolved.parents
   target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(member.linkname)
  else:raise AssertionError('Unsupported archive member')
record=json.loads((unpacked/'manifest.json').read_text());root=unpacked/'root';assert record['api']==29
for name,item in record['files'].items():
 file=root/name;assert file.is_file()and not file.is_symlink();assert hashlib.sha256(file.read_bytes()).hexdigest()==item['sha256'];assert stat.S_IMODE(file.stat().st_mode)==item['mode']
for name,target in record['symlinks'].items():assert (root/name).is_symlink()and os.readlink(root/name)==target
releases=base/'releases';assert not releases.is_symlink();releases.mkdir(mode=0o755,exist_ok=True)
release=releases/('api29-'+CONFIG['run']);assert not release.exists();root.rename(release)
(release/'install-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
runtime=json.loads((release/'runtime.json').read_text())
native_host=runtime.get('native_host',False)
cap_entry=release/('libexec/saildroid-app'if native_host else'libexec/saildroid-launch')
policy=runtime.get('native_bootstrap')
capability='cap_sys_resource=ep'
if policy is not None:
 assert native_host and policy in [dict(schema='saildroid-native-bootstrap-v1',capabilities=value)for value in ['cap_sys_resource=ep','cap_dac_override,cap_sys_resource=ep']]
 capability=policy['capabilities']
subprocess.run(['setcap',capability,str(cap_entry)],check=True)
cap=subprocess.check_output(['getcap',str(cap_entry)],text=True).strip();assert cap==str(cap_entry)+' '+capability
# Ordinary user storage and its actual session runtime directory.
for directory in [base/'apps',base/'data/shared',base/'data/logs',base/'data/manager']:
 assert not directory.is_symlink();directory.mkdir(mode=0o700,parents=True,exist_ok=True);os.chown(directory,account.pw_uid,account.pw_gid)
old=base/'api29-root';assert not old.exists()or old.is_symlink()
before=dict(boot=boot,lipstick=lipstick,old_root=os.readlink(old)if old.is_symlink()else None,release=str(release))
link=base/('.api29-root-'+CONFIG['run']);link.symlink_to(str(release));os.replace(link,old)
wrapper=base/'bin/saildroid-open'
if wrapper.exists():assert (wrapper.is_symlink()and os.readlink(wrapper)=='../api29-root/libexec/saildroid-app')or(wrapper.is_file()and 'api29-root/libexec/saildroid-open'in wrapper.read_text())
temporary=wrapper.with_name('.saildroid-open-'+CONFIG['run'])
if native_host:temporary.symlink_to('../api29-root/libexec/saildroid-app')
else:temporary.write_text('#!/bin/sh\nexec /usr/bin/python3 /home/art/api29-root/libexec/saildroid-open "$@"\n');temporary.chmod(0o755)
os.replace(temporary,wrapper)
desktop_dir=Path(account.pw_dir)/'.local/share/applications';desktop_dir.mkdir(parents=True,exist_ok=True);os.chown(desktop_dir,account.pw_uid,account.pw_gid)
service_name='org.saildroid.app.p'+hashlib.sha256(b'org.saildroid.manager').hexdigest()[:20]
desktop=desktop_dir/(service_name+'.desktop');legacy_desktop=desktop_dir/'saildroid-org.saildroid.manager.desktop';before['desktop_previous']=desktop.read_text()if desktop.exists()else legacy_desktop.read_text()if legacy_desktop.exists()else None
old_activation=Path(account.pw_dir)/'.local/share/dbus-1/services'/(service_name+'.service')
if old_activation.exists():
 assert 'Name='+service_name in old_activation.read_text()and 'Exec=/home/art/'in old_activation.read_text();old_activation.unlink()
manager_launcher=base/'bin/org.saildroid.manager';manager_temporary=manager_launcher.with_name('.org.saildroid.manager-'+CONFIG['run']);manager_temporary.write_text('#!/bin/sh\nexec /home/art/bin/saildroid-open --manager "$@"\n');manager_temporary.chmod(0o755);os.replace(manager_temporary,manager_launcher)
manager_exec=str(release/'libexec/saildroid-app')+' --manager'if native_host else'/home/art/bin/org.saildroid.manager'
text='[Desktop Entry]\nType=Application\nName=SailDroid 安装器\nExec='+manager_exec+' --desktop-token org.saildroid.manager %u\nIcon=/home/art/api29-root/share/icons/saildroid.svg\nMimeType=application/vnd.android.package-archive;\nStartupNotify=true\nX-Sailfish-ApplicationType=generic\n\n[X-Sailjail]\nSandboxing=Disabled\nOrganizationName=org.saildroid.app\nApplicationName='+service_name.rsplit('.',1)[1]+'\n'
temporary=desktop.with_suffix('.desktop.new');temporary.write_text(text);os.chown(temporary,account.pw_uid,account.pw_gid);temporary.chmod(0o644);os.replace(temporary,desktop)
if legacy_desktop.exists():legacy_desktop.unlink()
# Confirm privilege scope through the real phone user's exec path.
limits=subprocess.run([str(cap_entry),'--print-limits'],user=account.pw_uid,group=account.pw_gid,extra_groups=os.getgrouplist(account.pw_name,account.pw_gid),capture_output=True,text=True,timeout=5);assert limits.returncode==0,limits.stderr
scope=json.loads(limits.stdout);assert scope['uid']==account.pw_uid and scope['nice_limit']==json.loads((release/'runtime.json').read_text()).get('native_nice_limit',28) and scope['effective_capabilities']==0 and scope['no_new_privs']==1
assert boot==Path('/proc/sys/kernel/random/boot_id').read_text().strip()and lipstick==subprocess.check_output(['pidof','lipstick'],text=True).strip()
before.update(scope=scope,archive_sha256=CONFIG['sha256'],desktop=str(desktop),capabilities=cap)
(stage/'installation.json').write_text(json.dumps(before,indent=2)+'\n');print(json.dumps(dict(result='API29_COMPONENT=installed',**before)))
''').encode()
r=subprocess.run(ssh+['python3 -'],input=body,capture_output=True,timeout=150)
(a.bundle/('deploy-'+a.run+'.stdout')).write_bytes(r.stdout);(a.bundle/('deploy-'+a.run+'.stderr')).write_bytes(r.stderr)
print(r.stdout.decode());print(r.stderr.decode());r.check_returncode()
