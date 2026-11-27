"""Device half of deploy-native-overlay.py, executed as one bounded transaction."""
from pathlib import Path
import hashlib,json,os,pwd,shutil,stat,subprocess,tarfile
assert 'ID=sailfishos' in Path('/etc/sailfish-release').read_text()
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();lip=subprocess.check_output(['pidof','lipstick'],text=True).strip();stage=Path(CONFIG['stage']);archive=stage/'native-overlay.tar.gz';assert hashlib.sha256(archive.read_bytes()).hexdigest()==CONFIG['sha256']
lock=Path('/home/art/test/.device-lock/owner');assert lock.is_file(),'Acquire the device lock before deploy'
assert Path('/sys/class/backlight/panel0-backlight/actual_brightness').read_text().strip()=='0'
unpacked=stage/'unpacked';unpacked.mkdir()
with tarfile.open(archive)as source:
 for item in source:
  name=Path(item.name);assert not name.is_absolute() and '..'not in name.parts and name.parts[0]in ['overlay.json','payload'];target=unpacked/name
  if item.isdir():target.mkdir(parents=True,exist_ok=True);target.chmod(0o755)
  elif item.isfile():
   target.parent.mkdir(parents=True,exist_ok=True)
   with source.extractfile(item)as incoming,target.open('xb')as out:shutil.copyfileobj(incoming,out)
   target.chmod(item.mode&0o777)
  else:raise RuntimeError('Overlay payload must contain only files/directories')
meta=json.loads((unpacked/'overlay.json').read_text());assert meta['schema']=='saildroid-native-overlay-v1';pre=meta['predecessor'];base=Path(pre['root']);assert base.is_dir() and not base.is_symlink() and base.stat().st_uid==0
assert hashlib.sha256((base/'install-manifest.json').read_bytes()).hexdigest()==meta['predecessor_manifest_sha256']
old_manifest=json.loads((base/'install-manifest.json').read_text())
def verify(root,manifest):
 for name,entry in manifest['files'].items():
  path=root/name;assert path.is_file() and not path.is_symlink(),name;assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256'],name;assert stat.S_IMODE(path.stat().st_mode)==entry['mode'],name
 for name,target in manifest['symlinks'].items():assert (root/name).is_symlink() and os.readlink(root/name)==target,name
verify(base,old_manifest)
for name,entry in meta['changes'].items():
 relative=Path(name);assert not relative.is_absolute() and '..'not in relative.parts;path=unpacked/'payload'/relative;assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
release=Path('/home/art/releases')/('api29-'+CONFIG['run'])
if CONFIG.get('reuse_existing'):
 assert CONFIG['activate'] and release.is_dir()and not release.is_symlink()and release.stat().st_uid==0
 assert json.loads((release/'install-manifest.json').read_text())==meta['install_manifest']
else:
 assert not release.exists();shutil.copytree(base,release,symlinks=True,copy_function=os.link)
 for name,entry in meta['changes'].items():
  path=release/name
  if path.exists()or path.is_symlink():path.unlink()
  path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(unpacked/'payload'/name,path);path.chmod(entry['mode'])
 for name,target in meta['symlinks'].items():
  path=release/name
  if path.exists()or path.is_symlink():path.unlink()
  path.symlink_to(target)
 path=release/'install-manifest.json';path.unlink();path.write_text(json.dumps(meta['install_manifest'],indent=2)+'\n');path.chmod(0o644)
 subprocess.run(['setcap','cap_sys_resource=ep',str(release/'libexec/saildroid-app')],check=True)
verify(release,meta['install_manifest'])
u=pwd.getpwnam('defaultuser');user=dict(user=u.pw_uid,group=u.pw_gid,extra_groups=os.getgrouplist(u.pw_name,u.pw_gid));env=dict(os.environ,HOME=u.pw_dir,USER=u.pw_name,LOGNAME=u.pw_name,XDG_RUNTIME_DIR='/run/user/100000',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/100000/dbus/user_bus_socket')
limit=subprocess.run([str(release/'libexec/saildroid-app'),'--print-limits'],capture_output=True,text=True,timeout=6,env=env,**user);assert limit.returncode==0,limit.stderr;scope=json.loads(limit.stdout);assert scope['uid']==u.pw_uid and scope['nice_limit']==meta['product_manifest'].get('native_nice_limit',28) and scope['no_new_privs']==1 and scope['effective_capabilities']==0
backup={}
def replace(path,*,data=None,link=None,owner=0):
 path=Path(path);backup[str(path)]=dict(link=os.readlink(path))if path.is_symlink() else dict(text=path.read_text())if path.exists()else dict(absent=True)
 if path.exists()or path.is_symlink():
  info=path.lstat();backup[str(path)].update(mode=stat.S_IMODE(info.st_mode),uid=info.st_uid,gid=info.st_gid)
 (stage/'activation-backup.json').write_text(json.dumps(backup,indent=2)+'\n')
 temp=path.with_name('.'+path.name+'-'+CONFIG['run']);assert not temp.exists() and not temp.is_symlink()
 if link is not None:temp.symlink_to(link)
 else:temp.write_text(data);temp.chmod(0o644)
 os.lchown(temp,owner,u.pw_gid if owner==u.pw_uid else 0);os.replace(temp,path)
if CONFIG['activate']:
 # The global launch indirection changes only with all old host generations
 # quiescent. This includes the native manager, so versions cannot mix.
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:
   executable=os.readlink(proc/'exe');command=(proc/'cmdline').read_bytes()
  except (OSError,PermissionError):continue
  owned=executable=='/home/art/bin/dalvikvm' or (executable.startswith('/home/art/releases/') and executable.endswith('/libexec/saildroid-host')) or b'api29-root/libexec/saildroid-open'in command or command.startswith(b'saildroid-supervisor:')
  assert not owned,'Close owned runtime before activation: '+proc.name
 try:
  root=Path('/home/art/api29-root');assert root.is_symlink() and str(root.resolve())==(CONFIG.get('expected_active') or str(base))
  replace(root,link=str(release));replace('/home/art/bin/saildroid-open',link='../api29-root/libexec/saildroid-app')
  desktop_dir=Path(u.pw_dir)/'.local/share/applications'
  manager='org.saildroid.manager';ident='org.saildroid.app.p'+hashlib.sha256(manager.encode()).hexdigest()[:20]
  desktop=desktop_dir/(ident+'.desktop');text=desktop.read_text();lines=text.splitlines();lines=[('Exec='+str(release/'libexec/saildroid-app')+' --manager --desktop-token '+manager+' %u')if s.startswith('Exec=')else s for s in lines];replace(desktop,data='\n'.join(lines)+'\n',owner=u.pw_uid)
  expected_desktops={desktop:'Exec='+str(release/'libexec/saildroid-app')+' --manager --desktop-token '+manager+' %u'}
  for app in Path('/home/art/apps').iterdir():
   if not (app/'record.json').is_file():continue
   installed=json.loads((app/'record.json').read_text());name=installed['package'];ident='org.saildroid.app.p'+hashlib.sha256(name.encode()).hexdigest()[:20];desktop=desktop_dir/(ident+'.desktop')
   if not desktop.exists():continue
   expected_desktops[desktop]='Exec='+str(release/'libexec/saildroid-app')+' --package '+name+' --desktop-token '+name
   lines=desktop.read_text().splitlines();lines=[expected_desktops[desktop]if s.startswith('Exec=')else s for s in lines];replace(desktop,data='\n'.join(lines)+'\n',owner=u.pw_uid)
  assert root.resolve()==release and Path('/home/art/bin/saildroid-open').resolve()==release/'libexec/saildroid-app'
  for path,entry in expected_desktops.items():assert [line for line in path.read_text().splitlines()if line.startswith('Exec=')]==[entry]
 except BaseException:
  for name,entry in reversed(list(backup.items())):
   path=Path(name);temp=path.with_name('.'+path.name+'-restore-'+CONFIG['run'])
   if entry.get('absent'):
    if path.exists()or path.is_symlink():path.unlink()
    continue
   if 'link'in entry:temp.symlink_to(entry['link'])
   else:temp.write_text(entry['text']);temp.chmod(entry.get('mode',0o644))
   os.lchown(temp,entry.get('uid',0),entry.get('gid',0));os.replace(temp,path)
  raise
(stage/'activation-backup.json').write_text(json.dumps(backup,indent=2)+'\n')
assert boot==Path('/proc/sys/kernel/random/boot_id').read_text().strip() and lip==subprocess.check_output(['pidof','lipstick'],text=True).strip()
assert Path('/sys/class/backlight/panel0-backlight/actual_brightness').read_text().strip()=='0'
print(json.dumps(dict(result='NATIVE_OVERLAY=activated'if CONFIG['activate'] else'NATIVE_OVERLAY=staged',release=str(release),reused_existing=bool(CONFIG.get('reuse_existing')),backup_stage=str(stage),files=len(meta['install_manifest']['files']),payload_sha256=CONFIG['sha256'],boot=boot,lipstick=lip,brightness=0,scope=scope)))
