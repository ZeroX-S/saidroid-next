"""Physical launch / real Binder Activity result contract. Run under devlock.
The fixture is private and never receives a desktop entry.
"""
from pathlib import Path
import subprocess,os,pwd,time,json,sys,hashlib,importlib.util,re,shutil,ctypes
label,component,expect=sys.argv[1:4]
assert re.fullmatch('[a-z0-9-]+',label) and expect in ['cohosted','isolated']
root=Path(component);assert re.fullmatch('/home/art/releases/api29-[a-z0-9-]+',component)
assert Path('/home/art/test/.device-lock/owner').is_file()
assert 'ID=sailfishos' in Path('/etc/sailfish-release').read_text()
pkg='org.example.saildroid.remoteactivity';base=Path('/home/art/test')/label;base.mkdir(exist_ok=False,mode=0o700)
u=pwd.getpwnam('defaultuser');env=dict(os.environ,HOME=u.pw_dir,USER=u.pw_name,LOGNAME=u.pw_name,XDG_RUNTIME_DIR='/run/user/100000',WAYLAND_DISPLAY='../../display/wayland-0',DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/100000/dbus/user_bus_socket');kw=dict(env=env,user=u.pw_uid,group=u.pw_gid,extra_groups=os.getgrouplist(u.pw_name,u.pw_gid))
host=root/'libexec/saildroid-app';rt=Path('/run/user/100000/saildroid');boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();lip=subprocess.check_output(['pidof','lipstick'],text=True).strip();record=None;remote=None;store=None;child=None;inp=None
spec=importlib.util.spec_from_file_location('matrix','/home/art/test/r86-ui-tools/integration-matrix.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
shots=Path(u.pw_dir)/'Downloads/SailDroid-Screenshots'/label;shots.mkdir(exist_ok=False);os.chown(shots,u.pw_uid,u.pw_gid)
def read(name):
 try:return json.loads((rt/(name+'.json')).read_text())
 except (OSError,ValueError):return {}
def alive(r):
 try:
  p=Path('/proc')/str(r['pid']);s=(p/'stat').read_text().rsplit(') ',1)[1].split();return r['boot']==boot and s[0]not in ['Z','X'] and int(s[19])==r['start_ticks'] and(p/'exe').resolve()==root/'libexec/saildroid-host'
 except (OSError,KeyError):return False
def text(r):
 p=Path(r.get('log','/nonexistent'));return p.read_text(errors='replace').replace(chr(0),'')if p.is_file()else''
def wait(test,seconds,reason):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  value=test()
  if value:return value
  if child is not None and child.poll()is not None:raise AssertionError('Parent process exited: '+reason)
  time.sleep(.08)
 raise AssertionError(reason)
def capture(tag):
 p=shots/(tag+'.png');m.run(['gdbus','call','--session','--dest','org.nemomobile.lipstick','--object-path','/org/nemomobile/lipstick/screenshot','--method','org.nemomobile.lipstick.saveScreenshot',str(p)],timeout=8)
 end=time.monotonic()+4;previous=-1;stable=0
 while time.monotonic()<end:
  if p.exists():
   b=p.read_bytes();stable=stable+1 if len(b)==previous and len(b)>5000 and b[:8]==bytes.fromhex('89504e470d0a1a0a')and b[16:24]==bytes.fromhex('0000043800000870')else 0;previous=len(b)
   if stable>=2:return str(p)
  time.sleep(.15)
 raise AssertionError('Incomplete screenshot')
def shot(tag,colour):
 end=time.monotonic()+15;attempt=0
 while time.monotonic()<end:
  attempt+=1;p=Path(capture(tag+'-attempt-'+str(attempt)));w,h,rows=png_rows(p);total=matching=0
  for y in range(250,h-200,80):
   for x in range(80,w-80,80):
    pixel=m.sd_covers.png_px(rows,x,y);total+=1;matching+=all(abs(pixel[i]-colour[i])<=12 for i in range(3))
  if matching/total>=.80:
   final=shots/(tag+'.png');shutil.copyfile(p,final);final.chmod(0o600);print('VISIBLE_COLOUR',tag,round(matching/total,3),flush=True);return str(final)
  print('VISIBLE_RETRY',tag,attempt,round(matching/total,3),'top='+str(m.top()),flush=True);time.sleep(.2)
 raise AssertionError('Actual full-screen '+tag+' content was not visible')
class PngImage(ctypes.Structure):
 _fields_=[('opaque',ctypes.c_void_p),('version',ctypes.c_uint32),('width',ctypes.c_uint32),('height',ctypes.c_uint32),('format',ctypes.c_uint32),('flags',ctypes.c_uint32),('colormap_entries',ctypes.c_uint32),('warning_or_error',ctypes.c_uint32),('message',ctypes.c_char*64)]
png=ctypes.CDLL('libpng16.so.16');png.png_image_begin_read_from_file.argtypes=[ctypes.POINTER(PngImage),ctypes.c_char_p];png.png_image_finish_read.argtypes=[ctypes.POINTER(PngImage),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int32,ctypes.c_void_p];png.png_image_free.argtypes=[ctypes.POINTER(PngImage)]
def png_rows(path):
 picture=PngImage();picture.version=1
 assert png.png_image_begin_read_from_file(ctypes.byref(picture),os.fsencode(path)),picture.message
 try:
  picture.format=3;w,h=picture.width,picture.height;data=(ctypes.c_ubyte*(w*h*4))()
  assert png.png_image_finish_read(ctypes.byref(picture),None,data,0,None),picture.message
  raw=bytes(data);return w,h,[raw[y*w*4:(y+1)*w*4]for y in range(h)]
 finally:png.png_image_free(ctypes.byref(picture))
watch=subprocess.Popen(['python3','-c',"import time,subprocess;time.sleep(110);subprocess.run(['mcetool','--set-never-blank=disabled','--blank-screen'])"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
try:
 subprocess.run(['mcetool','--set-never-blank=disabled','--set-blank-timeout=70','--unblank-screen','--set-tklock-mode=unlocked'],check=True,timeout=5)
 with(base/'entry.log').open('w')as f:child=subprocess.Popen([str(host),'--package',pkg,'--debug-log'],stdout=f,stderr=subprocess.STDOUT,**kw)
 record=wait(lambda:r if(r:=read(pkg)).get('pid')==child.pid and alive(r)and 'REMOTE_ACTIVITY=parent_created' in text(r)and 'SDWINDOW_SESSION=drawn|title='+pkg+'/'+pkg+'.ParentActivity'in text(r)else None,45,'Parent first Activity did not render')
 wait(lambda:m.top()==record['pid'],5,'Parent not foreground');shot('parent-before',(224,242,254))
 assert 'REMOTE_ACTIVITY=thread_priority|nice=-10|restored=0'in text(record)and 'REMOTE_ACTIVITY=battery|capacity='in text(record)
 inp=subprocess.Popen(['/home/art/bin/sdinput','serve'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True);time.sleep(1.4)
 assert alive(record)and m.top()==record['pid'];inp.stdin.write('tap 540 500\nsleep 250\n');inp.stdin.flush()
 wait(lambda:'REMOTE_ACTIVITY=parent_requested'in text(record),5,'Physical button did not start Activity')
 if expect=='cohosted':
  wait(lambda:'REMOTE_ACTIVITY=child_created'in text(record),10,'Old cohosted Activity did not run');assert '|isolated=false|'in text(record);remote=record
 else:
  key=pkg+'.service.'+hashlib.sha256((pkg+':tool').encode()).hexdigest()[:16]
  remote=wait(lambda:r if(r:=read(key))and alive(r)and 'REMOTE_ACTIVITY=child_created'in text(r)else None,150,'Declared process did not create child Activity')
  assert remote['pid']!=record['pid']and remote['owner_launch_id']==record['launch_id']and remote['process_name']==pkg+':tool'
  assert '|isolated=true|'in text(remote),text(remote)[-1000:]
  assert 'REMOTE_ACTIVITY=provider_roundtrip|owner_pid='+str(record['pid'])+'|valid=true'in text(remote)
  store_key=pkg+'.service.'+hashlib.sha256((pkg+':store').encode()).hexdigest()[:16]
  store=wait(lambda:r if(r:=read(store_key))and alive(r)and 'SDRUNTIME=service_process_ready|process='+pkg+':store'in text(r)else None,150,'Provider did not start in its declared headless process')
  assert store['pid']not in [record['pid'],remote['pid']]and store['owner_launch_id']==record['launch_id']and not store.get('window_mapped',False)
  assert 'REMOTE_ACTIVITY=provider_started|owner_pid='+str(store['pid'])+'|valid=true'in text(remote)
 wait(lambda:m.top()==remote['pid']and 'SDWINDOW_SESSION=drawn|title='+pkg+'/'+pkg+'.ChildActivity'in text(remote),5,'Child Activity did not present its actual window');shot('child-visible',(6,95,70))
 if expect=='isolated':
  again=subprocess.run([str(host),'--package',pkg],capture_output=True,text=True,timeout=8,**kw);assert again.returncode==0,again.stderr
  wait(lambda:m.top()==remote['pid'],3,'Repeated app entry displaced its remote Activity')
  assert read(pkg)['launch_id']==record['launch_id']and alive(remote)
  shot('child-after-reopen',(6,95,70))
 inp.stdin.write('tap 540 500\nsleep 250\n');inp.stdin.flush()
 wait(lambda:'REMOTE_ACTIVITY=child_return_tapped'in text(remote),5,'Physical child return button did not handle input')
 expected='REMOTE_ACTIVITY=FAIL'if expect=='cohosted'else'REMOTE_ACTIVITY=PASS'
 wait(lambda:expected in text(record),15,'Activity result not delivered with expected isolation')
 assert 'before_resume=true'in text(record)
 wait(lambda:m.top()==record['pid'],5,'Result did not restore original parent');assert alive(record);shot('parent-after',(224,242,254))
 if expect=='isolated':
  wait(lambda:alive(remote)and 'SDACTIVITY=remote_stack_empty|process_retained=true'in text(remote),5,'Returning the child destroyed its process')
  created=text(remote).count('REMOTE_ACTIVITY=child_created');passed=text(record).count('REMOTE_ACTIVITY=PASS')
  inp.stdin.write('tap 540 500\nsleep 250\n');inp.stdin.flush()
  wait(lambda:text(remote).count('REMOTE_ACTIVITY=child_created')==created+1,15,'Retained process did not reopen its Activity')
  current=read(key);assert alive(current)and current['pid']==remote['pid']and current['launch_id']==remote['launch_id']
  wait(lambda:m.top()==remote['pid'],5,'Reopened Activity did not regain foreground');shot('child-second-launch',(6,95,70))
  inp.stdin.write('tap 540 500\nsleep 250\n');inp.stdin.flush()
  wait(lambda:text(record).count('REMOTE_ACTIVITY=PASS')==passed+1,15,'Second result failed in retained process')
  wait(lambda:m.top()==record['pid'],5,'Second result did not restore parent');assert alive(remote)
 for r in [record,remote]:assert 'SDRUNTIME=uncaught'not in text(r)and'SDRUNTIME=failed'not in text(r)
 result=dict(expectation=expect,parent_pid=record['pid'],child_pid=remote['pid'],provider_pid=store['pid']if store else None,same_parent=True,real_result_before_resume=True,child_process_reused=expect=='isolated',component=component,boot=boot,status='negative-reproduced'if expect=='cohosted'else'PASS')
 (base/'result.json').write_text(json.dumps(result,indent=2)+'\n');print('REMOTE_ACTIVITY_CONTRACT='+result['status']+'|parent_pid='+str(record['pid'])+'|child_pid='+str(remote['pid'])+'|result_before_resume=true',flush=True)
finally:
 subprocess.run(['mcetool','--set-never-blank=disabled','--blank-screen'],timeout=5)
 if inp:
  try:inp.stdin.write('quit\n');inp.stdin.flush();inp.wait(timeout=3)
  except:inp.terminate();inp.wait(timeout=3)
 for name,r in [('parent',record),('child',remote),('provider',store)]:
  if r and Path(r['log']).exists():(base/(name+'.log')).write_bytes(Path(r['log']).read_bytes());(base/(name+'.log')).chmod(0o600)
 for args in [['--package',pkg,'--close'],['--broker','--close']]:subprocess.run([str(host)]+args,capture_output=True,timeout=18,**kw)
 if child is not None:child.wait(timeout=5)
 watch.terminate();watch.wait(timeout=3)
 wait(lambda:Path('/sys/class/backlight/panel0-backlight/actual_brightness').read_text().strip()=='0',3,'OLED cleanup failed')
 assert boot==Path('/proc/sys/kernel/random/boot_id').read_text().strip()and lip==subprocess.check_output(['pidof','lipstick'],text=True).strip()
 print('FINAL_BRIGHTNESS=0|boot_and_lipstick_unchanged=true',flush=True)
