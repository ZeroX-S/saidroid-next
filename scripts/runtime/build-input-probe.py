#!/usr/bin/env python3
"""Build a signed, temporary keyboard regression APK, outside the product."""
from pathlib import Path
import argparse,hashlib,os,subprocess,zipfile,re

p=argparse.ArgumentParser()
p.add_argument('inputs',type=Path)
p.add_argument('framework_apk',type=Path)
p.add_argument('output',type=Path)
p.add_argument('--package',default='org.example.saildroid.inputprobe')
p.add_argument('--label',default='SailDroid input test')
p.add_argument('--remote-service',action='store_true')
a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin'
framework=a.inputs/'android-all-10-robolectric-5803371.jar'
assert re.fullmatch(r'org\.example\.saildroid\.[a-z]+',a.package)
assert re.fullmatch(r'[A-Za-z0-9 ]+',a.label)
sources=[Path(__file__).resolve().parent/'probes'/name for name in ['KeyboardActivity.java','CounterService.java','SecondActivity.java']]
classes=a.output/'classes'
classes.mkdir()
subprocess.run([str(java/'javac'),'--release','8','-cp',str(framework),'-d',str(classes),*[str(source)for source in sources]],check=True)
subprocess.run([str(java/'java'),'-cp',str(a.inputs/'r8-8.3.37.jar'),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(a.output/'probe.jar'),*[str(f)for f in sorted(classes.rglob('*.class'))]],check=True)
manifest='''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.example.saildroid.inputprobe" android:versionCode="1" android:versionName="1"><uses-sdk android:minSdkVersion="29" android:targetSdkVersion="29"/><application android:label="SailDroid input test" android:theme="@android:style/Theme.Material.Light.NoActionBar" android:hardwareAccelerated="false"><activity android:name=".KeyboardActivity" android:exported="true" android:windowSoftInputMode="adjustResize"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>'''
manifest=manifest.replace('package="org.example.saildroid.inputprobe"','package="'+a.package+'"').replace('android:label="SailDroid input test"','android:label="'+a.label+'"').replace('android:name=".KeyboardActivity"','android:name="org.example.saildroid.inputprobe.KeyboardActivity"').replace('</application>','<service android:name="org.example.saildroid.inputprobe.CounterService" android:exported="false"/></application>')
manifest=manifest.replace('</application>','<activity android:name="org.example.saildroid.inputprobe.SecondActivity" android:exported="false"/></application>')
if a.remote_service:manifest=manifest.replace('android:name="org.example.saildroid.inputprobe.CounterService"','android:name="org.example.saildroid.inputprobe.CounterService" android:process=":worker"')
(a.output/'AndroidManifest.xml').write_text(manifest)
tool=Path('/var/tmp/saidroid-next-aapt-tools-20261025-r1/root')
env=dict(os.environ,LD_LIBRARY_PATH=str(tool/'usr/lib/aarch64-linux-gnu/android'))
apk=a.output/'input-probe.apk'
subprocess.run([str(tool/'usr/bin/aapt'),'package','-f','-M',str(a.output/'AndroidManifest.xml'),'-I',str(a.framework_apk),'-F',str(apk)],env=env,check=True)
with zipfile.ZipFile(apk,'a',zipfile.ZIP_DEFLATED)as target,zipfile.ZipFile(a.output/'probe.jar')as dex:
    target.writestr('classes.dex',dex.read('classes.dex'))
private=Path('/var/tmp/saidroid-next-private-signing-20261025')
env=dict(os.environ,SAILDROID_BUILD_KEY_PASSWORD=(private/'password').read_text())
subprocess.run([str(java/'jarsigner'),'-keystore',str(private/'manager.jks'),'-storepass:env','SAILDROID_BUILD_KEY_PASSWORD','-keypass:env','SAILDROID_BUILD_KEY_PASSWORD','-sigalg','SHA256withRSA','-digestalg','SHA-256',str(apk),'saildroid'],env=env,check=True,capture_output=True)
print('API29_INPUT_APK=compiled|sha256='+hashlib.sha256(apk.read_bytes()).hexdigest())
