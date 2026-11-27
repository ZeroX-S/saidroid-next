#!/usr/bin/env python3
"""Build an ordinary signed public media snapshot; no CTS result."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, zipfile
p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--multi-codec',action='store_true');a=p.parse_args()
repo=Path(__file__).resolve().parents[4];out=a.output;out.mkdir(exist_ok=False)
java=Path('/tmp/jdkfull/jdk-21.0.13+9/bin');inputs=repo/'build/codex-api29/inputs'
framework=inputs/'android-all-10-robolectric-5803371.jar';tools=Path('/var/tmp/saidroid-next-aapt-tools-20261025-r1/root')
signing=Path('/var/tmp/saidroid-next-private-signing-20261025')
classes=out/'classes';classes.mkdir()
source=Path(__file__).with_name('MultiCodecCapabilitiesInstrumentation.java' if a.multi_codec else 'MediaCapabilitiesInstrumentation.java')
subprocess.run([str(java/'javac'),'--release','8','-nowarn','-cp',str(framework),'-d',str(classes),str(source)],check=True)
subprocess.run([str(java/'java'),'-cp',str(inputs/'r8-8.3.37.jar'),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(out/'dex.jar'),*[str(f)for f in classes.rglob('*.class')]],check=True)
package='org.example.saildroid.mediacapabilities';instrumentation=package+'.'+source.stem;manifest=out/'AndroidManifest.xml';manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="'+package+'"><uses-sdk android:minSdkVersion="29" android:targetSdkVersion="29"/><application android:label="Private public media snapshot" android:debuggable="false"/><instrumentation android:name="'+instrumentation+'" android:targetPackage="'+package+'"/></manifest>')
apk=out/'media-capabilities.apk'
subprocess.run([str(tools/'usr/bin/aapt'),'package','-f','-M',str(manifest),'-I','/home/art/api29-root/system/framework/framework-res.apk','-F',str(apk)],check=True,env=dict(os.environ,LD_LIBRARY_PATH=str(tools/'usr/lib/aarch64-linux-gnu/android')))
with zipfile.ZipFile(apk,'a',zipfile.ZIP_DEFLATED)as z,zipfile.ZipFile(out/'dex.jar')as dex:z.writestr('classes.dex',dex.read('classes.dex'))
subprocess.run([str(java/'jarsigner'),'-keystore',str(signing/'manager.jks'),'-storepass:env','SAILDROID_BUILD_KEY_PASSWORD','-keypass:env','SAILDROID_BUILD_KEY_PASSWORD','-sigalg','SHA256withRSA','-digestalg','SHA-256',str(apk),'saildroid'],env=dict(os.environ,SAILDROID_BUILD_KEY_PASSWORD=(signing/'password').read_text().strip()),check=True,capture_output=True)
record=dict(scope='Internal ordinary signed public codec snapshot; no official CTS acceptance',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),instrumentation=instrumentation,apks=[dict(package=package,file=apk.name,debuggable=False,sha256=hashlib.sha256(apk.read_bytes()).hexdigest())])
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
