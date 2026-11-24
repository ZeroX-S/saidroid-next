#!/usr/bin/env python3
"""Package canonical ICMP null-FD cleanup over exact282; no default promotion."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, stat, tarfile, zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','output']:
    p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
p.add_argument('--content-pool',type=Path)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text())
assert before['schema']=='saildroid-native-overlay-v3' and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
    f=oldroot/n;assert not Path(n).is_absolute() and '..'not in Path(n).parts
    assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-icmp-cleanup-compat-v1'and module['passed']and module['unmodified_classfiles_byte_identical']
builder=repo/'scripts/runtime/build-icmp-cleanup-compat-vm.py';source=repo/'scripts/runtime/core/icmp-cleanup-compat'
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(source/'Inet6AddressImpl.patch')==v['patch_sha256']and sha(repo/v['reference'])==v['reference_sha256']
for k,c in module['components'].items():
    assert sha(a.module/(k+'-hostdex.jar'))==c['sha256']and sha(a.module/(k+'-classes.jar'))==c['class_jar_sha256']and c['all_existing_members_and_native_declarations_preserved']and c['all_existing_member_flags_preserved']
assert not module['components']['core-oj']['added_members']and module['components']['core-oj']['changed_classes']==['java/net/Inet6AddressImpl.class']
runtime=json.loads((oldroot/'runtime.json').read_text())
encoded=json.loads((a.encoded/'manifest.json').read_text());old_encoded=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text())
assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old_encoded
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old_encoded[k]
assert encoded['files'].keys()==old_encoded['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('loader_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc)
added=set();changed=[]
for n,v in encoded['files'].items():
    assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']
    assert sha(a.baseline_encoded/n)==old_encoded['files'][n]['sha256']==full['files'][n]['sha256']
    with zipfile.ZipFile(a.baseline_encoded/n)as z:old,_=enc.dex_members(z.read('classes.dex'));old_resources={k:sha256 for k in z.namelist()if not k.endswith('.dex')for sha256 in [hashlib.sha256(z.read(k)).hexdigest()]}
    with zipfile.ZipFile(a.encoded/n)as z:new,_=enc.dex_members(z.read('classes.dex'));new_resources={k:hashlib.sha256(z.read(k)).hexdigest()for k in z.namelist()if not k.endswith('.dex')}
    assert new_resources==old_resources
    assert set(old)<=set(new)
    actual_flag_changes={k:dict(before=old[k][0],after=new[k][0])for k in old if old[k][0]!=new[k][0]}
    assert actual_flag_changes=={}
    assert {k:v[0]for k,v in old.items()if v[0]&0x100}=={k:v[0]for k,v in new.items()if v[0]&0x100}
    added|=set(new)-set(old)
    if v['sha256']!=old_encoded['files'][n]['sha256']:changed.append(n)
assert changed==['java/dex/art/core-oj.jar']and added=={n for c in module['components'].values()for n in c['added_members']}
assert encoded['files']['java/dex/art/core-oj.jar']['source_sha256']==module['components']['core-oj']['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==27 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_names=['icmp-cleanup286-paired-v2-audit.json','icmp-cleanup286-encoded-v1-boundary.json','icmp-cleanup286-own-v1-audit.json','icmp-cleanup286-module-boundary-v1.json','icmp-cleanup286-v1-hosts-fixture-v1.json','icmp-cleanup286-own-v1.json','icmp-cleanup286-paired-v1-audit.json','icmp-cleanup286-expected-original-ids-v1.json','original-icmp-cleanup286-before-v2.json','original-icmp-cleanup286-after-v2.json']
proof_files=[evidence/n for n in proof_names]
audit,boundary,own,module_boundary,fixture=[json.loads(f.read_text())for f in proof_files[:5]]
assert audit['passed']and audit['whole_classes']==4 and audit['tests']==180 and audit['counts_before']==dict(started=180,passed=176,failed=4)and audit['counts_after']==dict(started=180,passed=178,failed=2)
assert audit['all_outcome_changes']==[dict(test='org.apache.harmony.tests.java.net.InetAddressTest#test_isReachableI',before=-2,after=0),dict(test='libcore.java.net.InetAddressTest#test_isReachable',before=-2,after=0)]
assert not audit['new_failed']and audit['all_cleanup_safe']and audit['exact_original_id_set']and not audit['phone_executed']and not audit['full_module_passed']
driver=evidence/'run-original-icmp-cleanup286-coupled-v2-vm.py'
for label,digest in audit['raw_results'].items():assert sha(evidence/('original-icmp-cleanup286-'+label+'-v2.json'))==digest
assert boundary['passed']and boundary['core_module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['changed_jars']==changed and boundary['encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and boundary['boot_manifest_sha256']==sha(a.boot/'manifest.json')and boundary['all_existing_effective_flags_preserved']and not boundary['new_flags']and not added
assert module_boundary['passed']and module_boundary['module_manifest_sha256']==sha(a.module/'manifest.json')and sha(proof_files[3])==audit['module_boundary_sha256']and module_boundary['all_other_classes_byte_identical']and not module_boundary['added_members']and module_boundary['unmodified_classfiles_byte_identical']
contract=repo/'scripts/runtime/tests/network/Network286ReachabilityContract.java';raw_own=json.loads(proof_files[5].read_text());assert raw_own['passed']and raw_own['private_data_removed']and raw_own['source_sha256']==sha(contract)
assert own['passed']and audit['own_audit_sha256']==sha(proof_files[2])and own['raw_own_sha256']==sha(proof_files[5])and own['existing_members_flags_native_preserved']and len(own['metrics'])==4
assert [v['actual_null_fd_crashes']for v in own['metrics']]==[0,0,34,0]and[v['tcp_connections']for v in own['metrics']]==[0,0,0,32]and all(v['fd_before']==v['fd_after']==26 and v['calls']==34 for v in own['metrics'])
assert fixture['passed']and all(v['dns_EACCES_failed']==43 and v['nlink']>1 for v in fixture['records'].values())
frozen=json.loads((evidence/'original-icmp-cleanup286-coupled-v2-frozen-inputs.json').read_text());assert all(sha(repo/n)==h for n,h in frozen['sources'].items())and all(sha(evidence/n)==h for n,h in frozen['proofs'].items())
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root,copy_function=os.link);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink()
    if target.exists():target.unlink()
    pooled=a.content_pool/n if a.content_pool else None
    if pooled and pooled.is_file()and not pooled.is_symlink()and pooled.stat().st_size==f.stat().st_size and sha(pooled)==sha(f)and stat.S_IMODE(pooled.stat().st_mode)==mode:
        os.link(pooled,target)
    else:
        shutil.copyfile(f,target);target.chmod(mode)
    v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/icmp-cleanup/'+n)
for n,v in module['sources']['files'].items():
    install(source/n,'share/build/icmp-cleanup/sources/'+n);install(source/'Inet6AddressImpl.patch','share/build/icmp-cleanup/pbe-api29.patch');install(repo/v['reference'],'share/build/icmp-cleanup/reference/Inet6AddressImpl.java')
for f in proof_files:install(f,'share/build/icmp-cleanup/evidence/'+f.name)
for f,n in [(contract,'tests/Contract.java'),(evidence/'audit-icmp-cleanup286-paired-v2.py','tests/audit-paired.py'),(evidence/'audit-icmp-cleanup286-own-v1.py','tests/audit-own.py'),(evidence/'run-icmp-cleanup286-own-v1-vm.py','tests/run-own.py'),(driver,'tests/run-original.py')]:install(f,'share/build/icmp-cleanup/'+n)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['icmp_cleanup_compat']=dict(schema=module['schema'],module_manifest_sha256=sha(a.module/'manifest.json'),canonical_null_guard=True,permission_denied_tcp_fallback=True,existing_protocol_address_security_rules_preserved=True,original_whole_class_tests=180,original_whole_class_failures=2,own_calls=136,own_after_denied_tcp_connections=32,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['icmp_cleanup_overlay']=dict(schema='saildroid-icmp-cleanup-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_art_media_manager_trust_cli_bytes_unchanged=True,original_whole_class_tests=180,original_whole_class_failures=2,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
assert not any(p.is_symlink()for p in root.rglob('*'))
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz',dereference=True)as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','r:gz')as archive:
    members=archive.getmembers();assert all(m.isfile()or m.isdir()for m in members),'V3 requires regular files/directories, never archive hardlinks'
    assert len([m for m in members if m.isfile()])==len(changes)+1
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert all(sha(oldroot/n)==v['sha256']and stat.S_IMODE((oldroot/n).stat().st_mode)==v['mode']for n,v in before['changes'].items())
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('ICMP_CLEANUP_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
