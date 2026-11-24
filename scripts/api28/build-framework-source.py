#!/usr/bin/env python3
"""Retain standalone libcore dependencies while selecting the Android9 framework."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api28', type=Path, required=True)
parser.add_argument('--api29', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
assert hashlib.sha256(arguments.api28.read_bytes()).hexdigest() == 'cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32'
assert hashlib.sha256(arguments.api29.read_bytes()).hexdigest() == 'a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'
assert not arguments.output.exists()
extensions = {}
with zipfile.ZipFile(arguments.api28) as framework, zipfile.ZipFile(arguments.api29) as previous:
    existing = set(framework.namelist())
    for name in sorted(previous.namelist()):
        if name.startswith(('libcore/', 'android/icu/', 'android/net/ssl/', 'com/android/org/kxml2/')) and name.endswith('.class') and name not in existing:
            extensions[name] = previous.read(name)
    with zipfile.ZipFile(arguments.output, 'x', zipfile.ZIP_DEFLATED) as output:
        for name in framework.namelist():
            output.writestr(name, framework.read(name))
        for name, data in extensions.items():
            output.writestr(name, data)
manifest = {'schema': 'saildroid-api28-framework-source-v1',
            'framework_sha256': hashlib.sha256(arguments.api28.read_bytes()).hexdigest(),
            'standalone_core_dependency_source_sha256': hashlib.sha256(arguments.api29.read_bytes()).hexdigest(),
            'extensions': {name: hashlib.sha256(data).hexdigest() for name, data in extensions.items()},
            'output_sha256': hashlib.sha256(arguments.output.read_bytes()).hexdigest()}
arguments.output.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('API28_CORE_DEPENDENCIES', len(extensions))
