#!/usr/bin/env python3
"""Install the WebView regression APK into /home/art/apps so the normal launcher
(saildroid-open --package ...) can run it as the ordinary phone user.

Run inside the MeeGo Build VM, with the device lock held.

    python3 scripts/perf/install-probe-apk-vm.py <tag>

This writes only private /home/art content: the app directory, its record and
its data directory, all owned by defaultuser(100000).
"""
from pathlib import Path
import hashlib, os, subprocess, sys

PACKAGE = 'org.example.saildroid.remoteactivity'
BASE = '/home/art/apps/' + PACKAGE
SSH = ['sshpass', '-e', 'ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=8',
       'root@bonito']
SCP = ['sshpass', '-e', 'scp', '-o', 'StrictHostKeyChecking=no', '-O',
       '-o', 'ConnectTimeout=8']


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: install-probe-apk-vm.py <tag>')
    apk = Path('/var/tmp/saidroid-next-api29-remote-activity-' + sys.argv[1]) / 'remote-activity.apk'
    assert apk.is_file(), 'build the APK first'
    env = dict(os.environ, SSHPASS=os.environ['SSHPASS'])
    preflight = r"""
import json
from pathlib import Path
pkg='org.example.saildroid.remoteactivity'
assert Path('/home/art/test/.device-lock/owner').is_file(), 'device lock required'
base=Path('/home/art/apps')/pkg
assert not base.is_symlink()
state=Path('/run/user/100000/saildroid')/(pkg+'.json')
if state.exists():assert json.loads(state.read_text()).get('state')=='exited'
if (base/'record.json').exists():
 old=json.loads((base/'record.json').read_text());assert old['package']==pkg and old['data']==str(base/'data')
"""
    subprocess.run(SSH + ['python3 -'], input=preflight.encode(), check=True, env=env, timeout=10)
    subprocess.run(SSH + ['install -d -m0755 ' + BASE + ' ' + BASE + '/lib ' + BASE + '/data'],
                   check=True, env=env, timeout=20)
    subprocess.run(SCP + ['-q', str(apk), 'root@bonito:' + BASE + '/app.apk'],
                   check=True, env=env, timeout=60)
    body = ('SHA=' + repr(hashlib.sha256(apk.read_bytes()).hexdigest()) + '\n'
            'PKG=' + repr(PACKAGE) + '\n' + r'''
import base64, hashlib, json, os, pwd
from pathlib import Path
base = Path('/home/art/apps') / PKG
assert PKG == 'org.example.saildroid.remoteactivity'
state=Path('/run/user/100000/saildroid')/(PKG+'.json')
if state.exists():
 old=json.loads(state.read_text());assert old.get('state')=='exited'
if (base/'record.json').exists():
 old=json.loads((base/'record.json').read_text());assert old['package']==PKG and old['data']==str(base/'data')
apk = base / 'app.apk'
assert hashlib.sha256(apk.read_bytes()).hexdigest() == SHA
account = pwd.getpwnam('defaultuser')
# One valid 1x1 PNG is enough for the record's icon slot.
(base / 'icon.png').write_bytes(base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='))
record = dict(package=PKG, apk=str(apk), native=str(base / 'lib'),
              icon=str(base / 'icon.png'), data=str(base / 'data'))
(base / 'record.json').write_text(json.dumps(record, indent=2) + '\n')
for path in [base, *base.rglob('*')]:
    os.chown(path, account.pw_uid, account.pw_gid)
for path in [base / 'app.apk', base / 'icon.png', base / 'record.json']:
    path.chmod(0o644)
print('REMOTE_ACTIVITY_PROBE_INSTALLED=' + str(base))
''')
    r = subprocess.run(SSH + ['python3 -'], input=body.encode(), capture_output=True,
                       env=env, timeout=30)
    print(r.stdout.decode().strip())
    print(r.stderr.decode().strip()[-800:])
    r.check_returncode()


if __name__ == '__main__':
    main()
