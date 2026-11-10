#!/usr/bin/python3
"""Manage host-owned SailDroid grants outside application ART processes."""
import argparse,hashlib,json,os,re,stat,tempfile
from pathlib import Path

POLICY=Path('/var/lib/saildroid/permissions')
SUPPORTED={'android.permission.'+name for name in ['CAMERA','RECORD_AUDIO','READ_EXTERNAL_STORAGE','WRITE_EXTERNAL_STORAGE']}

def digest(path):
 h=hashlib.sha256()
 with path.open('rb')as f:
  for block in iter(lambda:f.read(65536),b''):h.update(block)
 return h.hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',required=True);p.add_argument('--apk',type=Path,required=True)
 p.add_argument('--grant',action='append',default=[],choices=sorted(SUPPORTED));p.add_argument('--deny',action='append',default=[],choices=sorted(SUPPORTED));a=p.parse_args()
 if os.geteuid()!=0:raise SystemExit('Host permission changes require root')
 if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+',a.package):raise SystemExit('Invalid package')
 if set(a.grant)&set(a.deny):raise SystemExit('A permission cannot be both granted and denied')
 # The operator supplies the installed APK explicitly. APK declarations and
 # backend availability are still checked by the Android permission adapter.
 apk=a.apk.resolve(strict=True);sha=digest(apk)
 for folder in [Path('/var'),Path('/var/lib'),Path('/var/lib/saildroid'),POLICY]:
  if not folder.exists():folder.mkdir(mode=0o755)
  st=folder.lstat()
  if not stat.S_ISDIR(st.st_mode)or st.st_uid!=0 or st.st_mode&0o022:raise SystemExit('Untrusted policy directory: '+str(folder))
 target=POLICY/(a.package+'.properties');state={}
 if target.exists()or target.is_symlink():
  st=target.lstat()
  if not stat.S_ISREG(st.st_mode)or st.st_uid!=0 or st.st_mode&0o022:raise SystemExit('Untrusted policy record')
  for line in target.read_text().splitlines():
   if '='in line:k,v=line.split('=',1);state[k]=v
 if state.get('package')!=a.package or state.get('apk.sha256')!=sha:state={}
 if a.grant or a.deny:
  state.update({'package':a.package,'apk.sha256':sha})
  for name in a.grant:state[name]='granted'
  for name in a.deny:state[name]='denied'
  fd,name=tempfile.mkstemp(prefix='.permissions-',dir=POLICY)
  try:
   with os.fdopen(fd,'w')as out:
    os.fchmod(out.fileno(),0o644);out.write(''.join(k+'='+state[k]+'\n'for k in sorted(state)));out.flush();os.fsync(out.fileno())
   os.replace(name,target)
   directory=os.open(POLICY,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(directory)
   finally:os.close(directory)
  finally:
   if os.path.exists(name):os.unlink(name)
 print(json.dumps(dict(package=a.package,apk_sha256=sha,policy=state,modified=bool(a.grant or a.deny)),sort_keys=True))

if __name__=='__main__':main()
