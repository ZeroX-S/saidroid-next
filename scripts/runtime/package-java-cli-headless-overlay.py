#!/usr/bin/env python3
"""Package the verified ordinary-user headless CLI without changing platform libraries."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,stat,tarfile,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','component','module','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True);a=p.parse_args();os.umask(0o022)
repo=Path(__file__).resolve().parents[2];b=repo/'build/evidence/cts-frame-repair-20261031';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v3'and before['api']==29
full=before['install_manifest'];old=a.baseline/'payload';assert json.loads((a.component/'install-manifest.json').read_text())==full
for n,v in full['files'].items():
 f=a.component/n;assert not f.is_symlink()and f.is_file()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode'],n
for n,v in before['changes'].items():assert sha(old/n)==v['sha256']and stat.S_IMODE((old/n).stat().st_mode)==v['mode']
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-private-java-cli-v2'and module['passed']and module['raw_vm_copied_unchanged']and module['bootstrap_members_blacklisted']and module['bootstrap_code_unchanged_by_encoding']and module['application_main_ownership_enforced_before_initialization']and module['private_runtime_properties_pinned']
source=repo/'native/commands/java-cli-headless-path';builder=source/'build-vm.py';assert module['component_manifest_sha256']==sha(a.component/'install-manifest.json')
for key,f in [('builder_sha256',builder),('source_sha256',source/'dalvikvm.cpp'),('bootstrap_source_sha256',source/'SdJavaCommand.java'),('policy_header_sha256',repo/'native/host/app-filesystem-policy.hpp'),('json_header_sha256',repo/'native/host/third_party/json.hpp'),('binary_sha256',a.module/'dalvikvm'),('raw_vm_sha256',a.module/'dalvikvm-real'),('bootstrap_jar_sha256',a.module/'java-cli-bootstrap.jar')]:assert module[key]==sha(f),key
assert module['raw_vm_sha256']==full['files']['libexec/dalvikvm-real']['sha256']=='d722c5716eaca67ba1be68d64edba425ed88efca30afd043e90d6ae6ca60f3eb'
assert module['headless_framework_runtime_sha256']==full['files']['lib/runtime.jar']['sha256']
assert module['runtime_module_manifest_sha256']==full['files']['share/build/crypto-provider-alias/core-manifest.json']['sha256']
spec=importlib.util.spec_from_file_location('cli_headless_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
with zipfile.ZipFile(a.module/'bootstrap-raw.jar')as z:raw=z.read('classes.dex')
with zipfile.ZipFile(a.module/'java-cli-bootstrap.jar')as z:encoded=z.read('classes.dex')
rm,rc=enc.dex_members(raw);em,ec=enc.dex_members(encoded);assert rm==em and rc==ec and len(rm)==2
with zipfile.ZipFile(a.component/'lib/java-cli-bootstrap.jar')as z:oldmembers,_=enc.dex_members(z.read('classes.dex'))
assert {n:v[0]for n,v in oldmembers.items()}=={n:v[0]for n,v in rm.items()}
flags=dict(l.split(',',1)for l in(a.module/'bootstrap-flags.csv').read_text().splitlines());assert flags=={n:'blacklist'for n in rm}
audit=json.loads((b/'java-cli282-headless-paired-v2-audit.json').read_text());own=json.loads((b/'java-cli282-own-v2-audit.json').read_text());boundary=json.loads((b/'java-cli282-headless-path-v4-module-boundary.json').read_text());abi=json.loads((b/'phone282-cli-abi-v1.json').read_text())
assert audit['passed']and audit['tests']==79 and audit['whole_classes']==7 and audit['before_pass']==audit['after_pass']==79 and audit['before_fail']==audit['after_fail']==0 and audit['all_cleanup_safe']and audit['all_original_declared_listener_automatically_loaded']and not audit['phone_executed']and not audit['full_module_passed']
assert audit['own_audit_sha256']==sha(b/'java-cli282-own-v2-audit.json')and own['passed']and own['policy_cases']==26 and own['crypto_operations']==5 and own['native_owner_crypto_operations']==5 and own['java_initialization_cases']==2 and own['empty_native_path_real_crypto_passed']
assert own['v1_deployable']is False and own['v2_deployable']is False and own['v3_deployable']is False
assert own['current_module_boundary_sha256']==audit['module_boundary_sha256']==sha(b/'java-cli282-headless-path-v4-module-boundary.json')and boundary['module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['binary_sha256']==module['binary_sha256']and boundary['bootstrap_jar_sha256']==module['bootstrap_jar_sha256']
assert abi['passed']and not abi['missing']and abi['wrapper_sha256']==module['binary_sha256']
for n,h in own['proofs'].items():assert sha(b/n)==h
for label,h in audit['raw_results'].items():assert sha(b/('original-java-cli282-headless-'+label+'-v2.json'))==h
assert audit['driver_sha256']==sha(b/'run-original-java-cli282-headless-coupled-v2-vm.py')
frozen=json.loads((b/'original-java-cli282-headless-coupled-v2-frozen-inputs.json').read_text());assert len(frozen['sources'])==audit['frozen_sources']and len(frozen['proofs'])==audit['frozen_proofs'];assert all(sha(repo/n)==h for n,h in frozen['sources'].items())and all(sha(b/n)==h for n,h in frozen['proofs'].items())
proof_names=list(dict.fromkeys(['java-cli282-headless-paired-v2-audit.json','java-cli282-own-v2-audit.json','phone282-cli-abi-v1.json',*own['proofs']]))
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(old,root,copy_function=os.link)
after=copy.deepcopy(before);manifest=after['install_manifest'];updated=[]
def install(f,n,mode=0o644):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink()
 if target.exists():target.unlink()
 shutil.copyfile(f,target);target.chmod(mode);v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=after['changes'][n]=v;updated.append(n)
install(a.module/'dalvikvm','bin/dalvikvm',full['files']['bin/dalvikvm']['mode']);install(a.module/'java-cli-bootstrap.jar','lib/java-cli-bootstrap.jar')
ns='share/build/java-cli-headless/'
for f,n in [(a.module/'manifest.json','module-manifest.json'),(a.module/'bootstrap-flags.csv','bootstrap-flags.csv'),(a.module/'bootstrap-raw.jar','bootstrap-raw.jar'),(source/'dalvikvm.cpp','sources/dalvikvm.cpp'),(source/'SdJavaCommand.java','sources/SdJavaCommand.java'),(builder,'builder.py'),(Path(__file__),'packager.py'),(repo/'native/host/app-filesystem-policy.hpp','sources/app-filesystem-policy.hpp')]:install(f,ns+n)
for n in proof_names:install(b/n,ns+'evidence/'+n)
for n in ['JavaCli282CryptoMain.java','JavaCli282CryptoNativeMain.java','JavaCli282MainBase.java','JavaCli282InheritedMain.java','JavaCli282StaticCryptoMain.java','run-java-cli282-crypto-after-v4-vm.py','run-java-cli282-native-crypto-v2-vm.py','run-java-cli282-native-path-empty-v2-vm.py','run-java-cli282-basic-contract-v2-vm.py','run-java-cli282-policy-contract-v2-vm.py','run-java-cli282-inherited-v4-vm.py','run-original-java-cli282-headless-coupled-v2-vm.py','audit-java-cli282-headless-paired-v2.py','audit-java-cli282-own-v2.py']:install(b/n,ns+'tests/'+n)
for folder,label in [('java-cli-framework','v1-fonts'),('java-cli-headless','v2-initializer'),('java-cli-headless-init','v3-empty-native-path')]:
 for n in ['dalvikvm.cpp','SdJavaCommand.java','build-vm.py']:
  f=repo/'native/commands'/folder/n;assert frozen['sources'][str(f.relative_to(repo))]==sha(f);install(f,ns+'rejected/'+label+'/'+n)
runtime=json.loads((old/'runtime.json').read_text());previous_cli=runtime['private_java_cli'];runtime['private_java_cli']=dict(schema=module['schema'],module_manifest_sha256=sha(a.module/'manifest.json'),previous_module_manifest_sha256=previous_cli['module_manifest_sha256'],ordinary_uid_only=True,actual_art_executable_sha256=module['raw_vm_sha256'],bootstrap_blacklisted=True,sdk=29,hidden_api_policy='enabled',headless_base_jni_namespace_crypto_bootstrap=True,application_main_ownership_before_initialization=True,inherited_main_class_initialization_preserved=True,private_native_path_prefix_preserved_for_empty_or_user_paths=True,original_whole_classes=7,original_selected_tests=79,original_selected_failures=0,own_policy_cases=26,own_crypto_operations=5,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink();manifest['bytes']=sum(v['size']for v in manifest['files'].values())
assert manifest['symlinks']==full['symlinks']and set(full['files'])<=set(manifest['files'])
replaced={'bin/dalvikvm','lib/java-cli-bootstrap.jar','runtime.json'};assert {n for n in updated if n in full['files']}==replaced
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in replaced)
assert runtime['boot_jars']==json.loads((old/'runtime.json').read_text())['boot_jars']
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert after[k]==before[k]
for n,v in after['changes'].items():assert sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']
after['java_cli_headless_overlay']=dict(schema='saildroid-java-cli-headless-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_existing_native_art_core_runtime_jar_boot_image_trust_manager_media_bytes_unchanged=True,original_selected_tests=79,original_selected_failures=0,full_module_passed=False,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n');assert not any(p.is_symlink()for p in root.rglob('*'))
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz',dereference=True)as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','r:gz')as archive:
 members=archive.getmembers();assert all(m.isfile()or m.isdir()for m in members);assert len([m for m in members if m.isfile()])==len(after['changes'])+1
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and all(sha(old/n)==v['sha256']for n,v in before['changes'].items())
assert all(sha(repo/n)==h for n,h in frozen['sources'].items())and all(sha(b/n)==h for n,h in frozen['proofs'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz');print('JAVA_CLI_HEADLESS_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
