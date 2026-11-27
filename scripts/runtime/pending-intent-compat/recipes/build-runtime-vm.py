from pathlib import Path
import os,subprocess,hashlib,json,shutil,zipfile,importlib.util
os.umask(0o022)
repo=Path('/media/psf/Home/WorkSpace/saidroid-next');b=repo/'build/evidence/qq-pending-intent301-20261102-v1';base=Path('/var/tmp/saidroid-surface-texture298-runtime-v1');out=Path('/var/tmp/saidroid-pending-intent301-runtime-v2');out.mkdir();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source=b/'source';java=Path('/tmp/jdkfull/jdk-21.0.13+9/bin');inputs=repo/'build/codex-api29/inputs';fw=inputs/'android-all-10-robolectric-5803371.jar';r8=inputs/'r8-8.3.37.jar';commands=[]
input_hashes={str(p.relative_to(source)):sha(p)for p in source.rglob('*')if p.is_file()}
names=[str(p.relative_to(source))for p in (source/'scripts/device').rglob('*.java')];assert len(names)==3
before={str(p.relative_to(base/'classes')):sha(p)for p in(base/'classes').rglob('*.class')};oldmeta=json.loads((repo/'build/evidence/qq-surface-texture300-20261102-v1/runtime-build.json').read_text());assert before==oldmeta['classfiles_after']
def run(c,n):
 commands.append(c)
 with(out/n).open('ab',buffering=0)as f:subprocess.run(c,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
old=out/'baseline-classes';old.mkdir();old_sources=[]
for n in names:
 if not n.endswith('/SdPendingIntents.java'):
  old_sources.append(repo/'build/evidence/qq-manifest-receivers292-20261102-v1/source'/n if n.endswith('/SdActivityManagerService.java') else repo/n)
run([str(java/'javac'),'--release','8','-nowarn','-cp',str(fw)+':'+str(base/'classes'),'-d',str(old),*map(str,old_sources)],'baseline-javac.log')
oldclasses={str(p.relative_to(old)):sha(p)for p in old.rglob('*.class')};assert all(before[n]==h for n,h in oldclasses.items()),'Baseline source must reproduce existing bytecode'
new=out/'overlay-classes';new.mkdir();run([str(java/'javac'),'--release','8','-nowarn','-cp',str(fw)+':'+str(base/'classes'),'-d',str(new),*map(str,[source/n for n in names])],'javac.log')
classes=out/'classes';shutil.copytree(base/'classes',classes)
for p in new.rglob('*.class'):shutil.copyfile(p,classes/p.relative_to(new))
after={str(p.relative_to(classes)):sha(p)for p in classes.rglob('*.class')};changed=[n for n in before if before[n]!=after[n]];added=sorted(set(after)-set(before));assert set(before)<=set(after)
allowed=['SdActivityManagerService','SdNotificationPolicy']
assert all(any(n==v+'.class'or n.startswith(v+'$')for v in allowed)for n in changed),changed
assert all(n=='SdPendingIntents.class'or n.startswith('SdPendingIntents$')for n in added),added
run([str(java/'java'),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(fw),'--output',str(out/'runtime.jar'),*map(str,sorted(classes.rglob('*.class')))],'d8.log')
spec=importlib.util.spec_from_file_location('enc',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
def members(p):
 with zipfile.ZipFile(p)as z:return enc.dex_members(z.read('classes.dex'))[0]
oldmembers=members(base/'runtime.jar');newmembers=members(out/'runtime.jar');assert set(oldmembers)<=set(newmembers)and all(oldmembers[n][0]==newmembers[n][0]for n in oldmembers)
assert input_hashes=={str(p.relative_to(source)):sha(p)for p in source.rglob('*')if p.is_file()},'Sources changed during build'
record=dict(passed=True,scope='Application-owned PendingIntent token registry and real existing-backend dispatch; disabled-notification drop policy. No core/framework/boot change.',builder_sha256=sha(Path(__file__)),source_sha256={n:sha(source/n)for n in names},classfiles_before=before,classfiles_after=after,baseline_classfiles_reproduced=True,changed_classfiles=changed,added_classfiles=added,new_members=sorted(set(newmembers)-set(oldmembers)),existing_members_flags_native_preserved=True,runtime_sha256=sha(out/'runtime.jar'),commands=commands)
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');(b/'runtime-build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items()if k not in ['classfiles_before','classfiles_after','commands']},indent=2),flush=True)
