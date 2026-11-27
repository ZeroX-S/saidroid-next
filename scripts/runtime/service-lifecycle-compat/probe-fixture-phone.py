from pathlib import Path
import os,json,subprocess,pwd,time,zipfile,hashlib,base64,shutil
assert 'ID=sailfishos'in Path('/etc/sailfish-release').read_text();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot=='4fab5d11-f3fd-4a5f-8724-f20785e27485';assert Path('/home/art/test/.device-lock/owner').read_text().startswith('lifecycle305-fixture|')
root=Path(CFG['root']);pkg='org.example.saildroid.lifecycle';app=Path('/home/art/apps')/pkg;
if app.exists():
 previous=json.loads((app/'record.json').read_text());assert previous['package']==pkg and hashlib.sha256((app/'app.apk').read_bytes()).hexdigest()==CFG['prior_fixture_sha']
 for state in Path('/run/user/100000/saildroid').glob(pkg+'*.json'):
  d=json.loads(state.read_text());proc=Path('/proc')/str(d.get('pid',0))
  try:
   f=(proc/'stat').read_text().rsplit(') ',1)[1].split();assert not(f[0]not in ['Z','X']and int(f[19])==d.get('start_ticks'))
  except OSError:pass
 shutil.rmtree(app)
assert not app.exists();base=Path('/home/art/test')/CFG['label'];base.mkdir(mode=0o700);u=pwd.getpwnam('defaultuser');env=dict(os.environ,HOME=u.pw_dir,USER=u.pw_name,LOGNAME=u.pw_name,XDG_RUNTIME_DIR='/run/user/100000',WAYLAND_DISPLAY='../../display/wayland-0',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/100000/dbus/user_bus_socket');kw=dict(env=env,user=u.pw_uid,group=u.pw_gid,extra_groups=os.getgrouplist(u.pw_name,u.pw_gid));child=None;record=None;result=dict(passed=False,target_sdk=CFG['target_sdk'],root=str(root),expected=CFG['expected'])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();apk=base/'fixture.apk';apk.write_bytes(base64.b64decode(CFG['apk']));assert sha(apk)==CFG['sha256']

def alive(v):
 try:
  p=Path('/proc')/str(v['pid']);f=(p/'stat').read_text().rsplit(') ',1)[1].split();return f[0]not in ['Z','X']and int(f[19])==v['start_ticks']and v['boot']==boot and (p/'exe').resolve()==root/'libexec/saildroid-host'
 except(OSError,KeyError):return False
try:
 assert blank_display()['ready'];app.mkdir();(app/'lib').mkdir();(app/'data/files').mkdir(parents=True);shutil.copyfile(apk,app/'app.apk')
 (app/'icon.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='))
 (app/'record.json').write_text(json.dumps(dict(package=pkg,apk=str(app/'app.apk'),native=str(app/'lib'),data=str(app/'data'),icon=str(app/'icon.png'),apkSha256=CFG['sha256'],debuggable=False)))
 for p in [app,*app.rglob('*')]:os.chown(p,u.pw_uid,u.pw_gid)
 service_args=[];owner=None
 with(base/'entry.log').open('ab',buffering=0)as stream:child=subprocess.Popen([str(root/'libexec/saildroid-app'),'--package',pkg,*service_args],stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,**kw)
 until=time.monotonic()+70
 while time.monotonic()<until:
  instance=pkg+'.service.'+hashlib.sha256((pkg+':worker').encode()).hexdigest()[:16]if CFG.get('service')else pkg
  state=Path('/run/user/100000/saildroid')/(instance+'.json')
  if state.exists():
   v=json.loads(state.read_text())
   if CFG.get('service'):
    op=Path('/run/user/100000/saildroid')/(pkg+'.json')
    if op.exists():owner=json.loads(op.read_text())
    if owner and owner.get('pid')==child.pid and v.get('component')==str(root)and v.get('owner_launch_id')==owner.get('launch_id'):record=v
   elif v.get('pid')==child.pid and v.get('component')==str(root):record=v
  log=Path(record.get('log','/none'))if record else Path('/none');text=log.read_text(errors='replace').replace(chr(0),'')if log.is_file()else''
  if 'LIFECYCLE_FIXTURE=PASS|'in text or 'LIFECYCLE_FIXTURE=FAIL|'in text or child.poll()is not None:break
  time.sleep(.1)
 result['headless_service']=bool(CFG.get('service'));result['headless_marker']='LIFECYCLE_SERVICE=headless|'in text
 if CFG.get('service'):assert result['headless_marker']and owner and alive(owner)
 if record:result.update(pid=record['pid'],start_ticks=record['start_ticks'],role=record.get('role'),process_name=record.get('process_name'))
 result.update(child_code=child.poll(),main_alive=bool(record and alive(record)),marker_present='LIFECYCLE_FIXTURE=PASS|'in text,actual_target_marker='SDRUNTIME=sdk_policy|target='+str(CFG['target_sdk'])+'|source=parsed-apk-manifest'in text,baseline_rejected='LIFECYCLE_FIXTURE=FAIL|'in text and 'default service metadata'in text)
 if log.is_file():shutil.copyfile(log,base/'runtime.log')
 if result['marker_present']:
  import re
  result['checks']=int(re.search(r'LIFECYCLE_FIXTURE=PASS\|checks=(\d+)',text).group(1))
  assert result['checks']==40
  result['focus_abandon_count']=text.count('SDAUDIO=focus_abandon|owners=0|host_focus=unchanged|result=1')
  assert result['focus_abandon_count']==34
  if owner:
   shutil.copyfile(Path(owner['log']),base/'owner-runtime.log')
 if CFG['expected']=='negative-control':result['passed']=result['baseline_rejected']and result['main_alive']and not result['marker_present']
 else:result['passed']=result['marker_present']and result['actual_target_marker']and result['main_alive']and not result['baseline_rejected']
finally:
 if CFG.get('service')and record and alive(record):
  q=subprocess.run([str(root/'libexec/saildroid-app'),'--package',pkg,'--service',pkg+'.LifecycleService','--process',pkg+':worker','--close'],capture_output=True,timeout=18,**kw);result['service_close_code']=q.returncode
 if (record and alive(record))or(owner and alive(owner)):
  q=subprocess.run([str(root/'libexec/saildroid-app'),'--package',pkg,*service_args,'--close'],capture_output=True,timeout=18,**kw);result['close_code']=q.returncode
 if child:
  try:child.wait(timeout=5)
  except subprocess.TimeoutExpired:result['cleanup_process_alive']=True
 until=time.monotonic()+10
 while record and alive(record)and time.monotonic()<until:time.sleep(.1)
 result['display_cleanup']=blank_display();result['private_fixture_removed']=False
 if not result.get('cleanup_process_alive')and not(record and alive(record))and app.exists():
  assert json.loads((app/'record.json').read_text())['package']==pkg and sha(app/'app.apk')==CFG['sha256'];shutil.rmtree(app);result['private_fixture_removed']=True
 result['cleanup_safe']=result['display_cleanup']['ready']and result['private_fixture_removed']and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot
 (base/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
assert result['passed']and result['cleanup_safe']
