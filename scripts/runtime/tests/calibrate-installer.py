#!/usr/bin/env python3
"""Small device-side helper to calibrate the installer dialog and the drawer.

The integration matrix needs four pixel coordinates that depend on the phone
theme/locale and cannot be derived from the source: the installer "安装"
button, the catalog "卸载" button of the matrix-probe row, its confirmation
button, and the drawer icon positions. This helper takes a screenshot after
each step so the coordinates can be read off the image, and prints the
relevant runtime markers so a wrong tap is visible immediately.

Runs on the phone as root (app operations as the phone user).

Examples
  python3 calibrate-installer.py --install /home/defaultuser/Downloads/SailDroid-APKs/MatrixProbe.apk --shot cal-install-dialog
  python3 calibrate-installer.py --tap 730,1250 --shot cal-installing --wait-marker 'INSTALLER=installed|package=org.example.saildroid.matrixprobe' --wait 90
  python3 calibrate-installer.py --shot cal-catalog
  python3 calibrate-installer.py --tap 700,600 --shot cal-uninstall-dialog
  python3 calibrate-installer.py --tap 760,1250 --shot cal-uninstalled --wait-marker 'INSTALLER=uninstalled|package=org.example.saildroid.matrixprobe' --wait 60
  python3 calibrate-installer.py --drawer --shot cal-drawer
  python3 calibrate-installer.py --status
"""
import argparse
import json
import os
import pwd
import re
import subprocess
import sys
import time
from pathlib import Path

MANAGER = 'org.saildroid.manager'
PROBE = 'org.example.saildroid.matrixprobe'
RUNTIME = Path('/run/user/100000/saildroid')
OPEN = '/home/art/bin/saildroid-open'
TOUCH = '/home/art/test/delivery-touch-tool-r3/inject-touch'
SHOTS = Path('/home/defaultuser/Downloads/SailDroid-Screenshots')
DRAWER_SWIPE = ['--swipe', '540', '2159', '540', '950', '400']

USER = pwd.getpwnam('defaultuser')
ENV = dict(os.environ, HOME=USER.pw_dir, USER=USER.pw_name, LOGNAME=USER.pw_name,
           XDG_RUNTIME_DIR='/run/user/100000',
           DBUS_SESSION_BUS_ADDRESS='unix:path=/run/user/100000/dbus/user_bus_socket')


def run(command, timeout=30, as_user=False, check=True):
    kwargs = dict(capture_output=True, text=True, timeout=timeout, env=ENV)
    if as_user:
        kwargs.update(user=USER.pw_uid, group=USER.pw_gid,
                      extra_groups=os.getgrouplist(USER.pw_name, USER.pw_gid))
    result = subprocess.run(command, **kwargs)
    if check and result.returncode != 0:
        raise SystemExit('command failed: %s\n%s%s'
                         % (' '.join(command), result.stdout, result.stderr))
    return result


def state(package):
    try:
        return json.loads((RUNTIME / (package + '.json')).read_text())
    except (OSError, ValueError):
        return {}


def top():
    out = run(['gdbus', 'call', '--session', '--dest', 'org.nemomobile.lipstick',
               '--object-path', '/',
               '--method', 'org.nemomobile.compositor.privateTopmostWindowProcessId'],
              timeout=5).stdout
    match = re.match(r'\((\d+),\)', out.strip())
    return int(match.group(1)) if match else -1


def manager_ready():
    if not state(MANAGER):
        with open('/home/art/test/calibrate-manager.stdout', 'ab') as output:
            subprocess.Popen([OPEN, '--manager'], stdin=subprocess.DEVNULL,
                             stdout=output, stderr=subprocess.STDOUT, env=ENV,
                             start_new_session=True, user=USER.pw_uid, group=USER.pw_gid,
                             extra_groups=os.getgrouplist(USER.pw_name, USER.pw_gid))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not state(MANAGER):
            time.sleep(0.2)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        text = Path(state(MANAGER).get('log', '')).read_text(errors='replace') \
            if state(MANAGER).get('log') else ''
        if 'SDWINDOW_SESSION=drawn' in text:
            break
        time.sleep(0.2)
    run([OPEN, '--manager'], as_user=True, timeout=20)
    return state(MANAGER)


def screenshot(name):
    target = SHOTS / (name + '.png')
    if target.exists():
        target.unlink()
    run(['gdbus', 'call', '--session', '--dest', 'org.nemomobile.lipstick',
         '--object-path', '/org/nemomobile/lipstick/screenshot',
         '--method', 'org.nemomobile.lipstick.saveScreenshot', str(target)], timeout=10)
    size = -1
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if target.exists():
            current = target.stat().st_size
            if current > 0 and current == size:
                print('SHOT=%s|bytes=%d' % (target, current))
                return target
            size = current
        time.sleep(0.2)
    raise SystemExit('screenshot did not settle')


def status():
    info = state(MANAGER)
    print('MANAGER=%s|topmost=%d' % (json.dumps({k: info.get(k) for k in
                                                 ('pid', 'state', 'log')}), top()))
    probe_installed = Path('/home/art/apps', PROBE).exists()
    print('PROBE_INSTALLED=%s' % probe_installed)
    text = Path(info['log']).read_text(errors='replace') if info.get('log') else ''
    for line in [line for line in text.splitlines() if line.startswith('INSTALLER=')][-6:]:
        print('MARKER=%s' % line)
    for line in [line for line in text.splitlines()
                 if line.startswith(('SDRUNTIME=failed', 'SDLAUNCHER=exited'))][-3:]:
        print('MARKER=%s' % line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', default='')
    parser.add_argument('--tap', default='')
    parser.add_argument('--swipe', default='')
    parser.add_argument('--drawer', action='store_true')
    parser.add_argument('--shot', default='')
    parser.add_argument('--wait-marker', default='')
    parser.add_argument('--wait', type=float, default=0)
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()

    if os.getuid() != 0:
        raise SystemExit('run as root')

    if args.install:
        manager_ready()
        result = run([OPEN, '--manager', '--install', args.install], as_user=True, timeout=30)
        print('INSTALL_REQUEST=%s' % result.returncode)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            text = Path(state(MANAGER).get('log', '')).read_text(errors='replace')
            if 'INSTALLER=confirm|file=' in text:
                print('CONFIRM_DIALOG=shown')
                break
            time.sleep(0.2)
        else:
            print('CONFIRM_DIALOG=missing')

    if args.drawer:
        run([TOUCH] + DRAWER_SWIPE, timeout=8)
        time.sleep(1.3)

    if args.tap:
        x, y = args.tap.split(',')
        run([TOUCH, x.strip(), y.strip()], timeout=8)
        time.sleep(1.0)
        print('TAPPED=%s,%s|topmost=%d' % (x.strip(), y.strip(), top()))

    if args.swipe:
        parts = [part.strip() for part in args.swipe.split(',')]
        run([TOUCH, '--swipe'] + parts, timeout=8)
        time.sleep(1.0)
        print('SWIPED=%s|topmost=%d' % (args.swipe, top()))

    if args.shot:
        screenshot(args.shot)

    if args.wait_marker:
        deadline = time.monotonic() + (args.wait or 60)
        while time.monotonic() < deadline:
            text = Path(state(MANAGER).get('log', '')).read_text(errors='replace')
            if args.wait_marker in text:
                print('MARKER_FOUND=%s' % args.wait_marker)
                break
            time.sleep(0.3)
        else:
            print('MARKER_MISSING=%s' % args.wait_marker)

    status()
    return 0


if __name__ == '__main__':
    sys.exit(main())
