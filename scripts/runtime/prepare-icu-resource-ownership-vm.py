#!/usr/bin/env python3
"""Keep exact core-owned ICU resources once on the private boot class path.

The split standalone core/framework share the same ICU resource input. Preserve
the core copy and every class/native byte; remove only byte-identical duplicates
from the broader framework JARs. No application/test-specific selection.
"""
from pathlib import Path
import argparse,copy,hashlib,json,os,shutil,zipfile

p=argparse.ArgumentParser(description=__doc__)
for n in ['core-module','framework','output']:
    p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
cm=json.loads((a.core_module/'manifest.json').read_text())
assert cm['passed']and cm['schema']=='saildroid-runtime-utility-compat-v1'
core=a.core_module/'core-libart-hostdex.jar';assert sha(core)==cm['components']['core-libart']['sha256']
fm=json.loads((a.framework/'manifest.json').read_text())
assert not a.output.exists();a.output.mkdir(parents=True)
after=copy.deepcopy(fm);removed={};unchanged_class_dex={};kept={}
with zipfile.ZipFile(core)as z:
    resources={n:z.read(n)for n in z.namelist()if n.startswith('android/icu/')and not n.endswith(('.class','.dex','/'))}
assert 'android/icu/ICUConfig.properties'in resources
for name,entry in fm['files'].items():
    f=a.framework/name;assert sha(f)==entry['sha256']
    with zipfile.ZipFile(f)as z:
        assert len(z.namelist())==len(set(z.namelist()))
        common={n for n in z.namelist()if n in resources}
        assert all(z.read(n)==resources[n]for n in common),'Refuse to erase a differing resource'
        removed[name]={n:hashlib.sha256(resources[n]).hexdigest()for n in sorted(common)}
        target=a.output/name
        if not common:shutil.copyfile(f,target)
        else:
            with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED)as out:
                for item in z.infolist():
                    if item.filename not in common:out.writestr(item,z.read(item.filename))
        with zipfile.ZipFile(target)as out:
            assert set(z.namelist())-set(out.namelist())==common and not(set(out.namelist())-set(z.namelist()))
            assert all(z.read(n)==out.read(n)for n in out.namelist())
            unchanged_class_dex[name]=hashlib.sha256(out.read('classes.dex')).hexdigest()
        after['files'][name]['sha256']=sha(target)
        kept[name]=sorted(set(z.namelist())-common)
for n in {n for names in removed.values()for n in names}:
    assert after['resources'].pop(n)==hashlib.sha256(resources[n]).hexdigest()
shutil.copyfile(a.framework/'classes.jar',a.output/'classes.jar')
count=sum(map(len,removed.values()))
assert count==3607 and sum('android/icu/ICUConfig.properties'in m for m in removed.values())==1
provenance=dict(schema='saildroid-icu-resource-ownership-v1',scope='All apps; byte-identical ICU resources owned by private core-libart retained there and omitted only from broad framework resource copy. No class/native/ICU version/data content/test changes.',
    builder_sha256=sha(Path(__file__)),baseline_framework_manifest_sha256=sha(a.framework/'manifest.json'),core_module_manifest_sha256=sha(a.core_module/'manifest.json'),core_jar_sha256=sha(core),removed_framework_resources=removed,
    removed_duplicates=count,removed_duplicate_bytes=sum(len(resources[n])for m in removed.values()for n in m),remaining_framework_entries_byte_identical=True,all_dex_sha256=unchanged_class_dex)
after['resource_ownership']=provenance
(a.output/'manifest.json').write_text(json.dumps(after,indent=2)+'\n')
(a.output/'resource-ownership.json').write_text(json.dumps(provenance,indent=2)+'\n')
print('ICU_RESOURCE_OWNERSHIP=prepared|removed_exact_duplicates='+str(count)+'|all_class_native_data_bytes=retained|phone_changed=false')
