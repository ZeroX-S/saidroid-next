#!/usr/bin/env python3
"""Bind the installed API28 release's standalone core JNI in its private linker."""
import argparse
import json
import re
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--release-id', required=True)
parser.add_argument('--check', action='store_true',
                    help='Verify core JNI mappings without changing the staging root')
arguments = parser.parse_args()
root = arguments.root.resolve()
assert not str(root).startswith(('/opt/saildroid/releases/', '/home/art/releases/'))
assert re.fullmatch('[a-z0-9][a-z0-9.-]{0,100}', arguments.release_id)
assert json.loads((root/'runtime.json').read_text())['api'] == 28
assert arguments.check or not (root/'share/packaging/activation-manifest.json').exists()
config = root/'linker-config/runtime.cfg'
names = ('libjavacore.so', 'libopenjdk.so', 'libopenjdkjvm.so')
sources = {source for name in names for source in (name, '/system/lib64/'+name, '/system/lib/'+name)}
original_lines = config.read_text().splitlines()
lines = [line for line in original_lines
         if not line.split() or line.split()[0] not in sources]
installed = '/opt/saildroid/releases/'+arguments.release_id
mappings = []
for name in names:
    dynamic = subprocess.check_output(['readelf', '-dW', str(root/'lib'/name)], text=True)
    assert '(NEEDED)' in dynamic and '[libc.so.6]' in dynamic, name
    for source in (name, '/system/lib64/'+name, '/system/lib/'+name):
        mappings.append(source+' '+installed+'/lib/'+name)
if arguments.check:
    actual = [line.split() for line in original_lines
              if line.split() and line.split()[0] in sources]
    expected = [line.split() for line in mappings]
    assert sorted(actual) == sorted(expected), (
        'Core JNI linker mappings differ from release '+arguments.release_id+
        '. Run prepare-core-linker.py before sealing the payload')
    print('API28_CORE_LINKER_VERIFIED', arguments.release_id)
    raise SystemExit(0)
lines.extend(mappings)
config.write_text('\n'.join(lines)+'\n')
config.chmod(0o644)
print('API28_CORE_LINKER_BOUND', arguments.release_id)
