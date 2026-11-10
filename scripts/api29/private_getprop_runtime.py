"""Verify a repository-built property command and its unchanged native backend."""
from pathlib import Path
import hashlib,json,subprocess

def validate_getprop(directory,repo):
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    m=json.loads((directory/'manifest.json').read_text())
    assert m['schema']=='saildroid-private-getprop-v2'and m['backend_copied_unchanged']is True
    assert m['backend_build_from_reference_sources_claimed']is False and m['architecture']=='AArch64'
    assert sha(repo/'native/commands/private-getprop.cpp')==m['source_sha256']
    if 'host_product_source_sha256' in m:
        assert sha(repo/'native/compat/api29-hardware-properties.c')==m['host_product_source_sha256']
    for name,key in [('getprop','binary_sha256'),('libc_bio.so.0','property_backend_sha256'),('NOTICE','notice_sha256')]:
        p=directory/name;assert p.is_file()and not p.is_symlink()and sha(p)==m[key]
    for name in ['getprop','libc_bio.so.0']:
        header=subprocess.check_output(['readelf','-h',str(directory/name)],text=True)
        assert 'ELF64'in header and 'AArch64'in header
    for name,value in m['reference_source_hashes'].items():
        path=Path(name);assert not path.is_absolute()and '..'not in path.parts
        assert sha(repo/path)==value and sha(directory/'reference'/path.name)==value
    return m
