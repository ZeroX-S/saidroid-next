#!/usr/bin/env python3
"""Add a verified ordinary-user Java command without replacing the ART/core/runtime."""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,stat,tarfile,zipfile,importlib.util
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','component','module','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022)
repo=Path(__file__).resolve().parents[2];b=repo/'build/evidence/cts-frame-repair-20261031';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v3'and before['api']==29
full=before['install_manifest'];old=a.baseline/'payload';component_manifest=json.loads((a.component/'install-manifest.json').read_text());assert component_manifest==full
for n,v in full['files'].items():
 f=a.component/n;assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode'],n
for n,v in before['changes'].items():assert sha(old/n)==v['sha256']and stat.S_IMODE((old/n).stat().st_mode)==v['mode']
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-private-java-cli-v1'and module['passed']and module['raw_vm_copied_unchanged']and module['bootstrap_members_blacklisted']and module['bootstrap_code_unchanged_by_encoding']
source=repo/'native/commands/java-cli';builder=source/'build-vm.py';assert module['component_manifest_sha256']==sha(a.component/'install-manifest.json')
for key,f in [('builder_sha256',builder),('source_sha256',source/'dalvikvm.cpp'),('bootstrap_source_sha256',source/'SdJavaCommand.java'),('policy_header_sha256',repo/'native/host/app-filesystem-policy.hpp'),('json_header_sha256',repo/'native/host/third_party/json.hpp'),('binary_sha256',a.module/'dalvikvm'),('raw_vm_sha256',a.module/'dalvikvm-real'),('bootstrap_jar_sha256',a.module/'java-cli-bootstrap.jar')]:assert module[key]==sha(f),key
assert module['raw_vm_sha256']=='d722c5716eaca67ba1be68d64edba425ed88efca30afd043e90d6ae6ca60f3eb'
spec=importlib.util.spec_from_file_location('java_cli_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');encoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(encoder)
with zipfile.ZipFile(a.module/'bootstrap-raw.jar')as z:raw=z.read('classes.dex')
with zipfile.ZipFile(a.module/'java-cli-bootstrap.jar')as z:encoded=z.read('classes.dex')
rm,rc=encoder.dex_members(raw);em,ec=encoder.dex_members(encoded);assert rm==em and rc==ec and rm
flags=dict(line.split(',',1)for line in(a.module/'bootstrap-flags.csv').read_text().splitlines());assert set(flags)==set(rm)and set(flags.values())=={'blacklist'}
proof_names=['java-cli269-paired-v2-audit.json','java-cli268-basic-contract-v5.json','java-cli268-policy-contract-v1.json','java-cli268-prototype-v4.json','phone269-cli-abi-v1.json']
audit,own,policy,prototype,abi=[json.loads((b/n).read_text())for n in proof_names]
assert audit['passed']and audit['tests']==79 and audit['whole_classes']==7 and audit['before_pass']==78 and audit['before_fail']==1 and audit['after_pass']==79 and audit['after_fail']==0 and audit['all_cleanup_safe']and not audit['full_module_passed']and not audit['phone_executed']
assert own['passed']and policy['passed']and prototype['passed']
assert audit['own_basic_sha256']==sha(b/proof_names[1])and audit['own_policy_sha256']==sha(b/proof_names[2])
for n,h in audit['raw_results'].items():assert sha(b/n)==h
assert sha(b/'run-original-java-cli269-coupled-v3-vm.py')==audit['driver_sha256']
frozen=json.loads((b/'original-java-cli269-coupled-v3-frozen-inputs.json').read_text());assert len(frozen['sources'])==audit['frozen_sources']and len(frozen['proofs'])==audit['frozen_proofs'];assert all(sha(repo/n)==h for n,h in frozen['sources'].items())and all(sha(b/n)==h for n,h in frozen['proofs'].items())
assert abi['phone']['libc']['stdout']=='glibc 2.41\n'and abi['phone']['libstdc']['code']==0
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(old,root,copy_function=os.link)
after=copy.deepcopy(before);manifest=after['install_manifest'];updated=[]
def install(f,n,mode=0o644):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True)
 assert not target.is_symlink()
 if target.exists():target.unlink()
 shutil.copyfile(f,target);target.chmod(mode);v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=after['changes'][n]=v;updated.append(n)
for f,n,mode in [('dalvikvm','bin/dalvikvm',0o755),('dalvikvm-real','libexec/dalvikvm-real',0o755),('java-cli-bootstrap.jar','lib/java-cli-bootstrap.jar',0o644)]:
 assert n not in full['files'];install(a.module/f,n,mode)
for f,n in [(a.module/'manifest.json','module-manifest.json'),(a.module/'bootstrap-flags.csv','bootstrap-flags.csv'),(a.module/'bootstrap-raw.jar','bootstrap-raw.jar'),(source/'dalvikvm.cpp','sources/dalvikvm.cpp'),(source/'SdJavaCommand.java','sources/SdJavaCommand.java'),(builder,'builder.py'),(Path(__file__),'packager.py'),(repo/'native/host/app-filesystem-policy.hpp','sources/app-filesystem-policy.hpp')]:install(f,'share/build/java-cli/'+n)
for n in proof_names:install(b/n,'share/build/java-cli/evidence/'+n)
for n in ['JavaCli268ContractMain.java','JavaCli268ReturnMain.java','JavaCli268ThrowMain.java','run-java-cli268-basic-contract-v5-vm.py','run-java-cli268-policy-contract-v1-vm.py','run-original-java-cli269-coupled-v3-vm.py','audit-java-cli269-paired-v2.py']:install(b/n,'share/build/java-cli/tests/'+n)
runtime=json.loads((old/'runtime.json').read_text());runtime['private_java_cli']=dict(schema=module['schema'],module_manifest_sha256=sha(a.module/'manifest.json'),ordinary_uid_only=True,actual_art_executable_sha256=module['raw_vm_sha256'],bootstrap_blacklisted=True,sdk=29,hidden_api_policy='enabled',original_whole_classes=7,original_selected_tests=79,original_selected_failures=0,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert manifest['symlinks']==full['symlinks']and set(full['files'])<=set(manifest['files'])
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n!='runtime.json')
assert set(n for n in updated if n in full['files'])=={'runtime.json'}
assert runtime['boot_jars']==json.loads((old/'runtime.json').read_text())['boot_jars']
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert after[k]==before[k]
for n,v in after['changes'].items():assert sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']
after['java_cli_overlay']=dict(schema='saildroid-java-cli-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_existing_native_art_core_runtime_trust_bytes_unchanged=True,original_selected_tests=79,original_selected_failures=0,full_module_passed=False,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n');assert not any(p.is_symlink()for p in root.rglob('*'))
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz',dereference=True)as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','r:gz')as archive:
 members=archive.getmembers();assert all(m.isfile()or m.isdir()for m in members);assert len([m for m in members if m.isfile()])==len(after['changes'])+1
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and all(sha(old/n)==v['sha256']for n,v in before['changes'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('JAVA_CLI_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
