#!/usr/bin/env python3
"""Execute a prepared official module plan in the phone-owning build VM."""
from pathlib import Path
import argparse,json,subprocess,os
p=argparse.ArgumentParser();p.add_argument('plan',type=Path);p.add_argument('--stage-bundle',type=Path);a=p.parse_args();config=json.loads(a.plan.read_text());repo=Path('/media/psf/Home/WorkSpace/saidroid-next');out=a.plan.parent;os.environ['SSHPASS']=os.environ['SSHPASS'];mux=['-o','ControlMaster=auto','-o','ControlPersist=45','-o','ControlPath=/var/tmp/saidroid-cts-transport-%C'];ssh=['sshpass','-e','ssh',*mux,'-o','ConnectTimeout=6','root@bonito'];scp=['sshpass','-e','scp','-O',*mux];lock=repo/'scripts/devlock.sh';base='/home/art/test/'+config['label']
preflight='from pathlib import Path;assert "ID=sailfishos" in Path("/etc/sailfish-release").read_text();expected='+repr(config.get('expected_boot'))+';assert not expected or Path("/proc/sys/kernel/random/boot_id").read_text().strip()==expected,"Suite boot identity changed before device preparation"'
from apk_manifest import parse
from instrumentation_policy import verify_original_hidden_api_override
assert type(config.get('hidden_api_checks',True))is bool,'Invalid instrumentation hidden API option'
policy=verify_original_hidden_api_override(config,out)
if policy is not None:(out/'effective-official-policy.json').write_text(json.dumps(policy,indent=2)+'\n')
if config.get('directory_preparation'):
 import xml.etree.ElementTree as ET,hashlib
 from temporary_directory_preparer import directory_spec
 assert policy is not None,'Original Libcore configuration policy is required for this preparer'
 original=out/('original-hidden-api-policy-'+Path(policy['config_source']).name)
 assert hashlib.sha256(original.read_bytes()).hexdigest()==policy['config_sha256']
 preparers=[dict(**{'class':element.get('class')},options=[dict(option.attrib)for option in element.findall('option')])for element in ET.fromstring(original.read_bytes()).findall('target_preparer')]
 assert directory_spec(preparers)==config['directory_preparation'],'Directory preparation differs from original configuration'
verified_apks=[]
for item in config['apks']:
 metadata=parse(out/item['file']);assert metadata['package']==item['package']
 declared=metadata['application'].get('debuggable',False);assert type(declared)is bool
 if 'debuggable'in item:assert item['debuggable']==declared,'Prepared APK debuggable flag differs from original manifest'
 item['debuggable']=declared;verified_apks.append(dict(package=item['package'],debuggable=declared,apk_sha256=item['sha256']))
(out/'effective-apk-metadata.json').write_text(json.dumps(verified_apks,indent=2)+'\n')
subprocess.run(['bash',str(lock),'acquire','0','cts-module-run'],check=True,timeout=15)
transport=None;transport_output=None;transport_path=out/('transport-'+config['label'])
try:
 subprocess.run(ssh+['python3','-'],input=preflight.encode(),check=True,timeout=12)
 if config.get('network_proxy',{}).get('transport')=='ssh-vm-loopback':
  import time,signal
  proxy=config['network_proxy'];assert proxy['type']=='socks5'and proxy['host']=='127.0.0.1'and type(proxy['port'])is int and 1024<=proxy['port']<=65535
  transport_output=(out/('transport-'+config['label']+'.log')).open('w')
  transport=subprocess.Popen(['python3',str(repo/'scripts/cts/socks-relay-vm.py'),str(transport_path),'--expected-boot',config['expected_boot'],'--port',str(proxy['port']),'--seconds',str(min(config['timeout']+240,3600))],stdout=transport_output,stderr=subprocess.STDOUT,start_new_session=True)
  until=time.monotonic()+25
  while time.monotonic()<until and not(transport_path/'ready.json').is_file():
   assert transport.poll()is None,'Recorded VM network relay failed to start'
   time.sleep(.2)
  assert(transport_path/'ready.json').is_file(),'Recorded VM network relay readiness deadline'
 subprocess.run(['python3',str(repo/'scripts/perf/close-owned-vm.py')],check=True,timeout=50)
 if a.stage_bundle:subprocess.run(['python3',str(repo/'scripts/runtime/deploy-native-overlay-v3.py'),str(a.stage_bundle),Path(config['root']).name.removeprefix('api29-'),'--expected-active','/home/art/releases/api29-r112-native-candidate'],check=True,timeout=160)
 subprocess.run(ssh+['test ! -e '+base+' && install -d -m0700 '+base],check=True,timeout=12)
 for apk in config['apks']+config.get('dynamic_configs',[])+config.get('pushed_files',[]):subprocess.run(scp+[str(out/apk['file']),'root@bonito:'+base+'/'+apk['file']],check=True,timeout=max(90,45+(out/apk['file']).stat().st_size//(4*1024*1024)))
 support=(repo/'scripts/cts/temporary_directory_preparer.py').read_text()if config.get('directory_preparation')else''
 display_support=(repo/'scripts/cts/display_cleanup.py').read_text()
 body='CONFIG='+repr(config)+'\n'+support+'\n'+display_support+'\n'+(repo/'scripts/cts/run-instrument-phone.py').read_text()
 r=subprocess.run(ssh+['python3','-'],input=body.encode(),timeout=config['timeout']+110)
 subprocess.run(scp+['-r','root@bonito:'+base,str(out)],check=True,timeout=45)
 r.check_returncode()
 # All phone logs were transferred. Keep one authoritative local copy and no
 # duplicate APK/test tree on the phone.
 subprocess.run(ssh+['rm','-rf',base],check=True,timeout=10)
finally:
 transport_safe=True
 if transport is not None:
  import signal
  if transport_path.is_dir():(transport_path/'STOP').write_text('Original instrumentation transaction completed.\n')
  try:transport.wait(timeout=20)
  except subprocess.TimeoutExpired:
   transport_safe=False;os.killpg(transport.pid,signal.SIGTERM)
   try:transport.wait(timeout=3)
   except subprocess.TimeoutExpired:os.killpg(transport.pid,signal.SIGKILL);transport.wait(timeout=3)
  if transport.returncode:transport_safe=False
 if transport_output:transport_output.close()
 try:identity=subprocess.run(ssh+['python3','-'],input=preflight.encode(),capture_output=True,timeout=12).returncode==0
 except subprocess.TimeoutExpired:identity=False
 if identity:
  subprocess.run(['python3',str(repo/'scripts/perf/close-owned-vm.py')],timeout=50)
  subprocess.run(ssh+['mcetool','--set-never-blank=disabled','--blank-screen'],timeout=6)
 else:print('CLEANUP_DEFERRED=device-identity-not-confirmed; serial dispatcher must stop',flush=True)
 subprocess.run(['bash',str(lock),'release','cts-module-run'],check=True,timeout=15)
 assert transport_safe,'VM relay cleanup/identity contract failed'
