#!/usr/bin/env python3
"""Real-process native manager gates on a disposable VM session bus."""
from pathlib import Path
import subprocess,json,sys,time,fcntl,os,select
root=Path(sys.argv[1]);exe=root/'libexec/saildroid-host';children=[]
def line(p):
 assert select.select([p.stdout],[],[],6)[0], 'fixture response deadline'
 return json.loads(p.stdout.readline())
def start(key,role='activity',owner=''):
 p=subprocess.Popen([str(exe),key,role,owner],text=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE);children.append(p);return p,line(p)
def request(p,text):p.stdin.write(text+'\n');p.stdin.flush();return line(p)
def stop(p):
 if p.poll() is None:p.stdin.write('exit\n');p.stdin.flush();p.wait(timeout=4)
daemon=subprocess.Popen([str(exe),'--session'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
try:
 for _ in range(60):
  r=subprocess.run(['gdbus','call','--session','--dest','org.saildroid.HostManager','--object-path','/org/saildroid/HostManager','--method','org.saildroid.HostManager1.GetState','org.example.a'],capture_output=True,text=True,timeout=2)
  if r.returncode==0:break
  time.sleep(.05)
 else:raise AssertionError('manager readiness')
 a,ra=start('org.example.a');assert ra['accepted'] and ra['pid']==a.pid
 dup,rd=start('org.example.a');assert not rd['accepted'] and rd['pid']==a.pid;dup.wait(timeout=3)
 b,rb=start('org.example.b');assert rb['accepted'] and rb['pid']==b.pid and b.pid!=a.pid
 assert request(a,'TryAcquireHeavy')['reply']=='(true,)'
 assert request(b,'TryAcquireHeavy')['reply']=='(false,)'
 c,rc=start('org.example.c');assert request(c,'TryAcquireHeavy')['reply']=='(false,)'
 assert request(a,'ReleaseHeavy')['reply']=='()'
 assert request(c,'TryAcquireHeavy')['reply']=='(false,)'
 assert request(b,'TryAcquireHeavy')['reply']=='(true,)'
 assert 'error' in request(b,'SetState org.example.a closing')
 assert 'error' in request(a,'Close org.example.a stale-generation')
 assert a.poll() is None, 'stale close reached the live generation'
 rt_base=Path(f'/run/user/{os.getuid()}')
 if not rt_base.exists():rt_base=Path(os.environ['XDG_RUNTIME_DIR'])
 lock=open(rt_base/'saildroid/org.example.a.lock','r+')
 try:fcntl.lockf(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);raise AssertionError('live host update lock missing')
 except BlockingIOError:pass
 wrong,rw=start('org.example.a.service.bad','service','wrong-generation');assert 'error' in rw;wrong.wait(timeout=3)
 service,rs=start('org.example.a.service.123','service',ra['launch_id']);assert rs['accepted']
 helper=request(a,'SpawnHelper')['helper_pid']
 stop(a)
 immediate,ri=start('org.example.a');assert ri['accepted']and ri['launch_id']!=ra['launch_id']
 stop(immediate)
 for _ in range(60):
  if service.poll() is not None:break
  time.sleep(.05)
 assert service.poll() is not None, 'service survived its owner'
 for _ in range(60):
  try:
   stat=Path('/proc/'+str(helper)+'/stat').read_text();state=stat[stat.rfind(') ')+2:].split()[0]
   if state in ('Z','X'):break
  except FileNotFoundError:break
  time.sleep(.05)
 else:raise AssertionError('helper outlived retired application family')
 assert b.poll() is None and c.poll() is None, 'unrelated app ended'
 for _ in range(60):
  try:fcntl.lockf(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
  except BlockingIOError:time.sleep(.05)
 else:raise AssertionError('Retired relaunch retained installation lock')
 blocked,rblocked=start('org.example.a');assert 'error' in rblocked;blocked.wait(timeout=3)
 fcntl.lockf(lock,fcntl.LOCK_UN);lock.close()
 again,rnew=start('org.example.a');assert rnew['accepted'] and rnew['launch_id']!=ra['launch_id']
 stop(b)
 for _ in range(60):
  value=request(c,'TryAcquireHeavy')['reply']
  if value=='(true,)':break
  time.sleep(.05)
 assert value=='(true,)', 'dead heavy owner retained admission'
 # A same-UID process with forged persistent host metadata must not be
 # re-adopted or signalled by the manager after restart.
 unrelated=subprocess.Popen(['/bin/sleep','30']);children.append(unrelated)
 raw=Path('/proc/'+str(unrelated.pid)+'/stat').read_text();fields=raw[raw.rfind(') ')+2:].split()
 forged=rt_base/'saildroid/org.example.forged.json'
 forged.write_text(json.dumps(dict(schema=3,pid=unrelated.pid,start_ticks=int(fields[19]),boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),component=str(root),package='org.example.forged',role='activity',launch_id='forged')))
 daemon.terminate();daemon.wait(timeout=3)
 daemon=subprocess.Popen([str(exe),'--session'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 for _ in range(60):
  r=subprocess.run(['gdbus','call','--session','--dest','org.saildroid.HostManager','--object-path','/org/saildroid/HostManager','--method','org.saildroid.HostManager1.GetState','org.example.c'],capture_output=True,text=True,timeout=2)
  if r.returncode==0 and rc['launch_id'] in r.stdout:break
  time.sleep(.05)
 else:raise AssertionError('manager did not re-adopt live host')
 assert request(c,'GetState org.example.forged')['reply']=="('{\"running\":false}',)"
 assert unrelated.poll() is None,'unrelated executable was signalled'
 forged.unlink();unrelated.terminate();unrelated.wait(timeout=3)
 base_sig=request(c,'SignalCount')['signals']
 assert request(c,'SetState org.example.c art-running')['reply']=='()'
 woke1=request(c,f'WaitSignal {base_sig}')
 assert woke1['woke'] and woke1['signals']>base_sig,'StateChanged signal did not wake client on SetState'
 base_sig2=woke1['signals']
 assert request(c,'TryAcquireHeavy')['reply']=='(true,)'
 assert request(c,'ReleaseHeavy')['reply']=='()'
 woke2=request(c,f'WaitSignal {base_sig2}')
 assert woke2['woke'] and woke2['signals']>base_sig2,'StateChanged signal did not wake client on ReleaseHeavy'
 print('NATIVE_MANAGER=PASS|cases=dedup,concurrent-apps,fair-admission,lease-auth,stale-close,install-lock,service-generation,owner-cleanup,immediate-relaunch-cleanup,helper-group-cleanup,unrelated-survival,relaunch,dead-admission-release,manager-readoption,forged-executable-rejected,state-changed-signal')
finally:
 for p in children:
  try:stop(p)
  except Exception:
   if p.poll() is None:p.terminate();p.wait(timeout=3)
 daemon.terminate();daemon.wait(timeout=3)
