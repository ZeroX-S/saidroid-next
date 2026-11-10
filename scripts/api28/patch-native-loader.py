#!/usr/bin/env python3
"""Select the API28 loader adapter without moving any ELF code or relocation."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def replace_needed(path):
    before = subprocess.check_output(['readelf', '-dW', str(path)], text=True)
    if not any('(NEEDED)' in line and '[libnativeloader.so]' in line for line in before.splitlines()):
        return None
    original = path.read_bytes()
    old = b'libnativeloader.so\0'
    new = b'libnloader28.so\0'
    assert original.count(old) == 1, 'Ambiguous native loader name in ' + str(path)
    offset = original.index(old)
    replacement = new + bytes(len(old) - len(new))
    result = original[:offset] + replacement + original[offset + len(old):]
    assert len(result) == len(original)
    path.write_bytes(result)
    after = subprocess.check_output(['readelf', '-dW', str(path)], text=True)
    assert after == before.replace('[libnativeloader.so]', '[libnloader28.so]')
    return {'before_sha256': hashlib.sha256(original).hexdigest(),
            'after_sha256': hashlib.sha256(result).hexdigest(),
            'string_offset': offset, 'original_needed': 'libnativeloader.so',
            'selected_needed': 'libnloader28.so'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    assert not str(root).startswith('/opt/saildroid/releases/')
    assert (root / 'android-libs/libnloader28.so').is_file()
    changed = {}
    for path in sorted((root / 'android-libs').glob('*.so')):
        record = replace_needed(path)
        if record:
            changed[str(path.relative_to(root))] = record
    assert changed, 'No native loader dependencies were found'
    arguments.manifest.write_text(json.dumps(changed, indent=2) + '\n')
    print('API28_LOADER_DEPENDENCIES', len(changed))


if __name__ == '__main__':
    main()
