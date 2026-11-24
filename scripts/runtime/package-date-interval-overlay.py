#!/usr/bin/env python3
"""Package the canonical Android10 midnight interval policy over current248."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, stat, tarfile, zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','baseline-encoded','encoded','boot','output']:
    p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text())
assert before['schema']=='saildroid-native-overlay-v3' and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
    f=oldroot/n;assert not Path(n).is_absolute() and '..'not in Path(n).parts
    assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-date-interval-compat-v1'and module['passed']
builder=repo/'scripts/runtime/build-date-interval-compat-vm.py';source=repo/'scripts/runtime/core/date-interval-compat'
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
for n,v in module['sources']['files'].items():
    assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
    baseline=(repo/v['baseline_source']).read_text();reference=(repo/v['reference']).read_text();candidate=(source/n).read_text()
    if n.endswith('/DateIntervalFormat.java'):
        start=baseline.index('    boolean endsAtMidnight =');end=baseline.index('\n    String skeleton',start)
        rs=reference.index('    // Special handling when the range ends at midnight:');re=reference.index('\n    String skeleton',rs)
        assert candidate==baseline[:start]+reference[rs:re].replace('isExactlyMidnight(endCalendar)','isMidnight(endCalendar)')+baseline[end:]
    else:
        assert n=='libcore/icu/DateUtilsBridge.java';rs=reference.index('  /**\n   * Returns whether the argument will be displayed');re=reference.index('  private static boolean onTheHour',rs);start=baseline.index('  private static boolean onTheHour')
        assert candidate==baseline[:start]+reference[rs:re]+baseline[start:]
assert all(sha(source/n)==h for n,h in module['sources']['patches'].items())
core=module['components']['core-libart'];assert sha(a.module/'core-libart-hostdex.jar')==core['sha256']and sha(a.module/'core-libart-classes.jar')==core['class_jar_sha256']
assert core['changed_classes']==['libcore/icu/DateIntervalFormat.class','libcore/icu/DateUtilsBridge.class']and core['all_existing_members_and_native_declarations_preserved']and core['all_existing_member_flags_preserved']and core['added_members']==['Llibcore/icu/DateUtilsBridge;->isDisplayMidnightUsingSkeleton(Landroid/icu/util/Calendar;)Z']
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
assert changed==['java/dex/art/core-libart.jar']and len(added)==1 and added==set(core['added_members'])
assert encoded['files']['java/dex/art/core-libart.jar']['source_sha256']==core['sha256']
flags=lambda d:dict(line.split(',',1)for line in(d/'effective-api-flags.csv').read_text().splitlines())
af,bf=flags(a.baseline_encoded),flags(a.encoded);assert set(bf)-set(af)==added and all(bf[n]==v for n,v in af.items())
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text())
assert len(images)==27 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}
assert all(sha(a.boot/n)==h for n,h in images.items())
evidence=repo/'build/evidence/cts-frame-repair-20261031'
proof_files=[evidence/n for n in ['date-interval252-paired-v1-audit.json','date-interval252-encoded-v1-boundary.json']]
audit,boundary=[json.loads(f.read_text())for f in proof_files]
assert audit['passed']and not audit['full_module_passed']and not audit['formal_module_acceptance']and not audit['phone_staged']
for label,tests in [('selected',16),('regression',81)]:
    proof=audit['cohorts'][label];assert proof['same_ordered_callbacks']and proof['unique_original_tests']==tests
    raw=evidence/('original-date-interval252-'+label+'-v1.json');driver=evidence/('run-original-date-interval252-'+label+'-v1-vm.py');assert sha(raw)==proof['raw_sha256']and sha(driver)==proof['driver_sha256'];data=json.loads(raw.read_text())
    assert data['actual_core_libart_sha256']==old_encoded['files']['java/dex/art/core-libart.jar']['sha256']and data['actual_new_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']
    assert data['actual_new_bouncycastle_sha256']==data['actual_old_bouncycastle_sha256']==old_encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['sha256']==encoded['files']['java/dex/art/bouncycastle-hostdex.jar']['sha256']
    assert data['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')and data['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
    for key,n in [('actual_core_oj_sha256','java/dex/art/core-oj.jar'),('actual_new_core_oj_sha256','java/dex/art/core-oj.jar'),('actual_runtime_sha256','lib/runtime.jar'),('actual_javacore_sha256','lib/libjavacore.so'),('actual_native_host_sha256','lib/libsdhost29.so'),('actual_bridge_sha256','lib/libsdbridge.so'),('actual_art_baseline_sha256','lib/libart.so'),('actual_art_candidate_sha256','lib/libart.so'),('actual_companion_sha256','lib/libsdmath-precision.so')]:assert data[key]==full['files'][n]['sha256']
sel=audit['cohorts']['selected'];reg=audit['cohorts']['regression']
assert sel['counts']['before248']==dict(tests=16,failures=1,assumptions=0,ignored=0,real_passed=15)and sel['counts']['after252']==dict(tests=16,failures=0,assumptions=0,ignored=0,real_passed=16)
assert reg['counts']['before248']==reg['counts']['after252']==dict(tests=81,failures=0,assumptions=0,ignored=0,real_passed=81)
assert boundary['passed']and boundary['core_module_manifest_sha256']==sha(a.module/'manifest.json')and boundary['changed_jars']==changed and boundary['encoded_manifest_sha256']==sha(a.encoded/'manifest.json')and boundary['boot_manifest_sha256']==sha(a.boot/'manifest.json')and boundary['all_existing_effective_flags_preserved']and set(boundary['new_flags'])==added
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
    if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
    target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode)
    v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
for n in changed:install(a.encoded/n,n,full['files'][n]['mode'])
install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(Path(__file__),'packager.py')]:install(f,'share/build/date-interval/'+n)
for n in module['sources']['files']:install(source/n,'share/build/date-interval/sources/'+n)
for n,v in module['sources']['files'].items():install(repo/v['reference'],'share/build/date-interval/references/'+n)
for f in proof_files:install(f,'share/build/date-interval/evidence/'+f.name)
for n in module['sources']['patches']:install(source/n,'share/build/date-interval/'+n)
for name in ['selected','regression']:
    for prefix,suffix in [('run-','-vm.py'),('','.json')]:
        f=evidence/(prefix+'original-date-interval252-'+name+'-v1'+suffix);install(f,'share/build/date-interval/tests/'+f.name)
install(evidence/'audit-date-interval252-paired-v1-vm.py','share/build/date-interval/tests/audit-paired.py')
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['date_interval_compat']=dict(schema=module['schema'],core_module_manifest_sha256=sha(a.module/'manifest.json'),core_libart_sha256=encoded['files']['java/dex/art/core-libart.jar']['sha256'],canonical_midnight_policy=True,old_private_isMidnight_ABI_preserved=True,all_existing_members_flags_native_preserved=True,original_whole_class_tests=16,original_whole_class_failures=0,original_date_regression_tests=81,original_date_regression_failures=0,full_module_passed=False,phone_executed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])<=set(manifest['files'])and manifest['symlinks']==full['symlinks']
for k in ['remove_files','ca_alias_cleanup','product_manifest','release_file_cleanup']:assert before[k]==after[k]
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['date_interval_overlay']=dict(schema='saildroid-date-interval-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),all_native_art_media_manager_trust_bytes_unchanged=True,original_whole_class_tests=16,original_whole_class_failures=0,original_date_regression_tests=81,original_date_regression_failures=0,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
assert sha(builder)==module['builder_sha256']and sha(source/'sources.json')==module['source_meta_sha256']
assert all(sha(source/n)==v['sha256']for n,v in module['sources']['files'].items())
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('DATE_INTERVAL_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
