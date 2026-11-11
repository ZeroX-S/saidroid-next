#!/usr/bin/env python3
"""Rebuild the verified API28 window library with native display event routing."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
record = json.loads((args.baseline_root / 'share/build/native-fullscreen-20261109/window-build-result.json').read_text())
baseline_source = args.baseline_root / 'share/build/native-fullscreen-20261109/source/native/window/sdwindow.c'
assert not args.output.exists()
args.output.mkdir(parents=True)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(path):
    dynamic = subprocess.check_output(['aarch64-linux-gnu-readelf', '-dW', str(path)], text=True)
    exports = subprocess.check_output(['aarch64-linux-gnu-nm', '-D', '--defined-only', str(path)], text=True)
    return dict(sha256=digest(path),
        needed=[line.split('[')[1].split(']')[0] for line in dynamic.splitlines() if '(NEEDED)' in line],
        exports=sorted(line.split()[-1] for line in exports.splitlines()))


assert digest(baseline_source) == record['source_sha256']['native/window/sdwindow.c']
assert digest(args.baseline_root / 'lib/libsdwindow.so') == record['candidate_sha256']
results = {}
for label in ['baseline', 'candidate']:
    output = args.output / label
    output.mkdir()
    source = output / 'sdwindow-close-fixed.c'
    source.write_bytes((baseline_source if label == 'baseline' else repo / 'native/window/sdwindow.c').read_bytes().replace(b'\r\n', b'\n'))
    command = list(record['candidate']['command'])
    old_source = next(item for item in command if item.endswith('/sdwindow-close-fixed.c'))
    old_directory = str(Path(old_source).parent)
    command[command.index(old_source)] = str(source)
    command[command.index('-o') + 1] = str(output / 'libsdwindow.so')
    command.insert(1, '-ffile-prefix-map=' + str(output) + '=' + old_directory)
    if label == 'candidate':
        for name in ['native-display-events.h', 'native-display-events.c']:
            shutil.copyfile(repo / 'native/window' / name, output / name)
        command.insert(command.index(str(source)) + 1, str(output / 'native-display-events.c'))
    reply = subprocess.run(command, capture_output=True)
    (output / 'build.log').write_bytes(reply.stdout + reply.stderr)
    reply.check_returncode()
    results[label] = dict(inspect(output / 'libsdwindow.so'), command=command,
                         sources={str(Path(item)): digest(Path(item)) for item in command if item.endswith('.c')})
assert results['baseline']['sha256'] == record['candidate_sha256']
assert results['candidate']['needed'] == results['baseline']['needed']
assert set(results['baseline']['exports']) <= set(results['candidate']['exports'])
added = sorted(set(results['candidate']['exports']) - set(results['baseline']['exports']))
assert len([name for name in added if name.startswith('bionic_')]) == 9, added
shutil.copyfile(args.output / 'candidate/libsdwindow.so', args.output / 'libsdwindow.so')
result = dict(passed=True, baseline_byte_identical=True, dependencies_identical=True,
              previous_exports_preserved=True, added_exports=added, records=results,
              source_sha256={name: digest(repo / name) for name in [
                  'native/window/sdwindow.c', 'native/window/native-display-events.c',
                  'native/window/native-display-events.h', 'native/window/build-native-display-vm.py']})
(args.output / 'build-result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: value for key, value in result.items() if key != 'records'}, indent=2))
