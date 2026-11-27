#!/usr/bin/env python3
"""Build the temporary signed Activity remote Activity regression APK inside the build VM.
Use a tag ending in -software to test an APK's explicit renderer opt-out.
"""
from pathlib import Path
import hashlib, os, subprocess, sys, zipfile

REPO = Path('/media/psf/Home/WorkSpace/saidroid-next')
INPUTS = REPO / 'build/codex-api29/inputs'
FRAMEWORK_JAR = INPUTS / 'android-all-10-robolectric-5803371.jar'
R8 = INPUTS / 'r8-8.3.37.jar'
JAVA = Path(os.environ.get('JAVA_HOME', '/tmp/jdkfull/jdk-21.0.13+9')) / 'bin'
AAPT_TOOL = Path('/var/tmp/saidroid-next-aapt-tools-20261025-r1/root')
SIGNING = Path('/var/tmp/saidroid-next-private-signing-20261025')
FRAMEWORK_APK = Path('/home/art/api29-root/system/framework/framework-res.apk')
PACKAGE = 'org.example.saildroid.remoteactivity'
ACTIVITY = 'ParentActivity'


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: build-apk-vm.py <tag>')
    tag = sys.argv[1]
    software = tag.endswith('-software')
    out = Path('/var/tmp/saidroid-next-api29-remote-activity-' + tag)
    assert str(out).startswith('/var/tmp/saidroid-next-'), 'keep outputs under /var/tmp'
    out.mkdir(parents=True, exist_ok=False)
    classes = out / 'classes'
    classes.mkdir()
    sources=sorted((REPO/'scripts/runtime/tests/remote-activity').glob('*.java'))
    subprocess.run([str(JAVA / 'javac'), '--release', '8', '-nowarn', '-cp', str(FRAMEWORK_JAR),
                    '-d', str(classes), *[str(source)for source in sources]], check=True)
    subprocess.run([str(JAVA / 'java'), '-cp', str(R8), 'com.android.tools.r8.D8', '--release',
                    '--min-api', '29', '--lib', str(FRAMEWORK_JAR),
                    '--output', str(out / 'dex.jar'),
                    *[str(f) for f in sorted(classes.rglob('*.class'))]], check=True)
    manifest = (
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
        'package="' + PACKAGE + '" android:versionCode="1" android:versionName="1">'
        '<uses-permission android:name="android.permission.INTERNET"/><uses-sdk android:minSdkVersion="29" android:targetSdkVersion="29"/>'
        '<application android:label="SailDroid remote Activity regression" '
        'android:theme="@android:style/Theme.Material.Light.NoActionBar" '
        'android:hardwareAccelerated="true">'
        '<activity android:name="' + PACKAGE + '.' + ACTIVITY + '" android:exported="true" '
        'android:configChanges="orientation|screenSize|keyboardHidden">'
        '<intent-filter><action android:name="android.intent.action.MAIN"/>'
        '<category android:name="android.intent.category.LAUNCHER"/></intent-filter>'
        '</activity><activity android:name="org.example.saildroid.remoteactivity.ChildActivity" android:process=":tool" android:exported="false"/>'
        '<provider android:name="org.example.saildroid.remoteactivity.SharedProvider" android:authorities="org.example.saildroid.remoteactivity.shared" android:exported="false"/>'
        '<provider android:name="org.example.saildroid.remoteactivity.DataProvider" android:authorities="org.example.saildroid.remoteactivity.store" android:process=":store" android:exported="false"/></application></manifest>')
    if software:manifest=manifest.replace('hardwareAccelerated="true"','hardwareAccelerated="false"')
    (out / 'AndroidManifest.xml').write_text(manifest)
    env = dict(os.environ, LD_LIBRARY_PATH=str(AAPT_TOOL / 'usr/lib/aarch64-linux-gnu/android'))
    apk = out / 'remote-activity.apk'
    subprocess.run([str(AAPT_TOOL / 'usr/bin/aapt'), 'package', '-f',
                    '-M', str(out / 'AndroidManifest.xml'), '-I', str(FRAMEWORK_APK),
                    '-F', str(apk)], env=env, check=True)
    with zipfile.ZipFile(apk, 'a', zipfile.ZIP_DEFLATED) as target, \
            zipfile.ZipFile(out / 'dex.jar') as dex:
        target.writestr('classes.dex', dex.read('classes.dex'))
    env = dict(os.environ, SAILDROID_BUILD_KEY_PASSWORD=(SIGNING / 'password').read_text().strip())
    subprocess.run([str(JAVA / 'jarsigner'), '-keystore', str(SIGNING / 'manager.jks'),
                    '-storepass:env', 'SAILDROID_BUILD_KEY_PASSWORD',
                    '-keypass:env', 'SAILDROID_BUILD_KEY_PASSWORD',
                    '-sigalg', 'SHA256withRSA', '-digestalg', 'SHA-256',
                    str(apk), 'saildroid'], env=env, check=True, capture_output=True)
    print('REMOTE_ACTIVITY_PROBE_APK=' + str(apk))
    print('SHA256=' + hashlib.sha256(apk.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
