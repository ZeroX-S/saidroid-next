#!/usr/bin/env python3
"""Compose verified nonboot-library ownership over an isolated native overlay.

All existing core/image/native/media/manager/trust bytes are retained. Creates
a new test artifact only; never stages or activates a device component.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import tarfile
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    os.umask(0o022)
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['baseline', 'prepared_source', 'framework', 'baseline_encoded', 'encoded', 'output']:
        p.add_argument(name, type=Path)
    p.add_argument('--expected-baseline-sha256', required=True)
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[2]
    assert sha(a.baseline / 'native-overlay.tar.gz') == a.expected_baseline_sha256
    before = json.loads((a.baseline / 'overlay.json').read_text())
    assert before['schema'] == 'saildroid-native-overlay-v2' and before['api'] == 29
    oldroot = a.baseline / 'payload'
    full = before['install_manifest']
    for name, entry in before['changes'].items():
        f = oldroot / name
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert f.is_file() and not f.is_symlink() and sha(f) == entry['sha256']
        assert f.stat().st_size == entry['size'] and stat.S_IMODE(f.stat().st_mode) == entry['mode']
        assert full['files'][name] == entry
    source = json.loads((a.prepared_source / 'manifest.json').read_text())
    builder = repo / 'scripts/runtime/prepare-framework-library-ownership-vm.py'
    assert source['passed'] and source['remaining_class_and_resource_bytes_unchanged']
    assert sha(builder) == source['builder_sha256']
    assert sha(a.prepared_source / 'source.jar') == source['source_sha256']
    assert len(source['removed_classes']) == 8 and all(n.startswith('com/android/timezone/distro/') for n in source['removed_classes'])
    assert all(sha(Path(f)) == digest for f, digest in source['references'].items())
    framework = json.loads((a.framework / 'manifest.json').read_text())
    assert framework['source_sha256'] == source['source_sha256']
    assert framework['compiler_sha256'] == '59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
    assert framework['resources'] == source['resources']
    with zipfile.ZipFile(a.framework / 'classes.jar') as archive:
        assert set(archive.namelist()) == set(source['kept_classes'])
        assert all(hashlib.sha256(archive.read(n)).hexdigest() == digest for n, digest in source['kept_classes'].items())
    runtime = json.loads((oldroot / 'runtime.json').read_text())
    encoded = json.loads((a.encoded / 'manifest.json').read_text())
    old_encoded = json.loads((oldroot / 'share/build/hiddenapi-manifest.json').read_text())
    assert json.loads((a.baseline_encoded / 'manifest.json').read_text()) == old_encoded
    for k in ['schema', 'canonical_flags_sha256', 'tool_sha256', 'public_library_apis', 'unknown_policy']:
        assert old_encoded[k] == encoded[k]
    assert encoded['files'].keys() == old_encoded['files'].keys() == set(runtime['boot_jars']) | {'lib/runtime.jar'}
    spec = importlib.util.spec_from_file_location('ownership_encoder', repo / 'scripts/runtime/encode-hiddenapi-vm.py')
    encoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encoder)
    old_members, new_members, changed = {}, {}, []
    for name, entry in encoded['files'].items():
        assert sha(a.encoded / name) == entry['sha256'] and entry['executable_code_unchanged']
        assert sha(a.baseline_encoded / name) == old_encoded['files'][name]['sha256'] == full['files'][name]['sha256']
        for directory, members in [(a.baseline_encoded, old_members), (a.encoded, new_members)]:
            with zipfile.ZipFile(directory / name) as archive:
                values, _ = encoder.dex_members(archive.read('classes.dex'))
                members.update({n: v[0] for n, v in values.items()})
        if entry['sha256'] != old_encoded['files'][name]['sha256']:
            assert '/framework29-' in name
            changed.append(name)
        if '/framework29-' in name:
            raw = a.framework / Path(name).name
            assert entry['source_sha256'] == sha(raw) == framework['files'][raw.name]['sha256']
    assert len(changed) == 5
    assert not (set(new_members) - set(old_members))
    removed = set(old_members) - set(new_members)
    assert len(removed) == 100 and all(n.startswith('Lcom/android/timezone/distro/') for n in removed)
    assert all(old_members[n] == v for n, v in new_members.items())
    flags = lambda d: dict(line.split(',', 1) for line in (d / 'effective-api-flags.csv').read_text().splitlines())
    af, bf = flags(a.baseline_encoded), flags(a.encoded)
    assert set(af) - set(bf) == removed and all(af[n] == v for n, v in bf.items())
    assert all(af[n] == 'blacklist' for n in removed)
    evidence = repo / 'build/evidence/cts-frame-repair-20261031'
    proof_file = evidence / 'original-timezone197-paired-v1-audit.json'
    proof = json.loads(proof_file.read_text())
    raw_proof = evidence / 'original-timezone197-paired-v2.json'
    assert proof['accepted_comparison'] and not proof['full_module_passed']
    assert sha(raw_proof) == proof['raw_paired_sha256']
    diagnostic = json.loads(raw_proof.read_text())
    assert diagnostic['status'] == 'COMPLETE'
    assert proof['tests'] == proof['after_pass'] == 46 and proof['after_fail'] == 0 and proof['before_fail'] == 27
    assert {n: encoded['files'][n]['sha256'] for n in runtime['boot_jars'] if '/framework29-' in n} == diagnostic['actual_framework197_files']
    assert not a.output.exists()
    a.output.mkdir(parents=True)
    root = a.output / 'payload'
    shutil.copytree(oldroot, root)
    root.chmod(0o755)
    for d in root.rglob('*'):
        if d.is_dir() and not d.is_symlink():
            d.chmod(0o755)
    after = copy.deepcopy(before)
    manifest, changes, updated = after['install_manifest'], after['changes'], []

    def install(f, name, mode=0o644):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        assert not target.is_symlink()
        shutil.copyfile(f, target)
        target.chmod(mode)
        entry = dict(sha256=sha(target), size=target.stat().st_size, mode=mode)
        manifest['files'][name] = changes[name] = entry
        updated.append(name)

    for name in changed:
        install(a.encoded / name, name, full['files'][name]['mode'])
    install(a.encoded / 'manifest.json', 'share/build/hiddenapi-manifest.json')
    install(a.framework / 'manifest.json', 'share/build/framework-manifest.json')
    install(a.prepared_source / 'manifest.json', 'share/build/framework-ownership/source-manifest.json')
    install(builder, 'share/build/framework-ownership/builder.py')
    install(Path(__file__), 'share/build/framework-ownership/packager.py')
    install(proof_file, 'share/build/framework-ownership/original-paired-audit.json')
    for f, digest in source['references'].items():
        install(Path(f), 'share/build/framework-ownership/references/' + Path(f).name)
    runtime['hidden_api']['manifest_sha256'] = sha(a.encoded / 'manifest.json')
    runtime['framework_library_ownership'] = dict(
        schema='saildroid-framework-library-ownership-v1',
        source_manifest_sha256=sha(a.prepared_source / 'manifest.json'),
        scope='All applications; Android10 separately linked time-zone distro libraries omitted from boot framework. No Java access/loader/API-policy changes.',
        removed_classes=sorted(source['removed_classes']))
    tmp = a.output / 'runtime.json'
    tmp.write_text(json.dumps(runtime, indent=2) + '\n')
    install(tmp, 'runtime.json')
    tmp.unlink()
    manifest['bytes'] = sum(v['size'] for v in manifest['files'].values())
    assert manifest['symlinks'] == full['symlinks'] and set(full['files']) <= set(manifest['files'])
    for k in ['remove_files', 'ca_alias_cleanup', 'product_manifest']:
        assert before[k] == after[k]
    assert all(manifest['files'][n] == v for n, v in full['files'].items() if n not in updated)
    assert all(sha(root / n) == v['sha256'] and stat.S_IMODE((root / n).stat().st_mode) == v['mode'] for n, v in changes.items())
    after['framework_ownership_overlay'] = dict(
        schema='saildroid-framework-ownership-overlay-v1', baseline_archive_sha256=a.expected_baseline_sha256,
        updated_files=sorted(updated), all_core_images_native_media_manager_trust_bytes_unchanged=True,
        original_selected_vm_passed=46, phone_staged=False)
    (a.output / 'overlay.json').write_text(json.dumps(after, indent=2) + '\n')
    with tarfile.open(a.output / 'native-overlay.tar.gz.pending', 'w:gz') as archive:
        archive.add(root, arcname='payload')
        archive.add(a.output / 'overlay.json', arcname='overlay.json')
    assert sha(a.baseline / 'native-overlay.tar.gz') == a.expected_baseline_sha256
    assert sha(builder) == source['builder_sha256'] and sha(raw_proof) == proof['raw_paired_sha256']
    assert all(sha(a.encoded / n) == v['sha256'] for n, v in encoded['files'].items())
    (a.output / 'native-overlay.tar.gz.pending').replace(a.output / 'native-overlay.tar.gz')
    print('FRAMEWORK_OWNERSHIP_OVERLAY=packaged|sha256=' + sha(a.output / 'native-overlay.tar.gz') + '|phone_staged=false')


if __name__ == '__main__':
    main()
