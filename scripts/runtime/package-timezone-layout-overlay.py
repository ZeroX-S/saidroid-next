#!/usr/bin/env python3
"""Package verified real Android10 timezone data/module paths and native launch environment."""
from pathlib import Path
import argparse,copy,hashlib,importlib.util,json,os,shutil,stat,subprocess,tarfile,zipfile
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline','module','host','baseline-encoded','encoded','boot','data','icu-overlay','output']:p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--expected-baseline-sha256',required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256
before=json.loads((a.baseline/'overlay.json').read_text());assert before['schema']=='saildroid-native-overlay-v2'and before['api']==29
oldroot=a.baseline/'payload';full=before['install_manifest']
for n,v in before['changes'].items():
 f=oldroot/n;assert not Path(n).is_absolute()and'..'not in Path(n).parts
 assert f.is_file()and not f.is_symlink()and sha(f)==v['sha256']and f.stat().st_size==v['size']and stat.S_IMODE(f.stat().st_mode)==v['mode']and full['files'][n]==v
module=json.loads((a.module/'manifest.json').read_text());assert module['schema']=='saildroid-timezone-layout-compat-v1'and module['passed']
source=repo/'scripts/runtime/core/timezone-layout-compat';builder=repo/'scripts/runtime/build-timezone-layout-compat-vm.py';assert sha(source/'sources.json')==module['source_meta_sha256']and sha(builder)==module['builder_sha256']
for n,v in module['sources']['files'].items():assert sha(source/n)==v['sha256']and sha(repo/v['baseline_source'])==v['baseline_sha256']and sha(repo/v['reference'])==v['reference_sha256']
core=module['components']['core-libart'];assert sha(a.module/'core-libart-hostdex.jar')==core['sha256']and sha(a.module/'core-libart-classes.jar')==core['class_jar_sha256']and core['all_existing_member_flags_preserved']and core['all_existing_members_and_native_declarations_preserved']and not core['added_members']
runtime=json.loads((oldroot/'runtime.json').read_text());old=json.loads((oldroot/'share/build/hiddenapi-manifest.json').read_text());encoded=json.loads((a.encoded/'manifest.json').read_text());assert json.loads((a.baseline_encoded/'manifest.json').read_text())==old
for k in ['schema','canonical_flags_sha256','tool_sha256','public_library_apis','unknown_policy']:assert encoded[k]==old[k]
assert encoded['files'].keys()==old['files'].keys()==set(runtime['boot_jars'])|{'lib/runtime.jar'}
spec=importlib.util.spec_from_file_location('timezone_package_encoder',repo/'scripts/runtime/encode-hiddenapi-vm.py');enc=importlib.util.module_from_spec(spec);spec.loader.exec_module(enc);changed=[]
for n,v in encoded['files'].items():
 assert sha(a.encoded/n)==v['sha256']and v['executable_code_unchanged']and sha(a.baseline_encoded/n)==old['files'][n]['sha256']==full['files'][n]['sha256']
 with zipfile.ZipFile(a.baseline_encoded/n)as z:am,_=enc.dex_members(z.read('classes.dex'));ar={n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()if not n.endswith('.dex')}
 with zipfile.ZipFile(a.encoded/n)as z:bm,_=enc.dex_members(z.read('classes.dex'));br={n:hashlib.sha256(z.read(n)).hexdigest()for n in z.namelist()if not n.endswith('.dex')}
 assert ar==br and am.keys()==bm.keys()and all(am[k][0]==bm[k][0]for k in am)
 if old['files'][n]['sha256']!=v['sha256']:changed.append(n)
assert changed==['java/dex/art/core-libart.jar']and encoded['files'][changed[0]]['source_sha256']==core['sha256']
assert(a.baseline_encoded/'effective-api-flags.csv').read_bytes()==(a.encoded/'effective-api-flags.csv').read_bytes()
images=json.loads((a.boot/'manifest.json').read_text());recipe=json.loads((a.boot/'recipe.json').read_text());assert len(images)==30 and images.keys()==json.loads((oldroot/'share/build/boot-image-manifest.json').read_text()).keys()
assert {Path(n).name:v for n,v in recipe['files'].items()}=={Path(n).name:encoded['files'][n]['sha256']for n in runtime['boot_jars']if '/framework29-'not in n}and all(sha(a.boot/n)==h for n,h in images.items())
host=json.loads((a.host/'manifest.json').read_text());hsource=repo/'native/compat/timezone-layout';hbuilder=repo/'native/compat/build-timezone-env-vm.py';hmeta=json.loads((hsource/'sources.json').read_text())
assert host['schema']=='saildroid-timezone-env-native-v1'and host['passed']and host['baseline_rebuild_byte_identical']and host['all_dynamic_symbols_identical']and host['needed_identical']
assert sha(hbuilder)==host['builder_sha256']and sha(hsource/'sources.json')==host['source_meta_sha256']and sha(hsource/'host-entry.cpp')==host['source_sha256']==hmeta['sha256']and sha(repo/hmeta['baseline_source'])==hmeta['baseline_sha256']
assert all(sha(repo/n)==h for n,h in host['sources'].items())and sha(a.host/'saildroid-host')==host['library_sha256']and host['baseline_library_sha256']==full['files']['libexec/saildroid-host']['sha256']
symbols=lambda f:set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
assert symbols(a.host/'saildroid-host')==symbols(oldroot/'libexec/saildroid-host')
data=json.loads((a.data/'manifest.json').read_text());assert all(sha(a.data/n)==v['sha256']and(a.data/n).stat().st_size==v['bytes']for n,v in data['files'].items())
overlay=json.loads((a.icu_overlay/'manifest.json').read_text());license=json.loads((a.icu_overlay/'license-source.json').read_text());assert sha(a.icu_overlay/'icu_tzdata.dat')==overlay['sha256']and sha(a.icu_overlay/'LICENSE')==license['sha256']
assert(a.data/'tzdata').read_bytes().startswith(b'tzdata2019c\0')and b'ianaversion="2019c"'in(a.data/'tzlookup.xml').read_bytes()and(a.data/'tz_version').read_bytes()==b'003.001|2019c|001'
b=repo/'build/evidence/cts-frame-repair-20261031';proofs=[b/n for n in ['original-timezone223-paired-v2-audit.json','timezone223-own-contract-v2.json','timezone223-layout-env-v2.json']];original,own,layout=[json.loads(f.read_text())for f in proofs]
assert original['accepted_comparison']and original['tests']==original['after_pass']==13 and original['before_fail']==6 and original['after_fail']==0 and not original['full_module_passed']and sha(b/'original-timezone223-selected-v2.json')==original['raw_paired_sha256']
assert own['passed']and'real_offset_samples=1520|'in own['marker']and'version=2019c|'in own['marker']and own['source_sha256']==sha(repo/'scripts/runtime/tests/timezone-layout/TimeZoneLayoutContract.java')and own['source_meta_sha256']==sha(source/'sources.json')
assert layout['passed']and layout['host_entry_source_sha256']==host['source_sha256']and layout['fixture_source_sha256']==sha(repo/'native/compat/tests/timezone/environment.cpp')and layout['dataset_manifest_sha256']==sha(a.data/'manifest.json')and layout['icu_timezone_overlay_manifest_sha256']==sha(a.icu_overlay/'manifest.json')
assert own['layout_manifest_sha256']==original['actual_layout_manifest_sha256']==sha(proofs[2])and all(sha(Path(layout['root'])/n)==h for n,h in layout['files'].items())
assert own['actual_core_libart_sha256']==original['actual_new_core_libart_sha256']==encoded['files']['java/dex/art/core-libart.jar']['sha256']and own['actual_core_oj_sha256']==original['actual_new_core_oj_sha256']==full['files']['java/dex/art/core-oj.jar']['sha256']
assert own['actual_boot_manifest_sha256']==original['actual_new_boot_manifest_sha256']==sha(a.boot/'manifest.json')and own['actual_encoded_manifest_sha256']==original['actual_new_encoded_manifest_sha256']==sha(a.encoded/'manifest.json')
assert own['actual_art_sha256']==original['actual_art_sha256']==full['files']['lib/libart.so']['sha256']and own['actual_new_javacore_sha256']==original['actual_javacore_sha256']==full['files']['lib/libjavacore.so']['sha256']and own['actual_native_host_sha256']==original['actual_native_host_sha256']==full['files']['lib/libsdhost29.so']['sha256']and own['actual_new_runtime_sha256']==full['files']['lib/runtime.jar']['sha256']
assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'payload';shutil.copytree(oldroot,root);root.chmod(0o755)
for d in root.rglob('*'):
 if d.is_dir()and not d.is_symlink():d.chmod(0o755)
after=copy.deepcopy(before);manifest,changes,updated=after['install_manifest'],after['changes'],[]
def install(f,n,mode=0o644):
 target=root/n;target.parent.mkdir(parents=True,exist_ok=True);assert not target.is_symlink();shutil.copyfile(f,target);target.chmod(mode);v=dict(sha256=sha(target),size=target.stat().st_size,mode=mode);manifest['files'][n]=changes[n]=v;updated.append(n)
install(a.host/'saildroid-host','libexec/saildroid-host',full['files']['libexec/saildroid-host']['mode'])
install(a.encoded/'java/dex/art/core-libart.jar','java/dex/art/core-libart.jar',full['files']['java/dex/art/core-libart.jar']['mode']);install(a.encoded/'manifest.json','share/build/hiddenapi-manifest.json')
for n in images:install(a.boot/n,'system/framework/'+n,full['files']['system/framework/'+n]['mode'])
install(a.boot/'manifest.json','share/build/boot-image-manifest.json')
for n,h in layout['files'].items():
 if n.startswith('usr/icu/'):
  assert full['files'][n]['sha256']==h;continue
 src=a.icu_overlay/'icu_tzdata.dat'if n.endswith('icu_tzdata.dat')else a.data/Path(n).name
 assert sha(src)==h;install(src,n,full['files'].get(n,{}).get('mode',0o644))
removed='usr/share/zoneinfo/tzlookup.xml';assert removed in manifest['files'];(root/removed).unlink();manifest['files'].pop(removed);changes.pop(removed,None)
assert removed not in after['remove_files'];after['remove_files'][removed]=copy.deepcopy(full['files'][removed])
for f,n in [(a.module/'manifest.json','core-manifest.json'),(source/'sources.json','sources.json'),(builder,'builder.py'),(a.host/'manifest.json','host-manifest.json'),(hsource/'sources.json','host-sources.json'),(hsource/'host-entry.cpp','host-entry.cpp'),(hbuilder,'host-builder.py'),(Path(__file__),'packager.py'),(repo/'native/compat/tests/timezone/environment.cpp','tests/environment.cpp'),(repo/'scripts/runtime/tests/timezone-layout/TimeZoneLayoutContract.java','tests/TimeZoneLayoutContract.java')]:install(f,'share/build/timezone-layout/'+n)
for n,v in module['sources']['files'].items():install(source/n,'share/build/timezone-layout/sources/'+n);install(repo/v['reference'],'share/build/timezone-layout/references/'+n)
for name in data['files']:install(a.data/name,'share/build/timezone-layout/data-source/'+name)
install(a.data/'manifest.json','share/build/timezone-layout/data-source/manifest.json')
for n in ['manifest.json','LICENSE','license-source.json']:install(a.icu_overlay/n,'share/build/timezone-layout/icu-overlay-source/'+n)
for f in proofs:install(f,'share/build/timezone-layout/evidence/'+f.name)
runtime['hidden_api']['manifest_sha256']=sha(a.encoded/'manifest.json');runtime['boot_image']['manifest_sha256']=sha(a.boot/'manifest.json')
runtime['timezone_layout']=dict(schema='saildroid-timezone-layout-v1',scope='All ARTroles and apps; actual originalAndroid10r16 timezone2019c+ICUoverlay, canonical private runtime/TZmodule paths and legacy path delegation. Standard data-override precedence retained; no clock/version spoof.',core_module_manifest_sha256=sha(a.module/'manifest.json'),host_manifest_sha256=sha(a.host/'manifest.json'),native_host_sha256=host['library_sha256'],dataset_manifest_sha256=sha(a.data/'manifest.json'),icu_overlay_manifest_sha256=sha(a.icu_overlay/'manifest.json'),original_selected_tests=13,original_selected_failures=0,own_offset_samples=1520,canonical_zoneinfo_32bit_range_retained=True,full_module_passed=False)
tmp=a.output/'runtime.json';tmp.write_text(json.dumps(runtime,indent=2)+'\n');install(tmp,'runtime.json');tmp.unlink()
manifest['bytes']=sum(v['size']for v in manifest['files'].values());assert set(full['files'])-set(manifest['files'])=={removed}and manifest['symlinks']==full['symlinks']
for k in ['ca_alias_cleanup','product_manifest']:assert before[k]==after[k]
assert set(after['remove_files'])==set(before['remove_files'])|{removed}
assert all(manifest['files'][n]==v for n,v in full['files'].items()if n not in updated and n!=removed)
assert all(sha(root/n)==v['sha256']and stat.S_IMODE((root/n).stat().st_mode)==v['mode']for n,v in changes.items())
after['timezone_layout_overlay']=dict(schema='saildroid-timezone-layout-overlay-v1',baseline_archive_sha256=a.expected_baseline_sha256,updated_files=sorted(updated),removed_files=[removed],original_selected_tests=13,original_selected_failures=0,all_other_native_art_runtime_framework_media_manager_trust_bytes_unchanged=True,phone_staged=False)
(a.output/'overlay.json').write_text(json.dumps(after,indent=2)+'\n')
with tarfile.open(a.output/'native-overlay.tar.gz.pending','w:gz')as archive:archive.add(root,arcname='payload');archive.add(a.output/'overlay.json',arcname='overlay.json')
assert sha(a.baseline/'native-overlay.tar.gz')==a.expected_baseline_sha256 and sha(a.host/'saildroid-host')==host['library_sha256']and sha(source/'sources.json')==module['source_meta_sha256']and sha(builder)==module['builder_sha256']and sha(hbuilder)==host['builder_sha256']
(a.output/'native-overlay.tar.gz.pending').replace(a.output/'native-overlay.tar.gz')
print('TIMEZONE_LAYOUT_OVERLAY=packaged|sha256='+sha(a.output/'native-overlay.tar.gz')+'|phone_staged=false')
