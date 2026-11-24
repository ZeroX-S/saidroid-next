#!/usr/bin/python3
"""Ordinary-user desktop entry point for one installed SailDroid application."""
from pathlib import Path
import argparse,ctypes,fcntl,json,os,pwd,re,stat,subprocess,sys,time,socket,struct,signal,uuid,hashlib
ROOT=Path('/home/art/api29-root')
APPS=Path('/home/art/apps')
NAME=re.compile(r'[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+')
BROKER='org.saildroid.binder'

def supervisor_title(role,name):
    """Publish this process as a supervisor, distinct from its Android child.

    Sailfish matches desktop Exec tokens against /proc cmdline. Leaving the
    launch request there can make it select this windowless Python process.
    Change only our existing argv storage, after Python has parsed its options.
    Never extend into the environment or change another process's identity.
    """
    raw=Path('/proc/self/stat').read_text();fields=raw[raw.rfind(') ')+2:].split()
    start,end=int(fields[45]),int(fields[46]);command=Path('/proc/self/cmdline').read_bytes()
    libc=ctypes.CDLL(None);original=ctypes.c_void_p.in_dll(libc,'program_invocation_name')
    if start!=original.value or not 0<end-start<=65536 or end-start!=len(command):
        raise RuntimeError('Supervisor argument storage could not be verified')
    if ctypes.string_at(start,len(command))!=command:
        raise RuntimeError('Supervisor argument storage changed')
    title=('saildroid-supervisor:'+role+':'+name).encode('ascii')[:end-start-1]
    ctypes.memmove(start,title,len(title));ctypes.memset(start+len(title),0,end-start-len(title))
    ctypes.c_void_p.in_dll(libc,'program_invocation_short_name').value=start

def trusted(file):
    value=file.stat()
    if value.st_uid!=0 or value.st_mode&0o022:raise RuntimeError('SailDroid component is writable by an untrusted owner')
    return file

def read_record(name):
    if not NAME.fullmatch(name)or name=='android' or name.startswith('org.saildroid.'):
        raise ValueError('Invalid installed application name')
    app=APPS/name
    if app.is_symlink()or app.resolve().parent!=APPS.resolve():raise ValueError('Invalid installed application directory')
    data=json.loads((app/'record.json').read_text())
    if data['package']!=name:raise ValueError('Application record identity differs')
    for key in ['apk','native','icon','data']:
        path=Path(data[key]);resolved=path.resolve()
        if app.resolve()not in resolved.parents:raise ValueError('Application paths escaped their installation directory')
    if not Path(data['apk']).is_file()or not Path(data['native']).is_dir():raise ValueError('Application installation is incomplete')
    return data

def ticks(pid):
    raw=(Path('/proc')/str(pid)/'stat').read_text();return int(raw[raw.rfind(') ')+2:].split()[19])

def process_alive(record):
    try:
        pid=record['pid']
        if not isinstance(pid,int)or pid<=1 or ticks(pid)!=record['start_ticks']:return False
        status=(Path('/proc')/str(pid)/'status').read_text()
        if int(next(l for l in status.splitlines()if l.startswith('Uid:')).split()[1])!=os.getuid():return False
        state=next(l for l in status.splitlines()if l.startswith('State:')).split()[1]
        return state not in ('Z','X')and record['boot']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except (OSError,KeyError,ValueError):return False

def send_existing(record,verb='activate'):
    pid=record['pid']
    if ticks(pid)!=record['start_ticks']:raise RuntimeError('Previous application process ended')
    status=(Path('/proc')/str(pid)/'status').read_text();uid=int(next(l for l in status.splitlines()if l.startswith('Uid:')).split()[1])
    if uid!=os.getuid():raise RuntimeError('Application process owner differs')
    endpoint=Path(record['socket']);deadline=time.monotonic()+5
    while True:
        client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);client.settimeout(3)
        try:client.connect(str(endpoint));break
        except (FileNotFoundError,ConnectionRefusedError):
            client.close()
            if time.monotonic()>deadline:raise RuntimeError('Application window did not become ready')
            if ticks(pid)!=record['start_ticks']:raise RuntimeError('Application process ended during startup')
            time.sleep(.05)
    with client:
        peer_pid,peer_uid,_=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if peer_pid!=pid or peer_uid!=os.getuid():raise RuntimeError('Application window endpoint identity differs')
        client.sendall((verb+'\n').encode('ascii'))
        expected=b'closing\n'if verb=='close'else b'requested\n'
        if client.recv(64)!=expected:raise RuntimeError('Window request is unavailable')

def save_record(target,record):
    temporary=target.with_name('.'+target.name+'.'+uuid.uuid4().hex)
    with open(temporary,'x',opener=lambda path,flags:os.open(path,flags,0o600))as stream:
        json.dump(record,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,target)

def await_existing(target):
    deadline=time.monotonic()+5
    while True:
        try:
            record=json.loads(target.read_text())
            if process_alive(record):return record
            if record.get('state')=='exited':
                owner=dict(record,pid=record.get('supervisor_pid'),start_ticks=record.get('supervisor_start_ticks'))
                if process_alive(owner):raise RuntimeError('The application exited; see '+record.get('log','its runtime log'))
        except (FileNotFoundError,json.JSONDecodeError):pass
        if time.monotonic()>deadline:raise RuntimeError('Application startup did not publish a live process')
        time.sleep(.03)

def terminate_owned(record):
    if not process_alive(record):return
    # Prefer the per-app supervisor, which owns this child's process group.
    supervisor=dict(record,pid=record.get('supervisor_pid'),start_ticks=record.get('supervisor_start_ticks'))
    if process_alive(supervisor):os.kill(supervisor['pid'],signal.SIGTERM)
    else:os.kill(record['pid'],signal.SIGTERM)  # legacy component process

def close_existing(record):
    try:send_existing(record,'close')
    except (OSError,RuntimeError):terminate_owned(record)
    deadline=time.monotonic()+8
    while process_alive(record)and time.monotonic()<deadline:time.sleep(.05)
    if process_alive(record):
        terminate_owned(record)
        deadline=time.monotonic()+3
        while process_alive(record)and time.monotonic()<deadline:time.sleep(.05)
    if process_alive(record):raise RuntimeError('Application did not close')

def family_lock(runtime,name):
    return os.open(runtime/(name+'.family.lock'),os.O_CREAT|os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)

def validate_service_owner(record,runtime):
    owner=json.loads((runtime/(record['package']+'.json')).read_text())
    if owner.get('launch_id')!=record.get('owner_launch_id')or not process_alive(owner):raise RuntimeError('The owning application has exited')

def close_service_children(record,runtime):
    if record.get('role')!='activity':return
    guard=family_lock(runtime,record['package']);fcntl.flock(guard,fcntl.LOCK_EX)
    try:
        children=[]
        for file in runtime.glob('*.json'):
            try:
                child=json.loads(file.read_text())
                if child.get('role')=='service'and child.get('package')==record['package']and child.get('owner_launch_id')==record['launch_id']:
                    owner=dict(child,pid=child.get('supervisor_pid'),start_ticks=child.get('supervisor_start_ticks'))
                    if process_alive(owner):children.append(child)
            except (OSError,ValueError):continue
        for child in children:
            if process_alive(child):
                try:send_existing(child,'close')
                except (OSError,RuntimeError):terminate_owned(child)
            else:
                owner=dict(child,pid=child.get('supervisor_pid'),start_ticks=child.get('supervisor_start_ticks'))
                if process_alive(owner):os.kill(owner['pid'],signal.SIGTERM)
        deadline=time.monotonic()+7
        for child in children:
            while process_alive(child)and time.monotonic()<deadline:time.sleep(.05)
            if process_alive(child):terminate_owned(child)
    finally:os.close(guard)

def ensure_broker(runtime):
    target=runtime/(BROKER+'.json')
    def ready():
        try:
            record=json.loads(target.read_text())
            return process_alive(record)and Path(record['ready_file']).read_text().strip()==str(record['pid'])
        except (OSError,ValueError,KeyError):return False
    if ready():return
    child=subprocess.Popen([sys.executable,str(ROOT/'libexec/saildroid-open'),'--broker'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,start_new_session=True)
    deadline=time.monotonic()+20
    while not ready():
        if time.monotonic()>deadline:raise RuntimeError('Private Binder registry did not start; inspect its runtime log')
        if child.poll()is not None and child.returncode!=0:raise RuntimeError('Private Binder registry failed to start')
        time.sleep(.05)

def supervise(command,env,record,target,output):
    # The Android process receives no instance-lock descriptor. Library code
    # closing inherited fds cannot release another launcher's instance lock.
    # A launch can originate inside another Android app (e.g. the installer).
    # Its supervisor must leave that caller's process group before the caller
    # can close; the ART child receives its own group as well.
    try:os.setsid()
    except PermissionError:
        if os.getpgrp()!=os.getpid():raise
    signal.pthread_sigmask(signal.SIG_UNBLOCK,{signal.SIGTERM,signal.SIGINT,signal.SIGHUP,signal.SIGCHLD})
    requested=[False];child=None
    def forward(signum,frame):
        requested[0]=True
        if child is not None and child.poll()is None:
            try:os.killpg(child.pid,signum)
            except ProcessLookupError:pass
    for signum in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(signum,forward)
    record.update(schema=2,state='starting',supervisor_pid=os.getpid(),supervisor_start_ticks=ticks(os.getpid()),supervisor_pgid=os.getpgrp(),pid=None,start_ticks=None)
    save_record(target,record)
    guard=None
    try:
        with os.fdopen(output,'ab',buffering=0)as stream:
            os.dup2(stream.fileno(),1);os.dup2(stream.fileno(),2)
            if record.get('role')=='service':
                guard=family_lock(target.parent,record['package']);fcntl.flock(guard,fcntl.LOCK_SH);validate_service_owner(record,target.parent)
            child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,env=env,close_fds=True,start_new_session=True)
            record.update(pid=child.pid,start_ticks=ticks(child.pid),process_group=child.pid,state='running');save_record(target,record)
            if guard is not None:os.close(guard);guard=None
            stream.write(('SDLAUNCHER=started|package='+record['package']+'|pid='+str(child.pid)+'|supervisor='+str(os.getpid())+'\n').encode())
            seen_window=False;closing=None;term_sent=None
            while child.poll()is None:
                exists=Path(record['socket']).exists();seen_window|=exists
                if seen_window and not exists and closing is None:closing=time.monotonic();requested[0]=True
                if (requested[0]or closing is not None)and term_sent is None:
                    if closing is None or time.monotonic()-closing>5:
                        os.killpg(child.pid,signal.SIGTERM);term_sent=time.monotonic()
                if term_sent is not None and time.monotonic()-term_sent>3:os.killpg(child.pid,signal.SIGKILL)
                time.sleep(.05)
            code=child.wait()
            closed=requested[0]or(seen_window and not Path(record['socket']).exists())
            # Reap/terminate only helpers belonging to this application's group.
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            close_service_children(record,target.parent)
            endpoint=Path(record['socket'])
            try:
                info=endpoint.lstat()
                if stat.S_ISSOCK(info.st_mode)and info.st_uid==os.getuid():endpoint.unlink()
            except FileNotFoundError:pass
            if record.get('ready_file'):
                ready=Path(record['ready_file'])
                try:
                    info=ready.lstat()
                    if stat.S_ISREG(info.st_mode)and info.st_uid==os.getuid():ready.unlink()
                except FileNotFoundError:pass
            record.update(state='exited',exit_code=code,exit_reason='closed'if closed else'exited'if code==0 else'failed',ended=time.time());save_record(target,record)
            stream.write(('SDLAUNCHER=exited|package='+record['package']+'|code='+str(code)+'|reason='+record['exit_reason']+'\n').encode())
            return code if code>=0 else 128-code
    except BaseException as failure:
        record.update(state='exited',exit_code=125,exit_reason='launch-failed',error=str(failure),ended=time.time());save_record(target,record)
        raise
    finally:
        if guard is not None:os.close(guard)
        if child is not None and child.poll()is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()

def main():
    if os.getuid()==0:raise RuntimeError('Launch SailDroid as the phone user')
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--manager',action='store_true');group.add_argument('--package');group.add_argument('--broker',action='store_true')
    parser.add_argument('--service');parser.add_argument('--process')
    parser.add_argument('--debug-log',action='store_true');parser.add_argument('--desktop-token')
    parser.add_argument('source',nargs='?');parser.add_argument('--install');actions=parser.add_mutually_exclusive_group();actions.add_argument('--is-running',action='store_true');actions.add_argument('--status',action='store_true');actions.add_argument('--close',action='store_true');actions.add_argument('--dump-threads',action='store_true');args=parser.parse_args()
    args.install=args.install or args.source
    if args.process and not args.service:raise ValueError('A secondary process requires a declared service')
    if args.install and not args.manager:raise ValueError('APK installation belongs to the installer')
    trusted(ROOT);manifest=json.loads(trusted(ROOT/'runtime.json').read_text())
    if manifest['api']!=29:raise RuntimeError('API 29 component manifest required')
    if args.broker:
        if not manifest.get('binder_device'):raise RuntimeError('Private Binder is not enabled in this component')
        name=BROKER;app=dict(package=name,apk=str(ROOT/'share/manager.apk'),native=str(ROOT/'empty-libs'),data='/home/art/data/binder')
    elif args.manager:
        name='org.saildroid.manager';app=dict(package=name,apk=str(ROOT/'share/manager.apk'),native=str(ROOT/'empty-libs'),data='/home/art/data/manager')
    else:
        name=args.package;app=read_record(name)
        if args.install:raise ValueError('APK installation belongs to the SailDroid installer')
    account=pwd.getpwuid(os.getuid());runtime=Path('/run/user')/str(account.pw_uid)/'saildroid';runtime.mkdir(mode=0o700,exist_ok=True)
    if runtime.is_symlink()or runtime.stat().st_uid!=os.getuid():raise RuntimeError('Invalid runtime directory')
    if args.service:
        if not args.package or not args.process or not NAME.fullmatch(args.service)or not re.fullmatch(r'[A-Za-z0-9_.]+(?::[A-Za-z0-9_.]+)?',args.process):raise ValueError('Declared service and process identity required')
    role='broker'if args.broker else'service'if args.service else'activity'
    if args.desktop_token is not None and(args.desktop_token!=name or role!='activity'):raise ValueError('Desktop token differs from the real Android process identity')
    activation='activate'
    if args.install:
        from urllib.parse import urlparse,unquote
        uri=urlparse(args.install)
        if uri.scheme and(uri.scheme!='file'or uri.netloc not in ('','localhost')):raise ValueError('Select a local APK file')
        source=Path(unquote(uri.path)if uri.scheme else args.install).resolve()
        if not source.is_file():raise ValueError('APK file cannot be read')
        args.install=str(source);activation='open '+source.as_uri()
        if len(activation.encode('ascii'))>16380:raise ValueError('APK file path is too long')
    instance=name+'.service.'+hashlib.sha256(args.process.encode()).hexdigest()[:16]if args.service else name
    target=runtime/(instance+'.json')
    # Queries must not temporarily take the instance lock: a simultaneous
    # real launch could otherwise mistake the querying process for its owner.
    if args.status or args.is_running or args.close or args.dump_threads:
        record=json.loads(target.read_text())if target.exists()else {}
        running=process_alive(record)
        owner=dict(record,pid=record.get('supervisor_pid'),start_ticks=record.get('supervisor_start_ticks'))
        starting=record.get('state')=='starting'and process_alive(owner)
        if args.is_running:return 0 if running or starting else 1
        if args.status:print(json.dumps(dict(record,package=name,running=running)));return 0
        if args.dump_threads:
            if not running:raise RuntimeError('Application is not running')
            send_existing(record,'dump');print(record['log']);return 0
        if running:close_existing(record)
        elif starting:
            os.kill(owner['pid'],signal.SIGTERM)
            deadline=time.monotonic()+8
            while process_alive(owner)and time.monotonic()<deadline:time.sleep(.05)
            if process_alive(owner):raise RuntimeError('Starting application did not close')
        return 0
    if manifest.get('binder_device')and not args.broker:ensure_broker(runtime)
    lock_file=runtime/(instance+'.lock');lock=os.open(lock_file,os.O_CREAT|os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
    try:fcntl.lockf(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        record=await_existing(target)
        if role!='activity':return 0
        send_existing(record,activation);return 0
    previous=json.loads(target.read_text())if target.exists()else None
    # Also recognize live processes from an older component whose application
    # code may already have closed its inherited lock fd.
    if previous is not None and process_alive(previous):
        if role!='activity':return 0
        send_existing(previous,activation);return 0
    data=Path(app['data']);data.mkdir(mode=0o700,parents=True,exist_ok=True)
    for child in ['cache','files','code_cache','device-protected']:(data/child).mkdir(mode=0o700,exist_ok=True)
    log_dir=Path('/home/art/data/logs')/name;log_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    log=log_dir/(time.strftime('%Y%m%dT%H%M%S')+'-'+str(os.getpid())+'.log')
    output=os.open(log,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    launch_id=uuid.uuid4().hex
    record=dict(package=name,role=role,process_name=args.process or name,launch_id=launch_id,owner_launch_id=os.environ.get('SAILDROID_APP_LAUNCH_ID')if args.service else None,boot=boot,log=str(log),app_id='org.saildroid.app.p'+hashlib.sha256(name.encode()).hexdigest()[:20],socket=str(runtime/('window-'+launch_id[:20]+'.sock')))
    if args.broker:record['ready_file']=str(runtime/('registry-ready-'+launch_id[:20]))
    jars=[]
    for relative in manifest['boot_jars']:
        file=ROOT/relative
        if ROOT.resolve()not in file.resolve().parents:raise RuntimeError('Boot class path escaped the component')
        trusted(file);jars.append(str(file))
    command=[str(trusted(ROOT/'libexec/saildroid-launch')),'-Xnoimage-dex2oat','-Xbootclasspath:'+':'.join(jars),'-Djava.library.path='+app['native']+':'+str(ROOT/'android-libs')+':/home/art/lib',
        '-Dsaidroid.bridge.library='+str(ROOT/'lib/libsdbridge.so'),'-Dsaidroid.window.library='+str(ROOT/'lib/libsdwindow.so'),'-Dsaidroid.ime.library='+str(ROOT/'lib/libsdmaliit.so'),
        '-Dsaidroid.native.runtime='+str(ROOT/'android-libs'),'-Dsaidroid.package='+name,'-Dsaidroid.apk='+app['apk'],'-Dsaidroid.native='+app['native'],'-Dsaidroid.data='+app['data']]
    if manifest.get('binder_device'):command.append('-Dsaidroid.binder.driver='+manifest['binder_device'])
    if args.debug_log:command.append('-Dsaidroid.vmExitDiagnostics=true')
    if args.service:
        command+=['-Dsaidroid.service='+args.service,'-Dsaidroid.process='+args.process]
    if args.install:
        command.append('-Dsaidroid.install.source='+args.install)
    command+=['-cp',str(ROOT/'lib/runtime.jar'),'SdBinderRegistry'if args.broker else'SdRuntime']
    child_env=dict(os.environ,SAILDROID_CONTROL_SOCKET=record['socket'],SAILDROID_APP_LAUNCH_ID=record['owner_launch_id']if args.service else launch_id)
    child_env.pop('SAILDROID_ART_EXECUTABLE',None)
    if args.debug_log:child_env['SAILDROID_ANDROID_LOG_STDERR']='1'
    if role=='activity':child_env['SAILDROID_DESKTOP_ID']='org.saildroid.app.p'+hashlib.sha256(name.encode()).hexdigest()[:20]
    else:child_env.pop('SAILDROID_DESKTOP_ID',None)
    if args.broker:child_env['SAILDROID_READY_FILE']=record['ready_file']
    supervisor_title(role,name)
    return supervise(command,child_env,record,target,output)

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as error:print('SailDroid: '+str(error),file=sys.stderr);sys.exit(2)
