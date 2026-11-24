"""Validate the original Character native implementation and its ICU63 link."""
from pathlib import Path
import hashlib
import json
import re
import subprocess


BASELINE_SHA256 = 'f59985a283b244f2e0001a246b3d33933b2f817c89ee1c652331ad198228ce8a'
SOURCE = 'libcore/ojluni/src/main/native/Character.cpp'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_character(directory, repo, native_icu_manifest):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['schema'] == 'saildroid-character-native-v1' and manifest['api'] == 29
    assert manifest['file'] == 'libsdcharacter-icu63.so'
    assert manifest['source'] == SOURCE and manifest['source_unmodified'] is True
    assert manifest['original_jni_registration_unchanged'] is True
    assert manifest['shared_runtime_unchanged'] is True
    assert manifest['baseline_openjdk_sha256'] == BASELINE_SHA256
    assert manifest['builder_sha256'] == digest(repo / 'native/compat/build-character-helper-vm.py')
    assert manifest['source_sha256'] == digest(repo / 'third_party/art-standalone' / SOURCE)
    assert native_icu_manifest['actual_native_version'] == [63, 2, 0, 0]
    assert manifest['icu_library_sha256'] == native_icu_manifest['files']['libicuuc.so.63']['sha256']
    library = directory / manifest['file']
    assert library.is_file() and not library.is_symlink()
    assert digest(library) == manifest['sha256'] and library.stat().st_size == manifest['bytes']
    header = subprocess.check_output(['readelf', '-h', str(library)], text=True)
    assert 'AArch64' in header and 'ELF64' in header and 'little endian' in header
    symbols = sorted(line.split()[-1] for line in subprocess.check_output(
        ['nm', '-D', '--defined-only', str(library)], text=True).splitlines() if line.split())
    assert symbols == manifest['exported_symbols'] and len(symbols) == 23
    assert all(re.fullmatch(r'_Z\d+Character_.*', name) for name in symbols)
    dynamic = subprocess.check_output(['readelf', '-d', str(library)], text=True)
    assert dynamic == manifest['dynamic']
    assert re.findall(r'\(SONAME\).*\[([^]]+)\]', dynamic) == [manifest['file']]
    needed = set(re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic))
    assert 'libicuuc.so.63' in needed
    assert needed <= {'libicuuc.so.63', 'libc.so.6', 'libm.so.6', 'ld-linux-aarch64.so.1'}
    assert manifest['dependencies']
    for name, sha in manifest['dependencies'].items():
        assert digest(Path(name)) == sha, 'Character compilation input changed: ' + name
    assert digest(directory / 'compile-commands.json') == manifest['compile_commands_sha256']
    assert digest(directory / 'NOTICE') == manifest['notice_sha256']
    return manifest
