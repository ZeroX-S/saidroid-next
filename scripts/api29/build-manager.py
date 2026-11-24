#!/usr/bin/env python3
"""Package and sign the installer Activity for the selected framework API."""
from pathlib import Path
import argparse,os,subprocess,zipfile,secrets,json,hashlib
p=argparse.ArgumentParser();p.add_argument('inputs',type=Path);p.add_argument('product',type=Path);p.add_argument('framework_apk',type=Path);p.add_argument('output',type=Path)
p.add_argument('--api',type=int,choices=(28,29),default=29)
p.add_argument('--aapt-root',type=Path,default=Path('/var/tmp/saidroid-next-aapt-tools-20261025-r1/root'))
p.add_argument('--signing-dir',type=Path,default=Path('/var/tmp/saidroid-next-private-signing-20261025'))
args=p.parse_args();assert not args.output.exists();args.output.mkdir(parents=True)
manifest=f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.saildroid.manager" android:versionCode="2" android:versionName="0.2.0-api{args.api}"><uses-sdk android:minSdkVersion="{args.api}" android:targetSdkVersion="{args.api}"/><application android:label="SailDroid" android:theme="@android:style/Theme.Material.Light.NoActionBar" android:hardwareAccelerated="true" android:allowBackup="false"><activity android:name="org.saildroid.manager.InstallerActivity" android:exported="true" android:screenOrientation="portrait"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>'''
(args.output/'AndroidManifest.xml').write_text(manifest)
tool=args.aapt_root;env=dict(os.environ,LD_LIBRARY_PATH=str(tool/'usr/lib/aarch64-linux-gnu/android'))
subprocess.run([str(tool/'usr/bin/aapt'),'package','-f','-M',str(args.output/'AndroidManifest.xml'),'-I',str(args.framework_apk),'-F',str(args.output/'manager.apk')],env=env,check=True)
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin'
frameworks={28:'android-all-9-robolectric-4913185-2.jar',29:'android-all-10-robolectric-5803371.jar'}
fw=args.inputs/frameworks[args.api]
subprocess.run([str(java/'java'),'-cp',str(args.inputs/'r8-8.3.37.jar'),'com.android.tools.r8.D8','--release','--min-api',str(args.api),'--lib',str(fw),'--output',str(args.output/'manager-dex.jar'),*[str(f)for f in sorted((args.product/'classes/org/saildroid/manager').glob('*.class'))]],check=True)
with zipfile.ZipFile(args.output/'manager.apk','a',zipfile.ZIP_DEFLATED)as target,zipfile.ZipFile(args.output/'manager-dex.jar')as source:
 for name in source.namelist():target.writestr(name,source.read(name))
key_dir=args.signing_dir;key_dir.mkdir(mode=0o700,exist_ok=True)
password_file=key_dir/'password';key=key_dir/'manager.jks'
if not password_file.exists():
 with open(password_file,'x',opener=lambda path,flags:os.open(path,flags,0o600))as output:output.write(secrets.token_hex(24))
env=dict(os.environ,SAILDROID_BUILD_KEY_PASSWORD=password_file.read_text())
if not key.exists():subprocess.run([str(java/'keytool'),'-genkeypair','-alias','saildroid','-keyalg','RSA','-keysize','2048','-validity','3650','-dname','CN=SailDroid component','-storetype','JKS','-keystore',str(key),'-storepass:env','SAILDROID_BUILD_KEY_PASSWORD','-keypass:env','SAILDROID_BUILD_KEY_PASSWORD'],env=env,check=True,capture_output=True)
key.chmod(0o600)
subprocess.run([str(java/'jarsigner'),'-keystore',str(key),'-storepass:env','SAILDROID_BUILD_KEY_PASSWORD','-keypass:env','SAILDROID_BUILD_KEY_PASSWORD','-sigalg','SHA256withRSA','-digestalg','SHA-256',str(args.output/'manager.apk'),'saildroid'],env=env,check=True,capture_output=True)
record=dict(api=args.api,sha256=hashlib.sha256((args.output/'manager.apk').read_bytes()).hexdigest(),product_manifest_sha256=hashlib.sha256((args.product/'manifest.json').read_bytes()).hexdigest())
(args.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('API'+str(args.api)+'_MANAGER=packaged|sha256='+record['sha256'])
