#!/usr/bin/env python3
"""Package app-private Java temporary-directory startup configuration over a pinned current component.

Only the native host, runtime provenance and new build evidence change. All
Java/core/native implementations, active images, APKs and cleanup rules stay
identical. Original coupled-state result is 144/145, not a full-module pass.
"""
from pathlib import Path
import argparse, copy, hashlib, json, os, shutil, stat, tarfile

p = argparse.ArgumentParser(description=__doc__)
for name in ['baseline', 'host', 'output']:
    p.add_argument('--' + name, type=Path, required=True)
p.add_argument('--expected-baseline-sha256', required=True)
a = p.parse_args(); os.umask(0o022)
repo = Path(__file__).resolve().parents[2]
b = repo / 'build/evidence/cts-frame-repair-20261031'
sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(a.baseline / 'native-overlay.tar.gz') == a.expected_baseline_sha256
before = json.loads((a.baseline / 'overlay.json').read_text())
assert before['schema'] == 'saildroid-native-overlay-v3' and before['api'] == 29
oldroot = a.baseline / 'payload'; full = before['install_manifest']
for name, value in before['changes'].items():
    path = Path(name); assert not path.is_absolute() and '..' not in path.parts
    file = oldroot / name
    assert file.is_file() and not file.is_symlink() and sha(file) == value['sha256']
    assert stat.S_IMODE(file.stat().st_mode) == value['mode'] and file.stat().st_size == value['size']
    assert full['files'][name] == value
host = json.loads((a.host / 'manifest.json').read_text())
builder = repo / 'native/compat/build-application-temp-startup-vm.py'
patch = repo / 'native/compat/application-temp-startup/host-entry.patch'
assert host['schema'] == 'saildroid-application-temp-startup-v1' and host['passed']
assert all(host[k] for k in ['unmodified_host_reproduced_byte_identical', 'all_dynamic_symbols_identical', 'needed_identical'])
assert host['builder_sha256'] == sha(builder) and host['patch_sha256'] == sha(patch)
assert host['baseline_binary_sha256'] == full['files']['libexec/saildroid-host']['sha256']
assert sha(a.host / 'saildroid-host') == host['binary_sha256']
assert host['sources_before'] == {'host-entry.cpp': sha(oldroot / 'share/build/application-cache-startup/host-entry.cpp')}
assert host['sources_after'] == {'host-entry.cpp': sha(a.host / 'source/host-entry.cpp')}
proofs = [b / n for n in ['original-temp-startup237-paired-v1-audit.json', 'application-temp-startup237-own-contract-v1.json']]
original, own = [json.loads(f.read_text()) for f in proofs]
assert original['passed'] and original['tests'] == 145 and original['same_ordered_original_ids']
assert original['before_counts'] == dict(started=145, passed=128, failed=17)
assert original['after_counts'] == dict(started=145, passed=144, failed=1) and len(original['fixed_tests']) == 16
assert original['remaining_failures'] == ['libcore.java.lang.SystemTest#testSystemProperties_mutable']
assert not original['full_module_passed'] and not original['formal_module_acceptance']
assert original['native_build_manifest_sha256'] == sha(a.host / 'manifest.json')
for label in ['before', 'after']:
    assert original[label + '_sha256'] == sha(b / ('original-temp-startup237-' + label + '-v1.json'))
raw = json.loads((b / 'original-temp-startup237-after-v1.json').read_text())
assert raw['actual_client_runtime_maps']
for name, digest in raw['actual_client_runtime_maps'].items():
    relative = str(Path(name).relative_to('/var/tmp/saidroid-application-cache-startup236-v1-formal-vm-component/root'))
    assert digest == full['files'][relative]['sha256']
contract = repo / 'scripts/runtime/tests/application-cache-startup/ApplicationTempStartupContract.java'
assert own['passed'] and own['contract_source_sha256'] == sha(contract)
assert [r['mode'] for r in own['results']] == ['first-app', 'second-app']
assert all('uid=65534' in r['marker'] and r['cross_uid_read_denied'] for r in own['results'])
assert not a.output.exists(); a.output.mkdir(parents=True)
root = a.output / 'payload'; shutil.copytree(oldroot, root); root.chmod(0o755)
for directory in root.rglob('*'):
    if directory.is_dir() and not directory.is_symlink(): directory.chmod(0o755)
after = copy.deepcopy(before); manifest, changes = after['install_manifest'], after['changes']; updated = []
def install(file, name, mode=0o644):
    target = root / name; target.parent.mkdir(parents=True, exist_ok=True); assert not target.is_symlink()
    shutil.copyfile(file, target); target.chmod(mode)
    value = dict(sha256=sha(target), size=target.stat().st_size, mode=mode)
    manifest['files'][name] = changes[name] = value; updated.append(name)
install(a.host / 'saildroid-host', 'libexec/saildroid-host', full['files']['libexec/saildroid-host']['mode'])
for file, name in [(a.host / 'manifest.json', 'manifest.json'), (a.host / 'source/host-entry.cpp', 'host-entry.cpp'),
                   (patch, 'host-entry.patch'), (builder, 'builder.py'), (Path(__file__), 'packager.py'),
                   (contract, 'tests/ApplicationTempStartupContract.java'),
                   (b / 'TempStartup237ContractRunner.java', 'tests/ContractRunner.java'),
                   (b / 'audit-original-temp-startup237-paired-v1.py', 'tests/audit-paired.py')]:
    install(file, 'share/build/application-temp-startup/' + name)
for file in proofs: install(file, 'share/build/application-temp-startup/evidence/' + file.name)
runtime = json.loads((oldroot / 'runtime.json').read_text())
runtime['application_temp_startup'] = dict(schema=host['schema'], host_manifest_sha256=sha(a.host / 'manifest.json'),
    configuration='-Djava.io.tmpdir=<actual-app-data>/cache',
    scope='Every ordinary app and declared app process uses its actual private cache for default Java temporary files; canonical startup property semantics, user.home remains mutable.',
    original_coupled_tests=145, original_coupled_passed=144, original_coupled_failed=1,
    original_sax_tests_fixed=16, own_applications=2, cross_uid_temp_reads_denied=True, phone_executed=False, full_module_passed=False)
pending = a.output / 'runtime.pending.json'; pending.write_text(json.dumps(runtime, indent=2) + '\n')
install(pending, 'runtime.json'); pending.unlink()
manifest['bytes'] = sum(v['size'] for v in manifest['files'].values())
assert set(full['files']) <= set(manifest['files']) and manifest['symlinks'] == full['symlinks']
assert all(manifest['files'][n] == v for n, v in full['files'].items() if n not in updated)
assert {n for n in updated if n in full['files']} == {'libexec/saildroid-host', 'runtime.json'}
for key in ['remove_files', 'ca_alias_cleanup', 'product_manifest', 'release_file_cleanup']: assert after[key] == before[key]
assert all(sha(root / n) == v['sha256'] and stat.S_IMODE((root / n).stat().st_mode) == v['mode'] for n, v in changes.items())
after['application_temp_startup_overlay'] = dict(schema='saildroid-application-temp-startup-overlay-v1',
    baseline_archive_sha256=a.expected_baseline_sha256, updated_files=sorted(updated),
    all_java_core_art_native_backend_boot_manager_media_trust_bytes_unchanged=True, phone_staged=False)
(a.output / 'overlay.json').write_text(json.dumps(after, indent=2) + '\n')
with tarfile.open(a.output / 'native-overlay.tar.gz.pending', 'w:gz') as archive:
    archive.add(root, arcname='payload'); archive.add(a.output / 'overlay.json', arcname='overlay.json')
assert sha(a.baseline / 'native-overlay.tar.gz') == a.expected_baseline_sha256
(a.output / 'native-overlay.tar.gz.pending').replace(a.output / 'native-overlay.tar.gz')
print('APPLICATION_TEMP_STARTUP_OVERLAY=packaged|sha256=' + sha(a.output / 'native-overlay.tar.gz') + '|phone_staged=false')
