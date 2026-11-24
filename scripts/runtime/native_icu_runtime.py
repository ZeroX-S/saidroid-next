"""Validate the private Android 10 native ICU build before packaging it."""
from pathlib import Path
import hashlib
import json
import re
import subprocess


FILES = {'libjavacore.so', 'libicuuc.so.63', 'libicui18n.so.63', 'libicudata.so.63'}
SOURCE_COMMIT = '38264f18fb2fa568bcffff2e0c40e545c1384311'
PHONE_BASELINE = '4a4934b2a5a2b8ca328325e18a84413b13ed9d564293ae64ce5c360de274542a'


def exported_symbols(file):
    output = subprocess.check_output(['nm', '-D', '--defined-only', str(file)], text=True)
    return {parts[-1]: parts[-2] for line in output.splitlines()
            if len(parts := line.split()) >= 3}


def validate_native_icu(directory, repo, product_manifest):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['schema'] == 'saildroid-native-icu-v1'
    assert manifest['source_commit'] == SOURCE_COMMIT
    source = directory / 'source-manifest.json'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['source_manifest_sha256']
    assert json.loads(source.read_text())['commit'] == SOURCE_COMMIT
    assert manifest['baseline_javacore_sha256'] == PHONE_BASELINE
    assert manifest['actual_native_version'] == [63, 2, 0, 0]
    assert manifest['actual_native_unicode_version'] == [11, 0, 0, 0]
    contract = manifest['actual_core_contract']
    assert contract['results'] == [dict(case='before74', passed=False, expected=False),
                                   dict(case='private63', passed=True, expected=True)]
    expected_sources = {'scripts/runtime/tests/icu/IcuCompatibilityContract.java',
                        'scripts/runtime/tests/icu/IcuNativeCoreContract.java'}
    assert set(contract['sources']) == expected_sources
    for name, digest in contract['sources'].items():
        assert hashlib.sha256((repo / name).read_bytes()).hexdigest() == digest
    # This source change makes Java's bootstrap native library lookup resolve
    # the component's libjavacore before the external legacy /home/art library.
    host = repo / 'native/host/host-entry.cpp'
    assert product_manifest['native_sources']['native/host/host-entry.cpp'] == hashlib.sha256(host.read_bytes()).hexdigest()
    assert '"-Djava.library.path=" + (root / "lib").string() + ":"' in host.read_text()
    assert set(manifest['files']) == FILES
    dependencies = {}
    for name, entry in manifest['files'].items():
        file = directory / name
        assert file.is_file() and not file.is_symlink()
        assert hashlib.sha256(file.read_bytes()).hexdigest() == entry['sha256']
        assert file.stat().st_size == entry['bytes']
        header = subprocess.check_output(['readelf', '-h', str(file)], text=True)
        assert 'AArch64' in header and 'ELF64' in header
        dynamic = subprocess.check_output(['readelf', '-d', str(file)], text=True)
        assert dynamic == entry['dynamic'], 'Unrecorded ELF dependency change: ' + name
        assert re.findall(r'\(SONAME\).*\[([^]]+)\]', dynamic) == [name]
        dependencies[name] = set(re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic))
        assert not any('.so.74' in dependency for dependency in dependencies[name])
        assert {dependency for dependency in dependencies[name] if dependency.startswith('libicu')} <= FILES
    assert {'libicuuc.so.63', 'libicui18n.so.63'} <= dependencies['libjavacore.so']
    assert 'libicudata.so.63' in dependencies['libicuuc.so.63']
    assert 'libicuuc.so.63' in dependencies['libicui18n.so.63']
    assert 'u_getVersion_63' in exported_symbols(directory / 'libicuuc.so.63')
    assert 'icudt63_dat' in exported_symbols(directory / 'libicudata.so.63')
    boundary = manifest['actual_phone_baseline_boundary']
    assert boundary['phone_baseline_sha256'] == PHONE_BASELINE
    assert boundary['new_sha256'] == manifest['files']['libjavacore.so']['sha256']
    old = manifest['phone_baseline_exports']
    new = exported_symbols(directory / 'libjavacore.so')
    public = lambda symbols: {k: v for k, v in symbols.items() if not k.startswith('_Z')}
    assert public(old) == public(new)
    assert {name.replace('icu_74', 'icu_63'): kind for name, kind in old.items()} == new
    assert sorted(set(old) - set(new)) == boundary['removed']
    assert sorted(set(new) - set(old)) == boundary['added']
    assert manifest['public_c_jni_exports_unchanged'] is True
    change = manifest['private_cpp_namespace_change']
    assert change['before'] == 'icu_74' and change['after'] == 'icu_63'
    assert change['no_existing_private_runtime_imports'] is True
    assert change['removed'] == boundary['removed'] and change['added'] == boundary['added']
    if flags := manifest.get('socket_flags_api29'):
        assert flags['fields'] == ['SOCK_CLOEXEC', 'SOCK_NONBLOCK']
        assert flags['native_library_sha256'] == manifest['files']['libjavacore.so']['sha256']
        assert flags['native_boundary']['symbols_unchanged'] is True
        assert flags['native_boundary']['shared_tree_unchanged'] is True
        assert flags['native_boundary']['library_sha256'] == flags['native_library_sha256']
        for name, digest in flags['sources'].items():
            assert name in {
                'native/compat/patches/libcore-socket-flags.patch',
                'scripts/runtime/core/socket-flags/android/system/OsConstants.java',
                'scripts/runtime/tests/network/SocketFlagsContract.java',
                'scripts/runtime/tests/network/OriginalReliableFdRunner.java',
                'scripts/runtime/tests/network/NativeNetworkRegistrationContract.java',
            }
            assert hashlib.sha256((repo / name).read_bytes()).hexdigest() == digest
        assert len(flags['sources']) == 5
        assert flags['kernel_contract']['results'] == [
            dict(case='before', target_sdk=29, passed=False, expected=False),
            dict(case='after', target_sdk=29, passed=True, expected=True),
        ]
        rows = flags['original_fd_contract']['results']
        assert len(rows) == 2
        assert rows[0]['case'] == 'before' and rows[0]['tests'] == rows[0]['failures'] == 8
        assert rows[1]['case'] == 'flags' and rows[1]['tests'] == 8 and rows[1]['failures'] == 0
        assert rows[1]['passed'] and not rows[1]['test_registration_helper_used']
    return manifest
