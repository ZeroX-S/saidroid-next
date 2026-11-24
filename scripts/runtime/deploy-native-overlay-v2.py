#!/usr/bin/env python3
"""Stage/activate a verified v2 overlay with duplicate-CA cleanup in a new root.
Run in the phone-owning VM while holding scripts/devlock.sh. Activation is
explicit; staging alone leaves the current desktop/runtime entry unchanged.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,time
p=argparse.ArgumentParser();p.add_argument('bundle',type=Path);p.add_argument('run');p.add_argument('--activate',action='store_true');p.add_argument('--activate-existing',action='store_true',help='Verify and activate this exact previously staged release');p.add_argument('--expected-active');a=p.parse_args();assert re.fullmatch('[a-z0-9-]+',a.run)
archive=a.bundle/'native-overlay.tar.gz';record=json.loads((a.bundle/'overlay.json').read_text());assert record['schema']=='saildroid-native-overlay-v2'
ssh=['ssh','-o','ConnectTimeout=8','root@bonito'];scp=['scp','-O','-o','ConnectTimeout=8']
if os.environ.get('SSHPASS'):ssh=['sshpass','-e']+ssh;scp=['sshpass','-e']+scp
stage='/home/art/test/native-overlay-'+a.run+('-activation-'+str(time.time_ns())if a.activate_existing else'')
subprocess.run(ssh+['test ! -e '+stage+' && install -d -m0700 '+stage],check=True,timeout=12)
subprocess.run(scp+[str(archive),'root@bonito:'+stage+'/native-overlay.tar.gz'],check=True,timeout=90)
config=dict(stage=stage,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),run=a.run,activate=a.activate or a.activate_existing,reuse_existing=a.activate_existing,expected_active=a.expected_active)
body='CONFIG='+repr(config)+'\n'+(Path(__file__).with_name('ca_overlay_removals.py')).read_text()+'\n'+(Path(__file__).with_name('native-overlay-device-v2.py')).read_text()
r=subprocess.run(ssh+['python3','-'],input=body.encode(),capture_output=True,timeout=120)
log='deploy-'+a.run+('-activation'if a.activate_existing else'');(a.bundle/(log+'.stdout')).write_bytes(r.stdout);(a.bundle/(log+'.stderr')).write_bytes(r.stderr);print(r.stdout.decode());print(r.stderr.decode());r.check_returncode()
