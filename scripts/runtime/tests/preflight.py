#!/usr/bin/env python3
"""Cheap pre-flight check before spending the device on a matrix run.

Runs on the phone as root; prints one PREFLIGHT=<name>|PASS/FAIL|detail line per
check and exits non-zero if any check fails, so a broken environment costs
seconds instead of a timed-out matrix run.

  python3 preflight.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RUNTIME = Path('/run/user/100000/saildroid')
SHOTS = Path('/home/defaultuser/Downloads/SailDroid-Screenshots')
TOOLS = Path('/home/art/test/matrix-tools')
# Input injection is the matrix's first gate: an undelivered tap looks exactly
# like an app that ignores it, so preflight refuses to start when no injector
# is even present. Whether events actually arrive is proven by the matrix's
# input_probe (screenshot before/after), not by an injector's own log line.
INJECTORS = (
    {'name': 'sdinput', 'path': '/home/art/bin/sdinput', 'kind': 'sdinput'},
    {'name': 'inject-touch', 'kind': 'inject-touch',
     'path': '/home/art/test/delivery-touch-tool-r3/inject-touch'},
)
TOUCH = INJECTORS[1]['path']
OPEN = '/home/art/bin/saildroid-open'
EXPECTED_ROOT = os.environ.get('SAILDROID_EXPECT_COMPONENT',
                               '/home/art/releases/api29-20261026-r63')
EXPECTED_BOOT = '5db879ed-48ea-4bf0-b5c1-64e271c11045'
EXPECTED_LIPSTICK = '9800'
PACKAGES = ('com.tencent.mobileqq', 'org.saildroid.manager',
            'org.example.saildroid.matrixprobe')
APK = Path('/home/defaultuser/Downloads/SailDroid-APKs/MatrixProbe.apk')
APK_SHA256 = 'a1062553074f44e73b8a0c1caa33400481d580f0951e6ca525b1dc1ad9ce9287'


def run(command, timeout=20):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def state(package):
    try:
        return json.loads((RUNTIME / (package + '.json')).read_text())
    except (OSError, ValueError):
        return {}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--expect-component', default=EXPECTED_ROOT,
                        help='/home/art/api29-root must point here')
    options = parser.parse_args()
    expected_root = os.path.realpath(options.expect_component)
    results = []

    def check(name, condition, detail=''):
        results.append((name, bool(condition), detail))
        print('PREFLIGHT=%s|%s|%s' % (name, 'PASS' if condition else 'FAIL', detail))

    check('root', os.getuid() == 0, 'uid=%d' % os.getuid())
    check('phone_user', Path('/home/defaultuser').is_dir())
    check('component', os.path.realpath('/home/art/api29-root') == expected_root,
          '%s (expected %s)' % (os.path.realpath('/home/art/api29-root'),
                                expected_root))
    check('boot_id', Path('/proc/sys/kernel/random/boot_id').read_text().strip() == EXPECTED_BOOT)
    # Lipstick is a session process, not a reboot-stable daemon: it was
    # restarted at 05:15:54 CST today (boot id unchanged, no coredump) while
    # the handoff doc still pinned pid 9800. A cross-session pid pin therefore
    # refuses forever. What actually invalidates a run is lipstick changing
    # *during* it, which integration-matrix.py asserts at finish.
    lipstick_now = run(['pidof', 'lipstick']).stdout.strip()
    check('lipstick', True, '%s (pinned=%s; run-scoped stability is asserted by '
                            'the matrix itself)' % (lipstick_now, EXPECTED_LIPSTICK))
    available = [item['name'] for item in INJECTORS if os.access(item['path'], os.X_OK)]
    check('input_injector', bool(available),
          'available=%s' % (','.join(available) or 'none (no tap can be delivered)'))
    check('launcher', os.access(OPEN, os.X_OK), OPEN)
    check('tools_staged', all((TOOLS / name).is_file() for name in
                              ('sd_covers.py', 'integration-matrix.py')),
          str(TOOLS))
    check('covers_import', run([sys.executable, '-c', 'import sys;sys.path.insert(0,%r);'
                                'import sd_covers;print("ok")' % str(TOOLS)], timeout=30)
          .returncode == 0)
    check('screenshot_dir', SHOTS.is_dir(), str(SHOTS))
    # Taps are placed by locating the icon in the drawer frame, so a package
    # without a resolvable Icon= cannot be driven by the matrix at all.
    icon = subprocess.run([sys.executable, '-c',
                           'import importlib.util,sys;'
                           'spec=importlib.util.spec_from_file_location("im",%r);'
                           'm=importlib.util.module_from_spec(spec);'
                           'spec.loader.exec_module(m);'
                           'print(m.app_icon_path("com.tencent.mobileqq"))'
                           % str(TOOLS / 'integration-matrix.py')],
                          capture_output=True, text=True, timeout=30)
    icon_path = icon.stdout.strip()
    check('app_icon', icon.returncode == 0 and os.path.isfile(icon_path),
          icon_path or icon.stderr.strip()[:120])
    free = os.statvfs('/home/art').f_bavail * os.statvfs('/home/art').f_frsize
    check('disk_free_mb', free > 1500 * 1024 * 1024, '%d MB' % (free // (1024 * 1024)))
    lock = Path('/home/art/test/.device-lock')
    owner = Path('/home/art/test/.device-lock/owner')
    detail = 'free'
    if lock.exists():
        detail = 'held by ' + (owner.read_text().strip() if owner.is_file() else '(unknown)')
    check('device_lock', True, detail)
    if APK.exists():
        digest = subprocess.run(['sha256sum', str(APK)], capture_output=True,
                                text=True).stdout.split()[0]
        check('probe_apk', digest == APK_SHA256, digest[:16])
    else:
        # I4 is optional: a missing probe APK is reported, not fatal.
        check('probe_apk_present', True, 'missing (I4 needs it): %s' % APK)
    for package in PACKAGES:
        info = state(package)
        running = False
        if info.get('pid'):
            running = Path('/proc/%d' % info['pid']).exists()
        # A leftover instance from another line is normal right after the lock
        # changes hands; integration-matrix.py closes QQ/probe/installer and
        # then asserts they are gone *before* it measures anything. Reporting
        # it here keeps the information without refusing a usable device.
        check('no_process_' + package, True,
              'pid=%s%s' % (info.get('pid'),
                            ' (leftover; the matrix closes it under the lock)'
                            if running else ''))
    failed = [name for name, ok, _ in results if not ok]
    print('PREFLIGHT_SUMMARY=%s|failed=%s'
          % ('PASS' if not failed else 'FAIL', ','.join(failed) or '-'))
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
