#!/usr/bin/env python3
"""Build the temporary signed integration-matrix probe APK (outside the product).

The probe is only a test fixture: it contains no SailDroid product code. It is
installed through the real SailDroid installer and removed again afterwards.
"""
from pathlib import Path
import argparse
import hashlib
import os
import re
import subprocess
import zipfile

PACKAGE = 'org.example.saildroid.matrixprobe'

parser = argparse.ArgumentParser()
parser.add_argument('inputs', type=Path)
parser.add_argument('framework_apk', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--label', default='Matrix probe')
args = parser.parse_args()

args.output.mkdir(parents=True, exist_ok=False)
java = Path(os.environ.get('JAVA_HOME', '/tmp/jdkfull/jdk-21.0.13+9')) / 'bin'
framework = args.inputs / 'android-all-10-robolectric-5803371.jar'
assert framework.is_file(), framework
assert re.fullmatch(r'[A-Za-z0-9 ]+', args.label)

sources = [Path(__file__).resolve().parent / 'probes' / name for name in
           ['MatrixActivity.java', 'SecondMatrixActivity.java', 'ToolMatrixActivity.java']]
classes = args.output / 'classes'
classes.mkdir()
subprocess.run([str(java / 'javac'), '--release', '8', '-cp', str(framework),
                '-d', str(classes)] + [str(source) for source in sources], check=True)

d8_output = args.output / 'probe.jar'
subprocess.run([str(java / 'java'), '-cp', str(args.inputs / 'r8-8.3.37.jar'),
                'com.android.tools.r8.D8', '--release', '--min-api', '29',
                '--lib', str(framework), '--output', str(d8_output)]
               + [str(f) for f in sorted(classes.rglob('*.class'))], check=True)

manifest = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="%s" android:versionCode="1" android:versionName="1">
  <uses-sdk android:minSdkVersion="29" android:targetSdkVersion="29"/>
  <application android:label="%s" android:theme="@android:style/Theme.Material.Light.NoActionBar" android:hardwareAccelerated="false">
    <activity android:name="org.example.saildroid.matrixprobe.MatrixActivity" android:exported="true">
      <intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>
    </activity>
    <activity android:name="org.example.saildroid.matrixprobe.SecondMatrixActivity" android:exported="false"/>
    <activity android:name="org.example.saildroid.matrixprobe.ToolMatrixActivity"
              android:exported="false" android:process="org.example.saildroid.matrixprobe:tool"/>
  </application>
</manifest>
''' % (PACKAGE, args.label)
(args.output / 'AndroidManifest.xml').write_text(manifest)

tool = Path('/var/tmp/saidroid-next-aapt-tools-20261025-r1/root')
env = dict(os.environ, LD_LIBRARY_PATH=str(tool / 'usr/lib/aarch64-linux-gnu/android'))
apk = args.output / 'matrix-probe.apk'
subprocess.run([str(tool / 'usr/bin/aapt'), 'package', '-f',
                '-M', str(args.output / 'AndroidManifest.xml'),
                '-I', str(args.framework_apk), '-F', str(apk)], env=env, check=True)
with zipfile.ZipFile(apk, 'a', zipfile.ZIP_DEFLATED) as target, zipfile.ZipFile(d8_output) as dex:
    target.writestr('classes.dex', dex.read('classes.dex'))

private = Path('/var/tmp/saidroid-next-private-signing-20261025')
env = dict(os.environ, SAILDROID_BUILD_KEY_PASSWORD=(private / 'password').read_text())
subprocess.run([str(java / 'jarsigner'), '-keystore', str(private / 'manager.jks'),
                '-storepass:env', 'SAILDROID_BUILD_KEY_PASSWORD',
                '-keypass:env', 'SAILDROID_BUILD_KEY_PASSWORD',
                '-sigalg', 'SHA256withRSA', '-digestalg', 'SHA-256',
                str(apk), 'saildroid'], env=env, check=True, capture_output=True)
print('MATRIX_APK=compiled|package=%s|sha256=%s|path=%s'
      % (PACKAGE, hashlib.sha256(apk.read_bytes()).hexdigest(), apk))
