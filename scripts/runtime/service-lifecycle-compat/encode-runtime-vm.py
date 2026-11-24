from pathlib import Path
import json,hashlib,subprocess
repo=Path('/media/psf/Home/WorkSpace/saidroid-next');b=repo/'build/evidence/qq-service-lifecycle305-20261103-v1';out=Path('/var/tmp/saidroid-service-lifecycle305-runtime-v1');inputs=Path('/var/tmp/saidroid-icmp-cleanup286-encoded-v1/inputs');old=Path('/var/tmp/saidroid-pending-intent301-runtime-v2/encoded');sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();build=json.loads((b/'runtime-build.json').read_text());assert build['passed']and sha(out/'runtime.jar')==build['runtime_sha256']
encoded=out/'encoded';cmd=['python3',str(repo/'scripts/runtime/encode-hiddenapi-vm.py'),str(inputs),str(out/'runtime.jar'),str(repo/'build/evidence/cts-frame-repair-20261031/aosp-extra/android10-hiddenapi-flags.csv.gz'),'/var/tmp/saidroid-hiddenapi-tool-20261031/hiddenapi',str(encoded)]
with(b/'encode.log').open('ab',buffering=0)as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=150)
before=json.loads((old/'manifest.json').read_text());after=json.loads((encoded/'manifest.json').read_text());assert before['files'].keys()==after['files'].keys()
for key in ['schema','canonical_flags_sha256','tool_sha256','unknown_policy','public_library_apis']:assert before[key]==after[key],key
changed=[n for n,v in after['files'].items()if v['sha256']!=before['files'][n]['sha256']];assert changed==['lib/runtime.jar'],changed
for n,v in after['files'].items():assert sha(encoded/n)==v['sha256']and v['executable_code_unchanged']
def flags(p):return dict(l.split(',',1)for l in p.read_text().splitlines())
a=flags(old/'effective-api-flags.csv');z=flags(encoded/'effective-api-flags.csv');assert set(a)<=set(z)and all(z[n]==v for n,v in a.items());added=sorted(set(z)-set(a));assert added==build['new_members']and all(z[n]=='blacklist'for n in added)
record=dict(passed=True,encoder_sha256=sha(Path(__file__)),command=cmd,encoded_root=str(encoded),encoded_runtime_sha256=sha(encoded/'lib/runtime.jar'),encoded_manifest_sha256=sha(encoded/'manifest.json'),changed_encoded_jars=changed,all_existing_hidden_api_flags_unchanged=True,all_new_members_implementation_private=True,new_private_members=added,core_framework_boot_jars_byte_unchanged=True,boot_images_reused=True)
(b/'encoded-build.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2),flush=True)
