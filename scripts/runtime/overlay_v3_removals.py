"""V3 cleanup: preserve narrow CA validation, permit one explicit TZlookup relocation.

The caller includes ca_overlay_removals.py first. All files are in a NEW release;
no predecessor or active runtime is modified. Validate every declaration and
actual destination before unlinking anything.
"""
import copy

def validate_v3_removals(meta,predecessor):
    assert meta['schema']=='saildroid-native-overlay-v3'
    transition=meta['release_file_cleanup'];assert transition['schema']=='saildroid-timezone-file-relocation-v1'
    removed=meta['remove_files'];ca_names=set(meta['ca_alias_cleanup']['certificates']);name='usr/share/zoneinfo/tzlookup.xml'
    assert set(removed)==ca_names|{name}and set(transition['relocations'])=={name}
    view=copy.deepcopy(meta);view['schema']='saildroid-native-overlay-v2';view['remove_files']={n:removed[n]for n in ca_names}
    validate_ca_removals(view,predecessor)
    move=transition['relocations'][name];entry=removed[name]
    assert move['old_entry']==entry and move['target']=='apex/com.android.runtime.debug/etc/tz/tzlookup.xml'
    assert move['target_entry']==meta['install_manifest']['files'][move['target']]==meta['changes'][move['target']]
    assert name not in meta['install_manifest']['files']and name not in meta['changes']and name not in meta['install_manifest']['symlinks']
    for path in [name,move['target']]:
        parts=Path(path).parts;assert all(str(Path(*parts[:i]))not in meta['install_manifest']['symlinks']for i in range(1,len(parts)))
    if name in predecessor['files']:assert predecessor['files'][name]==entry
    else:assert name not in predecessor['symlinks']
    return view,name,move

def apply_v3_removals(root,meta,predecessor):
    assert os.getuid()==os.geteuid()==0
    root=Path(root);view,name,move=validate_v3_removals(meta,predecessor)
    ready=[]
    for n,entry in view['remove_files'].items():
        source=_regular(root,n,entry);target=meta['ca_alias_cleanup']['certificates'][n]['target'];_regular(root,target,meta['install_manifest']['files'][target]);ready.append(source)
    _regular(root,move['target'],move['target_entry'])
    old=root/name
    if name in predecessor['files']:ready.append(_regular(root,name,meta['remove_files'][name]))
    else:assert not old.exists()and not old.is_symlink()
    for p in ready:p.unlink()
    assert all(not(root/n).exists()and not(root/n).is_symlink()for n in meta['remove_files'])
    return len(ready)
