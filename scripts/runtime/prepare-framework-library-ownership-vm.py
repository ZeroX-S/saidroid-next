#!/usr/bin/env python3
"""Keep the separately linked time-zone distro libraries out of the boot framework.

Android links these libraries into services.core and their own consumers. They
are not boot APIs. Preserve every remaining accepted class/resource byte; do
not adjust Java access, application loaders, or application/test archives.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('baseline', type=Path)
    p.add_argument('flags_gzip', type=Path)
    p.add_argument('core_library_definition', type=Path)
    p.add_argument('installer_library_definition', type=Path)
    p.add_argument('services_definition', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    assert not a.output.exists()
    flags = gzip.decompress(a.flags_gzip.read_bytes())
    assert hashlib.sha256(flags).hexdigest() == 'f22a59c215e752777a114bd9b07b0b6b4aedfc8e49e6efca0f99681771c5bfeb'
    assert not any(line.startswith(b'Lcom/android/timezone/distro/') for line in flags.splitlines())
    refs = {
        a.core_library_definition: '16bce1f56a032e26a031eed694c18318862b42facb6df49ee86712991286ee42',
        a.installer_library_definition: '87bb8e28646abe6fcaaf34859267c2c06ab4cf9f6b876265af9a42f6c14848a2',
        a.services_definition: '40d597c231146e04c1a848b634b0a46353a16d29697ed4e2a4a640a431d150df',
    }
    # Pin the actual references below; callers cannot widen the removal set.
    assert all(sha(f) == expected for f, expected in refs.items())
    assert 'name: "time_zone_distro"' in a.core_library_definition.read_text()
    assert 'name: "time_zone_distro_installer"' in a.installer_library_definition.read_text()
    service = a.services_definition.read_text()
    assert '"time_zone_distro",' in service and '"time_zone_distro_installer",' in service
    expected = {
        'com/android/timezone/distro/' + n + '.class' for n in (
            'DistroException', 'DistroVersion', 'FileUtils', 'StagedDistroOperation',
            'TimeZoneDistro', 'installer/TimeZoneDistroInstaller',
            'installer/TimeZoneDistroInstaller$InstallResultType',
            'installer/TimeZoneDistroInstaller$UninstallResultType')
    }
    classes = a.baseline / 'classes.jar'
    original_manifest = json.loads((a.baseline / 'manifest.json').read_text())
    first = a.baseline / 'framework29-classes.jar'
    assert sha(first) == original_manifest['files'][first.name]['sha256']
    a.output.mkdir(parents=True)
    kept, removed, resources = {}, {}, {}
    with zipfile.ZipFile(classes) as source, zipfile.ZipFile(first) as original_resources, \
            zipfile.ZipFile(a.output / 'source.jar', 'x', zipfile.ZIP_DEFLATED) as result:
        assert len(source.namelist()) == len(set(source.namelist()))
        found = {n for n in source.namelist() if n.startswith('com/android/timezone/distro/')}
        assert found == expected, sorted(found ^ expected)
        for name in source.namelist():
            data = source.read(name)
            digest = hashlib.sha256(data).hexdigest()
            if name in expected:
                removed[name] = digest
            else:
                assert name.endswith('.class')
                kept[name] = digest
                result.writestr(name, data)
        for name in original_resources.namelist():
            if name.endswith('.dex') or name.endswith('/'):
                continue
            assert name not in kept
            data = original_resources.read(name)
            resources[name] = hashlib.sha256(data).hexdigest()
            result.writestr(name, data)
    with zipfile.ZipFile(a.output / 'source.jar') as result:
        assert set(result.namelist()) == set(kept) | set(resources)
        assert all(hashlib.sha256(result.read(n)).hexdigest() == d for n, d in {**kept, **resources}.items())
    record = dict(
        scope='Source composition only: separately linked platform time-zone distro libraries removed from boot framework; no APK/Java access/native/host/device changes',
        passed=True, builder_sha256=sha(Path(__file__)),
        baseline_manifest_sha256=sha(a.baseline / 'manifest.json'),
        baseline_classes_sha256=sha(classes), canonical_flags_sha256=hashlib.sha256(flags).hexdigest(),
        references={str(f): sha(f) for f in [a.core_library_definition, a.installer_library_definition, a.services_definition]},
        source_sha256=sha(a.output / 'source.jar'), removed_classes=removed,
        kept_classes=kept, resources=resources,
        remaining_class_and_resource_bytes_unchanged=True)
    (a.output / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print('FRAMEWORK_OWNERSHIP=prepared|removed=8|remaining_class_and_resource_bytes=unchanged|device_changes=false')


if __name__ == '__main__':
    main()
