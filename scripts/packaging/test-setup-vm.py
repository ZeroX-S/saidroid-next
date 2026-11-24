#!/usr/bin/env python3
"""Isolated filesystem tests. Deliberately refuses to execute on Sailfish OS."""
from pathlib import Path
import argparse, base64, contextlib, fcntl, hashlib, importlib.util, json, os, platform, shutil, socket, stat, subprocess, tempfile, time

parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--legacy-bootstrap-root',type=Path);args=parser.parse_args()
assert platform.system()=='Linux' and os.geteuid()==0
assert 'sailfishos' not in Path('/etc/os-release').read_text().lower(), 'Fixture runner is forbidden on the phone'
assert not args.output.exists();args.output.mkdir(parents=True)
module_path=Path(__file__).with_name('saildroid-setup.py');spec=importlib.util.spec_from_file_location('setup',module_path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
results=[]
def record(name):results.append(dict(name=name,passed=True));print('SETUP_FIXTURE=PASS|'+name,flush=True)
def must_fail(name,fn,contains):
 try:fn()
 except (RuntimeError,OSError)as e:assert contains in str(e),(name,str(e));record(name)
 else:raise AssertionError('Unexpected success: '+name)
def owned(path,uid=0,mode=0o755):path.mkdir(parents=True,exist_ok=True);os.chmod(path,mode);os.chown(path,uid,uid)

def seal(root,legacy=False):
 files={};links={};dirs=[]
 for p in sorted(root.rglob('*')):
  rel=p.relative_to(root).as_posix()
  if rel in (m.MANIFEST,'install-manifest.json'):continue
  if p.is_symlink():links[rel]=os.readlink(p)
  elif p.is_dir():dirs.append(rel)
  else:files[rel]=dict(sha256=m.digest(p),size=p.stat().st_size,mode=stat.S_IMODE(p.stat().st_mode))
 data=dict(files=files,symlinks=links,directories=dirs)
 if not legacy:data.update(schema='saildroid-activation-manifest-v1',release_id=root.name)
 destination=root/('install-manifest.json'if legacy else m.MANIFEST);destination.write_text(json.dumps(data,indent=2)+'\n');destination.chmod(0o644)

class Fixture(m.Platform):
 fixture=True
 def __init__(self,prefix):
  self.prefix=prefix;self.busy_records=[];self.fail_refresh=False;self.refreshes=[];self.fail_package=False;self.fail_caps=False;self.real_legacy_caps=False
 def account(self):return dict(name='defaultuser',uid=65534,gid=65534,groups=[65534],home=str(self.path('/home/defaultuser')))
 def check_system(self):return {'ID':'fixture-only','VERSION_ID':'5.2.0'}
 def check_package(self,release,release_id):m.require(not self.fail_package,'Fixture dependency failure');return dict(package='fixture-'+release_id,dependencies=1)
 def check_capabilities(self,release,legacy=False):
  if legacy and self.real_legacy_caps:return m.Platform.check_capabilities(self,release,legacy=True)
  m.require(not self.fail_caps,'Fixture capability failure')
 def busy(self):return self.busy_records
 def prepare_binder(self,account,release):
  folder=self.path('/home/art/runtime/binder')
  if not folder.exists():owned(folder,account['uid'],0o700)
 def refresh(self,account,release,helper,count):
  self.refreshes.append(str(release));updates={}
  for directory in self.path('/home/art/apps').iterdir():
   p=directory/'record.json'
   if not p.is_file():continue
   data=m.document(p);package=data['package'];relative='.local/share/applications/'+m.desktop_id(package)+'.desktop'
   text='[Desktop Entry]\nExec='+str(release)+'/libexec/saildroid-app --package '+package+' --desktop-token '+package+'\n'
   updates[relative]=dict(data=base64.b64encode(text.encode()).decode(),mode=0o644)
  self.user_files(account,'restore',updates)
  if self.fail_refresh:raise RuntimeError('Fixture refresh failure after partial write')
  return 'fixture registry substitute'

@contextlib.contextmanager
def fixture():
 with tempfile.TemporaryDirectory(prefix='saidroid-setup-fixture-')as d:
  prefix=Path(d);prefix.chmod(0o755);host=Fixture(prefix);sockets=[]
  for path in ['/home','/var/lib','/opt/saildroid/releases','/run/user','/run/display']:
   owned(host.path(path))
  owned(host.path('/home/defaultuser'),65534)
  owned(host.path('/run/user/65534'),65534,0o700);owned(host.path('/run/user/65534/dbus'),65534,0o700)
  for path in ['/run/user/65534/dbus/user_bus_socket','/run/display/wayland-0']:
   sock=socket.socket(socket.AF_UNIX);sock.bind(str(host.path(path)));sockets.append(sock)
  try:yield host
  finally:
   for sock in sockets:sock.close()

def release(host,name,legacy=False,api=29):
 root=host.path((m.LEGACY_RELEASES if legacy else m.RELEASES)+'/'+name);owned(root)
 files={'runtime.json':json.dumps(dict(api=api,native_host=True)), 'libexec/saildroid-app':'fixture bootstrap', 'libexec/saildroid-host':'fixture host','bin/dalvikvm':'fixture cli','share/manager.apk':'fixture system apk','share/icons/saildroid.svg':'<svg/>',m.REGISTRY_JAR:'fixture registry jar'}
 for rel,data in files.items():
  p=root/rel;owned(p.parent);p.write_text(data);p.chmod(0o755 if rel.startswith(('bin/','libexec/')) else 0o644)
 seal(root,legacy);return root

def action(host,method,*values):
 setup=m.Setup(host)
 try:return getattr(setup,method)(*values)
 finally:setup.close()

def application(host,package='com.example.fixture'):
 root=host.path('/home/art/apps/'+package);owned(root,65534,0o700);owned(root/'data',65534,0o700);(root/'data/keep').write_text('user data untouched\n');os.chown(root/'data/keep',65534,65534)
 data=dict(package=package,label='Fixture',launchActivity='.Main',icon=str(root/'icon.png'))
 (root/'record.json').write_text(json.dumps(data));os.chown(root/'record.json',65534,65534)
 return root

q=subprocess.run(['python3',str(module_path),'status'],capture_output=True,text=True);assert q.returncode==1 and 'Sailfish OS 5.2 and 5.3' in q.stderr;record('production-cli-refuses-build-vm')
with fixture()as host:
 root=release(host,'api28-a',api=28)
 assert action(host,'status')['status']=='unconfigured'
 action(host,'change','api28-a');assert os.readlink(host.path('/home/art/api29-root'))==str(root)
 status=action(host,'status');assert status['active']['api']==28 and status['active']['available'] and status['status']=='ready'
 action(host,'rollback');assert not host.path('/home/art/api29-root').is_symlink()
 record('api28-activate-and-rollback')
with fixture()as host:
 old=release(host,'api29-removed');new=release(host,'api28-new',api=28)
 action(host,'change','api29-removed');shutil.rmtree(old)
 status=action(host,'status');assert status['status']=='missing-runtime' and not status['active']['available']
 action(host,'change','api28-new');status=action(host,'status')
 assert status['active']['api']==28 and status['previous']is None and not status['previous_available']
 action(host,'rollback');assert action(host,'status')['status']=='unconfigured'
 record('removed-runtime-link-replaced-without-invalid-rollback-target')
with fixture()as host:
 old=release(host,'api29-removed');new=release(host,'api28-new',api=28)
 action(host,'change','api29-removed');action(host,'change','api28-new');shutil.rmtree(old)
 status=action(host,'status');assert status['active']['api']==28 and status['previous']['path']==str(old) and not status['previous_available']
 host.path('/home/art/api29-root').unlink();status=action(host,'status')
 assert status['status']=='unconfigured' and status['previous']is None
 action(host,'change','api28-new');assert action(host,'status')['previous']is None
 record('uninstalled-history-is-separated-from-current-runtime')
with fixture()as host:
 old=release(host,'api29-old');new=release(host,'api28-new',api=28)
 action(host,'change','api29-old');action(host,'change','api28-new')
 (new/'runtime.json').write_text(json.dumps(dict(api=28,native_host=True,updated=True)));seal(new)
 action(host,'change','api28-new');history=m.document(host.path(m.STATE+'/history.json'))
 assert len(history)==2 and history[-1]['after']['manifest_sha256']==m.digest(new/m.MANIFEST)
 action(host,'rollback');assert os.readlink(host.path('/home/art/api29-root'))==str(old)
 record('same-directory-rpm-update-refreshes-active-manifest-without-history-growth')
runtime=dict(rpm_activation=dict(schema='saildroid-rpm-activation-v1',mode='posttrans',release_id='api28-a'))
scripts=m.rpm_install_scripts('api28-a')
text=''.join(name+' scriptlet (using /bin/sh):\n'+body+'\n'for name,body in scripts.items())
m.check_rpm_scripts(runtime,'api28-a',text);m.check_rpm_scripts({},'api28-a','')
must_fail('unexpected-install-scriptlet-refused',lambda:m.check_rpm_scripts(runtime,'api28-a',text+'unexpected\n'),'scriptlets differ')
record('sealed-installation-policy-and-inert-packages-validated')
with fixture()as host:
 root=release(host,'api28-a',api=28)
 preflight=scripts['preinstall'].replace(m.RELEASES+'/api28-a',str(root))
 assert subprocess.run(['/bin/sh','-c',preflight],capture_output=True,text=True).returncode==0
 executable=root/'libexec/saildroid-host';shutil.copyfile('/bin/sleep',executable);executable.chmod(0o755)
 child=subprocess.Popen([str(executable),'60'])
 try:
  for attempt in range(40):
   if Path('/proc/'+str(child.pid)+'/exe').resolve()==executable:break
   time.sleep(.05)
  check=subprocess.run(['/bin/sh','-c',preflight],capture_output=True,text=True)
  assert check.returncode!=0 and 'Close SailDroid' in check.stderr and str(child.pid) in check.stderr
 finally:child.terminate();child.wait(timeout=10)
 record('rpm-preinstall-blocks-overwriting-a-running-runtime')
with fixture()as host:
 a=release(host,'api29-a');previous=os.umask(0o077)
 try:action(host,'change','api29-a')
 finally:os.umask(previous)
 for path,owner,mode in (('/home/art',0,0o755),('/home/art/bin',0,0o755),(m.STATE,0,0o700),('/home/art/data',65534,0o700)):
  info=host.path(path).stat();assert info.st_uid==owner and stat.S_IMODE(info.st_mode)==mode
 record('restrictive-umask-storage-modes')
with fixture()as host:
 a=release(host,'api29-a');b=release(host,'api29-b');c=release(host,'api29-c')
 assert action(host,'status')['active_link']is None
 action(host,'change','api29-a');assert os.readlink(host.path('/home/art/api29-root'))==str(a)
 manager=Path(host.account()['home'])/'.local/share/applications'/ (m.MANAGER_ID+'.desktop')
 assert manager.stat().st_uid==65534 and 'api29-root/libexec/saildroid-app --manager' in manager.read_text();record('fresh-activate-user-owned-manager-entry')
 app=application(host);record_before=(app/'record.json').read_bytes();data_before=(app/'data/keep').read_bytes()
 action(host,'change','api29-b');assert (app/'record.json').read_bytes()==record_before and (app/'data/keep').read_bytes()==data_before;record('upgrade-preserves-app-record-and-data')
 current=os.readlink(host.path('/home/art/api29-root'));before=manager.read_bytes()
 host.busy_records=[dict(pid=778,executable='/opt/saildroid/releases/api29-a/libexec/saildroid-host')]
 must_fail('busy-host-refused',lambda:action(host,'change','api29-c'),'Close SailDroid-owned');host.busy_records=[]
 assert os.readlink(host.path('/home/art/api29-root'))==current and manager.read_bytes()==before
 (c/'libexec/saildroid-host').write_text('tampered');must_fail('hash-mismatch-refused',lambda:action(host,'change','api29-c'),'Payload hash mismatch');(c/'libexec/saildroid-host').write_text('fixture host')
 (c/'libexec/saildroid-host').chmod(0o777);must_fail('writable-payload-refused',lambda:action(host,'change','api29-c'),'immutable');(c/'libexec/saildroid-host').chmod(0o755)
 (c/'unexpected').write_text('extra');must_fail('unexpected-payload-refused',lambda:action(host,'change','api29-c'),'unexpected payload');(c/'unexpected').unlink()
 (c/'libexec/escape').symlink_to('/etc/passwd');must_fail('extra-symlink-refused',lambda:action(host,'change','api29-c'),'unexpected payload');(c/'libexec/escape').unlink()
 host.fail_package=True;must_fail('dependency-failure-refused',lambda:action(host,'change','api29-c'),'dependency');host.fail_package=False
 host.fail_caps=True;must_fail('wrong-capability-refused',lambda:action(host,'change','api29-c'),'capability');host.fail_caps=False
 host.fail_refresh=True;must_fail('partial-launcher-refresh-rolls-back',lambda:action(host,'change','api29-c'),'refresh failure');host.fail_refresh=False
 assert os.readlink(host.path('/home/art/api29-root'))==current and manager.read_bytes()==before
 assert not host.path(m.STATE+'/pending.json').exists()
 app_desktop=Path(host.account()['home'])/'.local/share/applications'/(m.desktop_id('com.example.fixture')+'.desktop');assert str(b) in app_desktop.read_text()
 assert len(m.document(host.path(m.STATE+'/history.json')))==2
 action(host,'rollback');assert os.readlink(host.path('/home/art/api29-root'))==str(a) and str(a) in app_desktop.read_text();record('rollback-refreshes-existing-and-new-apps')
 action(host,'rollback');assert not host.path('/home/art/api29-root').is_symlink() and not manager.exists() and not app_desktop.exists();assert (app/'data/keep').read_bytes()==data_before;record('fresh-rollback-unconfigures-without-data-loss')
 action(host,'change','api29-a');action(host,'change','api29-a');assert len(m.document(host.path(m.STATE+'/history.json')))==1;record('idempotent-activate-repairs-without-history-growth')
 lock=host.path('/run/user/65534/saildroid/host-manager.lock');fd=os.open(lock,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try:must_fail('native-manager-startup-lock-refused',lambda:action(host,'change','api29-b'),'holds the lock')
 finally:os.close(fd)
 # Emulate a power loss after history fsync but before pending journal removal.
 action(host,'change','api29-b');history=m.document(host.path(m.STATE+'/history.json'));saved=history[-1];m.atomic_json(host.path(m.STATE+'/pending.json'),dict(saved,history_before=history[:-1]))
 action(host,'recover');assert os.readlink(host.path('/home/art/api29-root'))==str(a) and len(m.document(host.path(m.STATE+'/history.json')))==1;record('interrupted-activation-recovers-history-and-launchers')
 action(host,'change','api29-b');history=m.document(host.path(m.STATE+'/history.json'));saved=history[-1]
 snapshot=host.user_files(host.account(),'snapshot',m.Setup(host).launcher_paths(m.Setup(host).installed()))
 m.atomic_json(host.path(m.STATE+'/pending.json'),dict(saved,rollback=True,rollback_launchers=snapshot,history_before=history))
 setup=m.Setup(host);setup.switch(saved['before_link']);m.atomic_json(host.path(m.STATE+'/history.json'),history[:-1])
 action(host,'recover');assert os.readlink(host.path('/home/art/api29-root'))==str(b) and len(m.document(host.path(m.STATE+'/history.json')))==2;record('interrupted-rollback-restores-pre-operation-state')
 assert (app/'record.json').read_bytes()==record_before and (app/'data/keep').read_bytes()==data_before
with fixture()as host:
 owned(host.path('/home/art'));owned(host.path('/home/art/releases'));legacy=release(host,'api29-old',True);new=release(host,'api29-new')
 host.path('/home/art/api29-root').symlink_to('releases/api29-old')
 action(host,'change','api29-new');action(host,'rollback');assert os.readlink(host.path('/home/art/api29-root'))=='releases/api29-old';record('legacy-relative-symlink-restored-verbatim')
with fixture()as host:
 release(host,'api29-a');outside=host.path('/outside');owned(outside,65534);(Path(host.account()['home'])/'.local').symlink_to(outside)
 must_fail('user-directory-symlink-refused',lambda:action(host,'change','api29-a'),'Unexpected symlink');assert not list(outside.iterdir())
with fixture()as host:
 release(host,'api29-a');owned(host.path('/home/art'));host.path('/home/art/api29-root').write_text('do not overwrite')
 must_fail('non-symlink-active-root-refused',lambda:action(host,'change','api29-a'),'must be a symlink');assert host.path('/home/art/api29-root').read_text()=='do not overwrite'
with fixture()as host:
 release(host,'api29-a');owned(host.path('/home/art'),mode=0o777)
 must_fail('writable-root-refused',lambda:action(host,'change','api29-a'),'immutable')
# A real character node in the isolated VM fixture models already-provisioned
# kernel binder. Never open it; prove activation/rollback do not alter its inode,
# rdev, ownership, mode, or provisioning contents.
def kernel_binder(host):
 owned(host.path('/home/art'));owned(host.path('/home/art/runtime'))
 folder=host.path('/home/art/runtime/binder');owned(folder)
 provision=folder/'provision.json';provision.write_text('{"fixture":"preserve existing kernel binder"}\n');provision.chmod(0o644)
 node=folder/'binder';os.mknod(node,stat.S_IFCHR|0o600,os.makedev(1,3));os.chown(node,65534,65534)
 return folder,node,provision

def binder_snapshot(paths):
 result=[]
 for p in paths:
  st=p.lstat();result.append((str(p),st.st_ino,st.st_uid,st.st_gid,st.st_mode,st.st_rdev,st.st_ctime_ns,p.read_bytes()if stat.S_ISREG(st.st_mode)else None))
 return result
with fixture()as host:
 a=release(host,'api29-a');attempts=[]
 def retry_binder(account,release):
  attempts.append(str(release))
  if len(attempts)==1:
   owned(host.path('/home/art/runtime'),0,0o755)
   owned(host.path('/home/art/runtime/binder'),0,0o755)
   raise RuntimeError('Fixture interrupted Binder provisioning')
  kernel_binder(host)
 host.prepare_binder=retry_binder
 must_fail('partial-binder-provisioning-refused',lambda:action(host,'change','api29-a'),'interrupted Binder')
 assert not host.path('/home/art/api29-root').is_symlink()
 assert not host.path(m.STATE+'/pending.json').exists()
 action(host,'change','api29-a')
 assert len(attempts)==2 and os.readlink(host.path('/home/art/api29-root'))==str(a)
 record('partial-binder-provisioning-retry-finishes-activation')

with fixture()as host:
 a=release(host,'api29-a');b=release(host,'api29-b');paths=kernel_binder(host);before=binder_snapshot(paths)
 action(host,'change','api29-a');action(host,'change','api29-b');action(host,'rollback')
 assert os.readlink(host.path('/home/art/api29-root'))==str(a)and binder_snapshot(paths)==before
 record('trusted-root-kernel-binder-preserved-across-activation-and-rollback')
for case,error in [('directory-mode','immutable'),('directory-group','kernel-binder directory'),('regular-device','kernel-binder device'),('device-owner','kernel-binder device'),('device-mode','kernel-binder device'),('linked-device','missing or linked'),('metadata-owner','provision metadata'),('metadata-mode','provision metadata'),('linked-metadata','missing or linked')]:
 with fixture()as host:
  release(host,'api29-a');folder,node,provision=kernel_binder(host)
  if case=='directory-mode':folder.chmod(0o777)
  elif case=='directory-group':os.chown(folder,0,65534)
  elif case=='regular-device':node.unlink();node.write_text('not a device');node.chmod(0o600);os.chown(node,65534,65534)
  elif case=='device-owner':os.chown(node,0,0)
  elif case=='device-mode':node.chmod(0o666)
  elif case=='linked-device':node.unlink();node.symlink_to('/dev/null')
  elif case=='metadata-owner':os.chown(provision,65534,65534)
  elif case=='metadata-mode':provision.chmod(0o666)
  elif case=='linked-metadata':provision.unlink();provision.symlink_to('/etc/os-release')
  before=binder_snapshot((folder,node,provision))
  must_fail('kernel-binder-'+case+'-refused',lambda:action(host,'change','api29-a'),error)
  assert not host.path('/home/art/api29-root').is_symlink()and binder_snapshot((folder,node,provision))==before
with fixture()as host:
 release(host,'api29-a');owned(host.path('/home/art'));owned(host.path('/home/art/apps'))
 must_fail('unrelated-root-owned-app-storage-still-refused',lambda:action(host,'change','api29-a'),'Existing storage ownership differs')
for declared in (None, 'cap_sys_resource=ep', 'cap_dac_override,cap_sys_resource=ep'):
 with fixture() as host:
  root = release(host, 'api28-cap-policy', api=28)
  runtime = m.document(root / 'runtime.json')
  if declared is not None:
   runtime['native_bootstrap'] = dict(schema='saildroid-native-bootstrap-v1', capabilities=declared)
   (root / 'runtime.json').write_text(json.dumps(runtime))
  capability = declared or 'cap_sys_resource=ep'
  subprocess.run(['setcap', capability, str(root / 'libexec/saildroid-app')], check=True)
  m.Platform.check_capabilities(host, root)
  record('native-bootstrap-policy-accepted-' + (declared or 'legacy-default'))
  subprocess.run(['setcap', 'cap_sys_resource=ep', str(root / 'libexec/saildroid-host')], check=True)
  must_fail('native-bootstrap-extra-path-refused-' + capability,
            lambda: m.Platform.check_capabilities(host, root), 'Only the native bootstrap')
  subprocess.run(['setcap', '-r', str(root / 'libexec/saildroid-host')], check=True)
  subprocess.run(['setcap', capability.replace('=ep', ',cap_net_bind_service=ep'),
                  str(root / 'libexec/saildroid-app')], check=True)
  must_fail('native-bootstrap-extra-capability-refused-' + capability,
            lambda: m.Platform.check_capabilities(host, root), 'Only the native bootstrap')
  subprocess.run(['setcap', '-r', str(root / 'libexec/saildroid-app')], check=True)
  must_fail('native-bootstrap-missing-capability-refused-' + capability,
            lambda: m.Platform.check_capabilities(host, root), 'Only the native bootstrap')
with fixture() as host:
 root = release(host, 'api28-cap-mismatch', api=28)
 runtime = m.document(root / 'runtime.json')
 runtime['native_bootstrap'] = dict(schema='saildroid-native-bootstrap-v1', capabilities='cap_dac_override,cap_sys_resource=ep')
 (root / 'runtime.json').write_text(json.dumps(runtime))
 subprocess.run(['setcap', 'cap_sys_resource=ep', str(root / 'libexec/saildroid-app')], check=True)
 must_fail('native-bootstrap-declared-capability-mismatch-refused',
           lambda: m.Platform.check_capabilities(host, root), 'Only the native bootstrap')
for policy in (
 {'schema': 'unknown', 'capabilities': 'cap_sys_resource=ep'},
 {'schema': 'saildroid-native-bootstrap-v1', 'capabilities': 'cap_dac_override=ep'},
 {'schema': 'saildroid-native-bootstrap-v1', 'capabilities': 'cap_sys_resource,cap_net_bind_service=ep'},
 {'schema': 'saildroid-native-bootstrap-v1', 'capabilities': 'cap_sys_resource=ep', 'path': 'libexec/saildroid-host'},
 {}, 'cap_sys_resource=ep',
):
 must_fail('unsupported-native-bootstrap-policy-refused-' + json.dumps(policy),
           lambda: m.native_bootstrap_capability({'native_bootstrap': policy}),
           'Unsupported native bootstrap capability policy')
if args.legacy_bootstrap_root:
 # Exercise actual getcap output from real, never-executed native bootstrap
 # copies. The VM's local temporary filesystem preserves security.capability.
 expected_hashes={'saildroid-app':'2ff709408f21d8f2b514e76ebb63a489652eba41c073341cb28db2f54630fe98','saildroid-launch':'a56df520408a7856f0ae63463c3a13ed4b212001c955332a3c0105be7f72bfbb'}
 def native_pair(host,name,legacy):
  root=release(host,name,legacy)
  for filename,expected_hash in expected_hashes.items():
   source=args.legacy_bootstrap_root/'libexec'/filename;assert m.digest(source)==expected_hash
   dest=root/'libexec'/filename;shutil.copyfile(source,dest);dest.chmod(0o755)
   subprocess.run(['setcap','cap_sys_resource=ep',str(dest)],check=True)
  seal(root,legacy);return root
 with fixture()as host:
  owned(host.path('/home/art'));owned(host.path('/home/art/releases'));old=native_pair(host,'api29-old',True);new=release(host,'api29-new');host.real_legacy_caps=True
  host.path('/home/art/api29-root').symlink_to('releases/api29-old')
  before={n:(m.digest(old/'libexec'/n),(old/'libexec'/n).stat().st_ino,os.getxattr(old/'libexec'/n,'security.capability'))for n in expected_hashes}
  action(host,'change','api29-new');action(host,'rollback')
  assert os.readlink(host.path('/home/art/api29-root'))=='releases/api29-old'
  assert before=={n:(m.digest(old/'libexec'/n),(old/'libexec'/n).stat().st_ino,os.getxattr(old/'libexec'/n,'security.capability'))for n in expected_hashes}
  record('reviewed-legacy-native-pair-preserved-across-activate-rollback')
 for case in ['changed-launcher-bytes','changed-bootstrap-bytes','extra-path','extra-capability','new-root-known-pair']:
  with fixture()as host:
   owned(host.path('/home/art'));owned(host.path('/home/art/releases'));legacy=case!='new-root-known-pair';root=native_pair(host,'api29-cap-test',legacy)
   if case.startswith('changed-'):
    node=root/'libexec'/('saildroid-launch'if case=='changed-launcher-bytes'else'saildroid-app');node.write_bytes(node.read_bytes()+b'altered');node.chmod(0o755);subprocess.run(['setcap','cap_sys_resource=ep',str(node)],check=True);seal(root,legacy)
   elif case=='extra-path':subprocess.run(['setcap','cap_sys_resource=ep',str(root/'libexec/saildroid-host')],check=True)
   elif case=='extra-capability':subprocess.run(['setcap','cap_sys_resource,cap_net_bind_service=ep',str(root/'libexec/saildroid-launch')],check=True)
   error='Unrecognized legacy capability bootstrap'if case.startswith('changed-')else'Only the native bootstrap'
   must_fail('legacy-capability-'+case+'-refused',lambda:m.Platform.check_capabilities(host,root,legacy=legacy),error)
 with fixture()as host:
  root=native_pair(host,'api29-new',False);subprocess.run(['setcap','-r',str(root/'libexec/saildroid-launch')],check=True)
  m.Platform.check_capabilities(host,root,legacy=False);record('new-release-still-requires-single-native-bootstrap-capability')
result=dict(passed=True,scope='VM-only isolated temporary filesystem. Package/registry and baseline capability calls use explicit platform doubles; optional legacy-capability cases use real getcap/setcap and never execute the copied ELFs. User desktop operations run as UID65534 through the real unprivileged subprocess.',tests=results,implementation_sha256=m.digest(module_path),fixture_sha256=m.digest(Path(__file__)))
(args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
