#!/usr/bin/env python3
"""Run the real registry through the real headless ART CLI in a mount namespace."""
from pathlib import Path
import argparse,hashlib,json,os,platform,shutil,subprocess,time,zipfile
p=argparse.ArgumentParser();p.add_argument('--runtime-root',type=Path,required=True);p.add_argument('--payload-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
assert platform.system()=='Linux' and os.geteuid()==0 and 'sailfishos' not in Path('/etc/os-release').read_text().lower()
assert not a.output.exists();a.output.mkdir(parents=True);work=a.output/'work';work.mkdir();homeart=work/'homeart';userhome=work/'home';apps=homeart/'apps';desktop=userhome/'.local/share/applications';services=userhome/'.local/share/dbus-1/services'
for path in [homeart,apps,homeart/'data',userhome,desktop,services]:path.mkdir(parents=True,exist_ok=True)
key=lambda package:'org.saildroid.app.p'+hashlib.sha256(package.encode()).hexdigest()[:20]
records=[]
for package,launch in [('com.example.setup','.Main'),('com.example.nolaunch',None)]:
 folder=apps/package;folder.mkdir();(folder/'data').mkdir();(folder/'data/preserved').write_text('unchanged user data\n')
 record=dict(package=package,label='Setup registry fixture',launchActivity=launch,icon='/home/art/apps/'+package+'/icon.png');(folder/'record.json').write_text(json.dumps(record));records.append(record)
 for path in [desktop/(key(package)+'.desktop'),desktop/('saildroid-'+package+'.desktop'),services/(key(package)+'.service')]:path.write_text('old fixture entry\n')
shutil.copyfile(a.payload_root/'share/packaging/setup-registry.jar',work/'setup-registry.jar')
shutil.copyfile(a.payload_root/'lib/java-cli-bootstrap.jar',work/'java-cli-bootstrap.jar')
for path in [work,*work.rglob('*')]:path.chmod(0o777 if path.is_dir() else 0o666)
root=Path('/opt/saildroid/releases/setup-registry-test')
# Parallels' shared filesystem reports synthetic per-caller ownership. Materialize
# only inside a private tmpfs mount so root immutability checks stay meaningful.
launcher=work/'namespace-launch.py';launcher.write_text("from pathlib import Path\nimport os,shutil,sys\nsource,target=map(Path,sys.argv[1:3])\nshutil.copytree(source,target,symlinks=True)\nshutil.copyfile('/var/tmp/setup-fixture/java-cli-bootstrap.jar',target/'lib/java-cli-bootstrap.jar')\nfor p in [target,*target.rglob('*')]:\n os.lchown(p,0,0)\n if p.is_dir():p.chmod(0o755)\nos.execv('/usr/sbin/runuser',sys.argv[3:])\n");launcher.chmod(0o644)
# Keep the input reachable even when it was built under one of the tmpfs paths.
cmd=['bwrap','--ro-bind','/','/','--tmpfs','/home','--tmpfs','/tmp','--tmpfs','/var/tmp','--tmpfs','/usr/local/lib','--tmpfs','/opt','--dir','/opt/saildroid/releases','--ro-bind',str(a.runtime_root.resolve()),'/var/tmp/runtime-input','--bind',str(work.resolve()),'/var/tmp/setup-fixture','--bind',str(homeart.resolve()),'/home/art','--bind',str(userhome.resolve()),'/home/defaultuser','--dev-bind','/dev','/dev','--proc','/proc','--unshare-net','--unshare-pid','--chdir','/home/defaultuser','--','/usr/bin/python3','/var/tmp/setup-fixture/namespace-launch.py','/var/tmp/runtime-input',str(root),'runuser','-u','nobody','--','env','-i','PATH=/usr/bin:/bin','LC_ALL=C','HOME=/home/defaultuser','USER=nobody','LOGNAME=nobody','ANDROID_DATA=/home/art/data',str(root/'bin/dalvikvm'),'-cp','/var/tmp/setup-fixture/setup-registry.jar:'+str(root/'share/manager.apk'),'org.saildroid.setup.RefreshLaunchers',str(root)]
# Application reflection must not inherit the bridge's boot domain.
probe=work/'RegistryDeniedProbe.java';probe.write_text('public class RegistryDeniedProbe { public static void main(String[] args) throws Exception { Class.forName("org.saildroid.manager.SdAppRegistry").getMethod("validName", String.class); throw new AssertionError("hidden method exposed"); } }')
classes=work/'probe-classes';classes.mkdir();dex=work/'probe-dex';dex.mkdir()
repo=Path(__file__).resolve().parents[2];jdk=Path('/tmp/jdkfull/jdk-21.0.13+9/bin')
subprocess.run([str(jdk/'javac'),'--release','8','-d',str(classes),str(probe)],check=True)
subprocess.run([str(jdk/'java'),'-cp',str(repo/'build/codex-api29/inputs/r8-8.3.37.jar'),'com.android.tools.r8.D8','--release','--min-api','29','--output',str(dex),str(classes/'RegistryDeniedProbe.class')],check=True)
with zipfile.ZipFile(work/'denied.jar','w')as z:z.write(dex/'classes.dex','classes.dex')
(work/'denied.jar').chmod(0o644)
rows=[]
for label,main,arg,expected in [('wrong-root','org.saildroid.setup.RefreshLaunchers','/wrong/root','Selected runtime differs'),('boot-main','org.saildroid.setup.RegistryBridge',str(root),'must belong to the application loader'),('hidden-registry','RegistryDeniedProbe',str(root),'NoSuchMethodException')]:
 negative=list(cmd);negative[-3]+=':/var/tmp/setup-fixture/denied.jar';negative[-2]=main;negative[-1]=arg
 with(a.output/(label+'.log')).open('wb')as stream:q=subprocess.run(negative,stdout=stream,stderr=subprocess.STDOUT,timeout=90)
 text=(a.output/(label+'.log')).read_text(errors='replace');assert q.returncode!=0 and expected in text and 'SAILDROID_SETUP_REGISTRY=ready'not in text,text[-6000:]
 rows.append(dict(label=label,returncode=q.returncode,expected=expected))
for label in ['valid','invalid-record']:
 if label=='invalid-record':
  broken=apps/'com.example.broken';broken.mkdir();broken.chmod(0o777);(broken/'record.json').write_text('{broken');(broken/'record.json').chmod(0o666)
 before={str(x.relative_to(work)):hashlib.sha256(x.read_bytes()).hexdigest()for x in work.rglob('preserved')}
 started=time.monotonic()
 with(a.output/(label+'.log')).open('wb')as stream:q=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,timeout=90)
 text=(a.output/(label+'.log')).read_text(errors='replace');rows.append(dict(label=label,returncode=q.returncode,seconds=time.monotonic()-started))
 if label=='valid':
  assert q.returncode==0 and 'SAILDROID_SETUP_REGISTRY=ready|apps=2|root='+str(root)in text,text[-6000:]
  real=desktop/(key('com.example.setup')+'.desktop');assert real.exists()and'Exec='+str(root)+'/libexec/saildroid-app --package com.example.setup --desktop-token com.example.setup'in real.read_text();snapshot=real.read_bytes()
  assert not(desktop/(key('com.example.nolaunch')+'.desktop')).exists()
  assert not list(desktop.glob('saildroid-*.desktop'))and not list(services.glob('*.service'))
 else:assert q.returncode!=0 and 'SAILDROID_SETUP_REGISTRY=ready'not in text and real.read_bytes()==snapshot,text[-6000:]
 after={str(x.relative_to(work)):hashlib.sha256(x.read_bytes()).hexdigest()for x in work.rglob('preserved')};assert before==after
result=dict(passed=True,scope='Actual packaged ART CLI and SdAppRegistry, ordinary UID65534, isolated home/app store and no network; no phone or GUI.',command=cmd,rows=rows,registry_payload_sha256=hashlib.sha256((work/'setup-registry.jar').read_bytes()).hexdigest(),manager_apk_sha256=hashlib.sha256((a.runtime_root/'share/manager.apk').read_bytes()).hexdigest(),runtime_jar_sha256=hashlib.sha256((a.runtime_root/'lib/runtime.jar').read_bytes()).hexdigest(),desktop=real.read_text())
(a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
