#!/usr/bin/env python3
"""Linux process tests: locking, fd isolation, independent apps and cleanup.

The child is a control-endpoint fixture, not an Android implementation. Real
APK/Wayland/Service verification is separate. VM root prepares trusted code;
all launchers and child fixtures run as the ordinary build user.
"""
from pathlib import Path
import argparse,json,os,pwd,socket,subprocess,sys,time

p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--user',default='builder');a=p.parse_args()
assert os.getuid()==0
a.output.mkdir(parents=True,exist_ok=False);a.output.chmod(0o755)
account=pwd.getpwnam(a.user);repo=Path(__file__).resolve().parents[3]
root=a.output/'root';apps=a.output/'apps';root.mkdir(mode=0o755);apps.mkdir(mode=0o755);os.chown(apps,account.pw_uid,account.pw_gid)
for name in ['lib','libexec','android-libs','empty-libs','share']:(root/name).mkdir(mode=0o755)
root.chmod(0o755)
(root/'runtime.json').write_text(json.dumps(dict(api=29,boot_jars=[])))
fixture=r'''#!/usr/bin/python3
from pathlib import Path
import os,socket,sys,time,json,subprocess
package=next(x.split('=',1)[1]for x in sys.argv if x.startswith('-Dsaidroid.package='))
# Opening and closing the lock inode in the runtime must not release the
# supervisor's POSIX lock, nor may the runtime inherit that lock descriptor.
inherited=[]
for fd in Path('/proc/self/fd').iterdir():
 try:
  if os.readlink(fd).endswith(package+'.lock'):inherited.append(fd.name)
 except OSError:pass
assert not inherited,inherited
with open('/run/user/'+str(os.getuid())+'/saildroid/'+package+'.lock','r'):pass
endpoint=os.environ['SAILDROID_CONTROL_SOCKET'];server=socket.socket(socket.AF_UNIX);server.bind(endpoint);server.listen(64)
print('FIXTURE=ready|pid='+str(os.getpid()),flush=True)
while True:
 client,_=server.accept();command=client.recv(64)
 if command==b'activate\n':client.sendall(b'requested\n');client.close()
 elif command==b'spawn\n':
  subprocess.Popen(['/usr/bin/python3',os.environ['SAILDROID_TEST_ENTRY'],'--package','org.example.saildroid.launchtwo']);client.sendall(b'spawned\n');client.close()
 elif command==b'spawnservice\n':
  subprocess.Popen(['/usr/bin/python3',os.environ['SAILDROID_TEST_ENTRY'],'--package',package,'--service',package+'.Worker','--process',package+':worker']);client.sendall(b'spawned\n');client.close()
 elif command==b'close\n':
  client.sendall(b'closing\n');client.close();server.close();Path(endpoint).unlink()
  if package.endswith('hung'):
   while True:time.sleep(1)
  break
 elif command==b'crash\n':os._exit(17)
 elif command==b'exit0\n':os._exit(0)
'''
helper=root/'libexec/saildroid-launch';helper.write_text(fixture);helper.chmod(0o755)
for path in root.rglob('*'):
    if path.is_dir():path.chmod(0o755)
    elif path!=helper:path.chmod(0o644)
bootstrap=a.output/'entry.py'
bootstrap.write_text('import importlib.util,sys\nfrom pathlib import Path\n'+'s=importlib.util.spec_from_file_location("launcher",'+repr(str(repo/'scripts/runtime/saildroid-open.py'))+')\nm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nm.ROOT=Path('+repr(str(root))+');m.APPS=Path('+repr(str(apps))+')\nsys.exit(m.main())\n');bootstrap.chmod(0o644)
for name in ['launchone','launchtwo','launchhung']:
 package='org.example.saildroid.'+name;app=apps/package;app.mkdir(mode=0o700);os.chown(app,account.pw_uid,account.pw_gid)
 for child in ['data','native']:(app/child).mkdir(mode=0o700);os.chown(app/child,account.pw_uid,account.pw_gid)
 for child in ['base.apk','icon.png']:(app/child).write_bytes(b'fixture')
 (app/'record.json').write_text(json.dumps(dict(package=package,apk=str(app/'base.apk'),native=str(app/'native'),icon=str(app/'icon.png'),data=str(app/'data'))))
 for child in app.iterdir():os.chown(child,account.pw_uid,account.pw_gid)
runtime=Path('/run/user')/str(account.pw_uid);runtime.mkdir(mode=0o700,parents=True,exist_ok=True);assert runtime.stat().st_uid in [0,account.pw_uid];os.chown(runtime,account.pw_uid,account.pw_gid)
logroot=Path('/home/art/data/logs');logroot.mkdir(parents=True,exist_ok=True);os.chown(logroot,account.pw_uid,account.pw_gid)
def command(name,*args):return ['/usr/bin/python3',str(bootstrap),'--package','org.example.saildroid.'+name,*args]
def start(name,*args):return subprocess.Popen(command(name,*args),user=account.pw_uid,group=account.pw_gid,env=dict(os.environ,SAILDROID_TEST_ENTRY=str(bootstrap)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
def run(name,*args):
 result=start(name,*args);stdout,stderr=result.communicate(timeout=12);assert result.returncode==0,(stdout,stderr);return json.loads(stdout)if args==('--status',)else stdout
def ready(name):
 deadline=time.monotonic()+6
 while True:
  state=run(name,'--status')
  if state.get('running')and state.get('socket')and Path(state['socket']).exists():return state
  if time.monotonic()>deadline:raise AssertionError(state)
  time.sleep(.05)
children=[]
try:
 one=start('launchone','--desktop-token','org.example.saildroid.launchone');children.append(one);first=ready('launchone')
 assert Path('/proc',str(first['supervisor_pid']),'cmdline').read_bytes().split(b'\0')[0]==b'saildroid-supervisor:activity:org.example.saildroid.launchone'
 duplicates=[start('launchone','--desktop-token','org.example.saildroid.launchone')for _ in range(20)]
 for child in duplicates:
  out,err=child.communicate(timeout=10);assert child.returncode==0,(out,err)
 assert run('launchone','--status')['pid']==first['pid']
 invalid=start('launchone','--desktop-token','org.example.saildroid.launchtwo')
 out,err=invalid.communicate(timeout=5);assert invalid.returncode!=0
 assert run('launchone','--status')['pid']==first['pid']
 with socket.socket(socket.AF_UNIX)as client:client.connect(first['socket']);client.sendall(b'spawn\n');assert client.recv(64)==b'spawned\n'
 second=ready('launchtwo');assert first['pid']!=second['pid']and second['supervisor_pgid']!=first['process_group']
 with socket.socket(socket.AF_UNIX)as client:client.connect(first['socket']);client.sendall(b'spawnservice\n');assert client.recv(64)==b'spawned\n'
 deadline=time.monotonic()+5;service=None
 while service is None:
  for file in (runtime/'saildroid').glob('org.example.saildroid.launchone.service.*.json'):
   record=json.loads(file.read_text())
   if record.get('state')=='running'and record.get('owner_launch_id')==first['launch_id']and Path(record['socket']).exists():service=record
  assert time.monotonic()<deadline;time.sleep(.03)
 run('launchone','--close');assert one.wait(timeout=3)==0
 deadline=time.monotonic()+4
 while Path('/proc',str(service['pid'])).exists()and time.monotonic()<deadline:time.sleep(.03)
 assert not Path('/proc',str(service['pid'])).exists(),service
 relaunched=start('launchone');children.append(relaunched);fresh=ready('launchone');assert fresh['pid']!=first['pid']and fresh['launch_id']!=first['launch_id'];run('launchone','--close');assert relaunched.wait(timeout=3)==0
 assert run('launchtwo','--status')['pid']==second['pid']and run('launchtwo','--status')['running']
 with socket.socket(socket.AF_UNIX)as client:client.connect(second['socket']);client.sendall(b'crash\n')
 deadline=time.monotonic()+3
 while True:
  state=run('launchtwo','--status')
  if state.get('state')=='exited':break
  assert time.monotonic()<deadline;time.sleep(.05)
 assert not state['running']and state['exit_code']==17 and state['exit_reason']=='failed'and not Path(second['socket']).exists()
 zero=start('launchtwo');children.append(zero);normal=ready('launchtwo')
 with socket.socket(socket.AF_UNIX)as client:client.connect(normal['socket']);client.sendall(b'exit0\n')
 assert zero.wait(timeout=4)==0
 state=run('launchtwo','--status');assert state['exit_code']==0 and state['exit_reason']=='exited'and not state['running']
 hung=start('launchhung');children.append(hung);ready('launchhung');begin=time.monotonic();run('launchhung','--close');assert hung.wait(timeout=3)==143 and time.monotonic()-begin<10
 print('LAUNCHER_PROCESSES=PASS|concurrent_requests=20|instances=1|lock_fd=isolated|nested_launch=independent|service_family=cleaned|relaunch=fresh|crash=recorded|unexpected_exit=classified|socket=cleaned|hung_close=bounded')
finally:
 for child in children:
  if child.poll()is None:child.terminate();child.wait(timeout=10)
