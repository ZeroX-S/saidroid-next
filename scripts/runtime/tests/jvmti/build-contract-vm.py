#!/usr/bin/env python3
"""Build two signed internal JVMTI contracts; neither counts as official CTS."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, zipfile
p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args()
repo=Path(__file__).resolve().parents[4];out=a.output;out.mkdir(exist_ok=False)
java=Path('/tmp/jdkfull/jdk-21.0.13+9/bin');inputs=repo/'build/codex-api29/inputs'
framework=inputs/'android-all-10-robolectric-5803371.jar';tools=Path('/var/tmp/saidroid-next-aapt-tools-20261025-r1/root')
signing=Path('/var/tmp/saidroid-next-private-signing-20261025');source=Path(__file__).with_name('JvmtiContractInstrumentation.java')
agent_source=repo/'native/compat/tests/jvmti-agent-contract.c';classes=out/'classes';classes.mkdir()
subprocess.run(['gcc','-shared','-fPIC','-nostdlib','-O2','-Wall','-Wextra','-Werror','-Wl,--hash-style=both','-I'+str(repo/'third_party/art-standalone/libnativehelper/include/nativehelper'),'-I'+str(repo/'third_party/art-standalone/art/openjdkjvmti/include'),str(agent_source),'-o',str(out/'libcontractagent.so')],check=True)
subprocess.run([str(java/'javac'),'--release','8','-nowarn','-cp',str(framework),'-d',str(classes),str(source)],check=True)
subprocess.run([str(java/'java'),'-cp',str(inputs/'r8-8.3.37.jar'),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(framework),'--output',str(out/'dex.jar'),*[str(f)for f in classes.rglob('*.class')]],check=True)
records=[]
for debug in (False,True):
 suffix='debug' if debug else 'plain';package='org.example.saildroid.jvmticontract.'+suffix
 manifest_dir=out/suffix;manifest_dir.mkdir();manifest=manifest_dir/'AndroidManifest.xml';manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="'+package+'"><uses-sdk android:minSdkVersion="29" android:targetSdkVersion="29"/><application android:label="Private JVMTI contract" android:debuggable="'+str(debug).lower()+'" android:extractNativeLibs="true"/><instrumentation android:name="org.example.saildroid.jvmticontract.JvmtiContractInstrumentation" android:targetPackage="'+package+'"/></manifest>')
 apk=out/('jvmti-'+suffix+'.apk')
 subprocess.run([str(tools/'usr/bin/aapt'),'package','-f','-M',str(manifest),'-I','/home/art/api29-root/system/framework/framework-res.apk','-F',str(apk)],check=True,env=dict(os.environ,LD_LIBRARY_PATH=str(tools/'usr/lib/aarch64-linux-gnu/android')))
 with zipfile.ZipFile(apk,'a',zipfile.ZIP_DEFLATED)as z,zipfile.ZipFile(out/'dex.jar')as dex:
  z.writestr('classes.dex',dex.read('classes.dex'));z.writestr('lib/arm64-v8a/libcontractagent.so',(out/'libcontractagent.so').read_bytes())
 subprocess.run([str(java/'jarsigner'),'-keystore',str(signing/'manager.jks'),'-storepass:env','SAILDROID_BUILD_KEY_PASSWORD','-keypass:env','SAILDROID_BUILD_KEY_PASSWORD','-sigalg','SHA256withRSA','-digestalg','SHA-256',str(apk),'saildroid'],env=dict(os.environ,SAILDROID_BUILD_KEY_PASSWORD=(signing/'password').read_text().strip()),check=True,capture_output=True)
 records.append(dict(package=package,file=apk.name,debuggable=debug,sha256=hashlib.sha256(apk.read_bytes()).hexdigest()))
record=dict(scope='Internal signed debugging boundary and actual JVMTI operations, not official CTS',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),agent_source_sha256=hashlib.sha256(agent_source.read_bytes()).hexdigest(),apks=records)
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
