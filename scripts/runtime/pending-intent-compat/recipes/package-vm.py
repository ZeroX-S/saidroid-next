from pathlib import Path
import json,hashlib,copy,shutil,stat,os,tarfile
os.umask(0o022)
r=Path('/media/psf/Home/WorkSpace/saidroid-next');b=r/'build/evidence/qq-pending-intent301-20261102-v1';priorb=r/'build/evidence/qq-surface-texture300-20261102-v1';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();proof=json.loads((priorb/'package.json').read_text());assert proof['passed'];prior=Path(proof['bundle']);assert sha(prior/'native-overlay.tar.gz')==proof['tarball_sha256'];before=json.loads((prior/'overlay.json').read_text());java=json.loads((b/'runtime-build.json').read_text());enc=json.loads((b/'encoded-build.json').read_text());assert java['passed']and enc['passed']and enc['all_existing_hidden_api_flags_unchanged']and enc['core_framework_boot_jars_byte_unchanged']
for n,h in java['source_sha256'].items():assert sha(b/'source'/n)==h
workspace=Path('/var/tmp/saidroid-native-pending-intent301-v1');workspace.mkdir();payload=workspace/'payload';shutil.copytree(Path(proof['native_payload']),payload,copy_function=os.link);after=copy.deepcopy(before);updated=[]
def install(f,n,mode=0o644):
 target=payload/n;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists()or target.is_symlink():target.unlink()
 shutil.copyfile(f,target);target.chmod(mode);v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);after['changes'][n]=after['install_manifest']['files'][n]=v;updated.append(n)
encoded=Path(enc['encoded_root']);assert sha(encoded/'lib/runtime.jar')==enc['encoded_runtime_sha256'];install(encoded/'lib/runtime.jar','lib/runtime.jar');install(encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in ['runtime-build.json','encoded-build.json','sources.json','build-runtime-vm.py','encode-runtime-vm.py','package-vm.py']:install(b/n,'share/build/pending-intent/'+n)
for parent in ['source','test-source']:
 for f in sorted((b/parent).rglob('*')):
  if f.is_file():install(f,'share/build/pending-intent/'+str(f.relative_to(b)))
runtime=json.loads((payload/'runtime.json').read_text());runtime['hidden_api']['manifest_sha256']=enc['encoded_manifest_sha256'];runtime['pending_intent']=dict(schema='saidroid-pending-intent-v1',scope='Application-owned process-lifetime tokens; real existing broadcast/activity/service dispatch; host notification delivery disabled.',runtime_build_sha256=sha(b/'runtime-build.json'),validation='candidate-not-yet-accepted');tmp=workspace/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json')
manifest=after['install_manifest'];manifest['bytes']=sum(v['size']for v in manifest['files'].values());after['pending_intent_overlay']=dict(schema='saidroid-pending-intent-overlay-v1',baseline_sha256=proof['tarball_sha256'],updated_files=updated,core_framework_boot_art_native_unchanged=True)
assert manifest['symlinks']==before['install_manifest']['symlinks']and set(before['install_manifest']['files'])<=set(manifest['files'])
for n,v in before['install_manifest']['files'].items():
 if n not in updated:assert manifest['files'][n]==v
for n,v in after['changes'].items():assert sha(payload/n)==v['sha256']and stat.S_IMODE((payload/n).stat().st_mode)==v['mode']
bundle=b/'bundle';bundle.mkdir();(bundle/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(bundle/'native-overlay.tar.gz.pending','w:gz',dereference=True)as t:t.add(payload,arcname='payload');t.add(bundle/'overlay.json',arcname='overlay.json')
with tarfile.open(bundle/'native-overlay.tar.gz.pending','r:gz')as t:assert all(v.isfile()or v.isdir()for v in t.getmembers())and sum(v.isfile()for v in t.getmembers())==len(after['changes'])+1
(bundle/'native-overlay.tar.gz.pending').replace(bundle/'native-overlay.tar.gz');record=dict(passed=True,scope='Candidate packaging only; no functional acceptance.',bundle=str(bundle),native_payload=str(payload),tarball_sha256=sha(bundle/'native-overlay.tar.gz'),overlay_sha256=sha(bundle/'overlay.json'),files=len(manifest['files']),symlinks=len(manifest['symlinks']),updated_files=updated,core_framework_boot_art_native_unchanged=True);(b/'package.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2),flush=True)
