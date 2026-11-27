#!/usr/bin/env python3
"""Install a private OAT/VDEX only for a closed app and exact component inputs.

Run in the build VM while holding scripts/devlock.sh. No APK/user data changes.
An earlier cache is replaced only after its saved manifest and bytes agree.
"""
from pathlib import Path
import argparse,subprocess,os,json,hashlib,re
def digest(path):
 with Path(path).open('rb')as source:return hashlib.file_digest(source,'sha256').hexdigest()
p=argparse.ArgumentParser();p.add_argument('cache',type=Path);p.add_argument('package');p.add_argument('run');a=p.parse_args()
assert re.fullmatch(r'[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+',a.package)
assert re.fullmatch('[a-z0-9-]+',a.run)
recipe=json.loads((a.cache/'recipe.json').read_text());files=json.loads((a.cache/'manifest.json').read_text());assert set(files)=={'base.odex','base.vdex'}
for name,item in files.items():assert digest(a.cache/name)==item['sha256']
config=dict(recipe=recipe,files=files,package=a.package,stage='/home/art/test/app-cache-'+a.run,run=a.run)
env=dict(os.environ,SSHPASS=os.environ['SSHPASS']);ssh=['sshpass','-e','ssh','-o','ConnectTimeout=6','root@bonito']
subprocess.run(ssh+['test ! -e '+config['stage']+' && install -d -m0755 '+config['stage']],env=env,check=True,timeout=10)
subprocess.run(['sshpass','-e','scp','-O','-q',*[str(a.cache/n)for n in files],'root@bonito:'+config['stage']+'/'],env=env,check=True,timeout=180)
body='CONFIG='+repr(config)+'\n'+r'''
from pathlib import Path
import subprocess,pwd,os,json,hashlib
def digest(path):
 with Path(path).open('rb')as source:return hashlib.file_digest(source,'sha256').hexdigest()
assert Path('/home/art/test/.device-lock/owner').is_file()
root=Path('/home/art/api29-root');recipe=CONFIG['recipe']
assert digest(root/'lib/runtime.jar')==recipe['runtime_jar_sha256']
for name,sha in recipe['boot_files'].items():assert digest(root/name)==sha
assert json.loads((root/'runtime.json').read_text())['boot_image']==recipe['boot_image']
# Compiler and phone must use identical image files, not merely the same DEX jars.
expected_images=recipe.get('image_files',{})
assert expected_images,'Cache recipe requires image hashes'
for name,sha in expected_images.items():assert digest(root/name)==sha
for name in CONFIG['files']:
 source=Path(CONFIG['stage'])/name;assert digest(source)==CONFIG['files'][name]['sha256'];source.chmod(0o644)
a=pwd.getpwnam('defaultuser')
code='CONFIG='+repr(CONFIG)+'\n'+r"""
from pathlib import Path
import json,os,hashlib,shutil
def digest(path):
 with Path(path).open('rb')as source:return hashlib.file_digest(source,'sha256').hexdigest()
pkg=CONFIG['package'];base=Path('/home/art/apps')/pkg;assert base.is_dir() and not base.is_symlink()
record=json.loads((base/'record.json').read_text());apk=Path(record['apk']);assert record['package']==pkg and str(apk)==CONFIG['recipe']['apk_location'];assert apk.resolve()==apk and base in apk.parents
assert digest(apk)==CONFIG['recipe']['apk_sha256']
state=Path('/run/user/100000/saildroid')/(pkg+'.json')
if state.exists():assert json.loads(state.read_text())['state']=='exited'
root=apk.parent/'oat';assert not root.is_symlink();root.mkdir(exist_ok=True);target=root/'arm64';assert not target.is_symlink();target.mkdir(exist_ok=True)
old_manifest=target/'saidroid-cache-manifest.json'
if any((target/name).exists()for name in CONFIG['files']):
 legacy=target/'saidroid-cache-manifest-r86.json'
 if old_manifest.exists():old=json.loads(old_manifest.read_text())['files']
 elif legacy.exists():old=json.loads(legacy.read_text())['files']
 else:raise RuntimeError('Existing app cache has no verified owner manifest')
 for name,item in old.items():assert digest(target/name)==item['sha256']
for name,item in CONFIG['files'].items():
 source=Path(CONFIG['stage'])/name;temp=target/('.'+name+'.'+CONFIG['run']);assert not temp.exists();
 with source.open('rb')as input,temp.open('xb')as output:shutil.copyfileobj(input,output,1024*1024)
 temp.chmod(0o600);assert digest(temp)==item['sha256']
for name in CONFIG['files']:os.replace(target/('.'+name+'.'+CONFIG['run']),target/name)
old_manifest.write_text(json.dumps(CONFIG,indent=2)+'\n');old_manifest.chmod(0o600)
print('APP_DEX_CACHE=installed|package='+pkg+'|uid='+str(os.getuid())+'|filter=speed|apk_unchanged=true')
"""
r=subprocess.run(['python3','-'],input=code,text=True,user=a.pw_uid,group=a.pw_gid,extra_groups=os.getgrouplist(a.pw_name,a.pw_gid),timeout=100);r.check_returncode()
'''
r=subprocess.run(ssh+['python3 -'],input=body,text=True,capture_output=True,env=env,timeout=120);print(r.stdout);print(r.stderr);r.check_returncode()
