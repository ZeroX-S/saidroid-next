"""Validate the real private fdlibm companion; never override host libc math."""
from pathlib import Path
import hashlib
import json
import re
import subprocess


def validate_strictmath(directory, repo):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['schema'] == 'saildroid-fdlibm-native-v1' and manifest['api'] == 29
    assert manifest['original_sources_unchanged'] is True
    assert manifest['original_phone_openjdk_unchanged'] is True
    assert manifest['host_libc_math_unchanged'] is True
    assert manifest['builder_sha256'] == hashlib.sha256(
        (repo / 'native/compat/build-fdlibm-helper-vm.py').read_bytes()).hexdigest()
    assert {'-D_IEEE_LIBM', '-D__LITTLE_ENDIAN', '-fno-strict-aliasing',
            '-ffloat-store', '-fno-fast-math', '-ffp-contract=off'} <= set(manifest['flags'])
    assert '#define __BYTE_ORDER__ __ORDER_LITTLE_ENDIAN__' in manifest['compiler_macros']
    for name, sha in manifest['sources'].items():
        assert Path(name).name == name
        assert hashlib.sha256((repo / 'third_party/art-standalone/external/fdlibm' / name
                              ).read_bytes()).hexdigest() == sha
    assert sum(name.endswith('.c') for name in manifest['sources']) == 80
    assert manifest['file'] == 'libsdstrictmath-fdlibm.so'
    file = directory / manifest['file']
    assert file.is_file() and not file.is_symlink()
    assert hashlib.sha256(file.read_bytes()).hexdigest() == manifest['sha256']
    assert file.stat().st_size == manifest['bytes']
    header = subprocess.check_output(['readelf', '-h', str(file)], text=True)
    assert 'AArch64' in header and 'ELF64' in header and 'little endian' in header
    symbols = sorted(line.split()[-1] for line in subprocess.check_output(
        ['nm', '-D', '--defined-only', str(file)], text=True).splitlines() if line.split())
    assert symbols == manifest['exported_symbols']
    assert len(symbols) == 50 and all(name.startswith('ieee_') for name in symbols)
    dynamic = subprocess.check_output(['readelf', '-d', str(file)], text=True)
    assert dynamic == manifest['dynamic']
    assert re.findall(r'\(SONAME\).*\[([^]]+)\]', dynamic) == [manifest['file']]
    assert set(re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic)) <= {
        'libc.so.6', 'libm.so.6', 'ld-linux-aarch64.so.1'}
    assert hashlib.sha256((directory / 'compile-commands.json').read_bytes()
                          ).hexdigest() == manifest['compile_commands_sha256']
    assert hashlib.sha256((directory / 'NOTICE').read_bytes()).hexdigest() == manifest['notice_sha256']
    return manifest
