"""Narrow v2-overlay cleanup of byte-identical legacy CA aliases in a NEW root.

Never deletes a certificate from the predecessor or changes a trust-anchor byte.
All declarations and every source/target are checked before the first unlink.
"""
from pathlib import Path
import hashlib,os,re,stat

def validate_ca_removals(meta, predecessor):
    assert meta['schema']=='saildroid-native-overlay-v2'
    removed=meta['remove_files'];certs=meta['ca_alias_cleanup']['certificates']
    assert 0<len(removed)==len(certs)<=1024 and set(removed)==set(certs)
    files=meta['install_manifest']['files'];links=meta['install_manifest']['symlinks']
    targets=set()
    for name,entry in removed.items():
        assert re.fullmatch(r'system/etc/security/cacerts/[a-f0-9]{64}\.pem',name)
        assert predecessor['files'][name]==entry
        assert name not in files and name not in links and name not in meta['changes']
        target=certs[name]['target']
        assert re.fullmatch(r'system/etc/security/cacerts/[a-f0-9]{8}\.[0-9]+',target)
        assert target not in targets;targets.add(target)
        assert certs[name]['sha256']==entry['sha256']==files[target]['sha256']
        assert target not in links and target in meta['changes']
        parts=Path(name).parts;target_parts=Path(target).parts
        assert all(str(Path(*parts[:i]))not in links for i in range(1,len(parts)))
        assert all(str(Path(*target_parts[:i]))not in links for i in range(1,len(target_parts)))
    return removed

def _regular(root,name,entry):
    assert root.is_absolute()and not root.is_symlink()
    assert root.stat().st_uid==0 and stat.S_ISDIR(root.stat().st_mode)
    assert not(root.stat().st_mode&0o022)
    path=root
    for part in Path(name).parts[:-1]:
        path=path/part;info=path.lstat()
        assert stat.S_ISDIR(info.st_mode)and info.st_uid==0 and not(info.st_mode&0o022)
    file=root/name;info=file.lstat()
    assert stat.S_ISREG(info.st_mode)and info.st_uid==0
    assert stat.S_IMODE(info.st_mode)==entry['mode']and info.st_size==entry['size']
    assert hashlib.sha256(file.read_bytes()).hexdigest()==entry['sha256']
    return file

def apply_ca_removals(root,meta,predecessor):
    assert os.getuid()==0 and os.geteuid()==0
    root=Path(root);removed=validate_ca_removals(meta,predecessor);ready=[]
    for name,entry in removed.items():
        source=_regular(root,name,entry);target=meta['ca_alias_cleanup']['certificates'][name]['target']
        _regular(root,target,meta['install_manifest']['files'][target]);ready.append(source)
    for file in ready:file.unlink()
    assert all(not(root/n).exists()and not(root/n).is_symlink()for n in removed)
    return len(ready)
