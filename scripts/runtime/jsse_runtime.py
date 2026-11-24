"""Validate the source-owned legacy JSSE artifact before component packaging."""
from pathlib import Path
import hashlib,json,zipfile

def validate_jsse(directory,repo):
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    source=repo/'scripts/runtime/jsse-compat';expected=json.loads((source/'sources.json').read_text())
    value=json.loads((directory/'manifest.json').read_text())
    assert value['schema']=='saildroid-jsse-compat-api29-v1'
    assert value['source']==expected and value['source_manifest_sha256']==sha(source/'sources.json')
    assert value['baseline_classes_sha256']=='37c6bdf7e937c6d4b9938512e9655f5c58544de5d42de7300cff7b21c21cbe83'
    assert value['original_class_count']==73 and value['existing_other_classfiles_unchanged']==68
    assert value['added_or_removed_classfiles']==0 and value['native_binaries_changed']is False
    assert set(value['changed_classfiles'])=={name.removesuffix('.java')+'.class'for name in expected['files']}
    assert value['file']=='wolfssljni-hostdex.jar'and sha(directory/value['file'])==value['sha256']
    assert sha(directory/'classes.jar')==value['classes_sha256']and sha(directory/'NOTICE')==value['notice_sha256']
    with zipfile.ZipFile(directory/'classes.jar')as archive:
        assert len([name for name in archive.namelist()if name.endswith('.class')])==73
    for name,entry in expected['files'].items():
        assert sha(source/name)==entry['sha256']and sha(repo/entry['baseline_source'])==entry['baseline_sha256']
        if 'upstream_algorithm'in entry:assert sha(source/entry['upstream_algorithm'])==entry['upstream_sha256']
    return value
