#!/usr/bin/env python3
"""Build the API28 microphone bridge over a verified existing runtime jar."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('framework', 'r8', 'baseline-runtime', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--runtime-classpath', required=True)
    parser.add_argument('--dexlib-classpath', required=True)
    arguments = parser.parse_args()
    module = Path(__file__).resolve().parent
    repository = module.parents[1]
    names = ['scripts/device/' + name + '.java'
             for name in ('SdAudio', 'SdAudioRecord', 'SdAppPermissions', 'SdPackageManagerService')]
    names.append('native/media/droid-camera/SdCameraAppOps.java')
    output = arguments.output.resolve()
    assert digest(arguments.framework) == 'cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32'
    assert digest(arguments.r8) == '59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
    assert not output.exists(), 'Build output already exists'
    output.mkdir(parents=True)
    classes = output / 'candidate-classes'
    tools = output / 'tools'
    classes.mkdir()
    tools.mkdir()
    commands = []

    def run(command, name):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, timeout=180)
        (output / name).write_bytes(result.stdout + result.stderr)
        result.check_returncode()

    classpath = str(arguments.framework) + os.pathsep + arguments.runtime_classpath
    run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-sourcepath', '',
         '-classpath', classpath, '-d', str(classes),
         *[str(repository / name) for name in names]], 'javac.log')
    run(['java', '-Xmx2g', '-cp', str(arguments.r8), 'com.android.tools.r8.D8', '--release',
         '--min-api', '28', '--lib', str(arguments.framework), '--output', str(output / 'overlay.jar'),
         *[str(classes / (name + '.class'))
           for name in ('SdAudio', 'SdAudioRecord', 'SdAppPermissions', 'SdPackageManagerService', 'SdCameraAppOps')]], 'd8.log')
    for jar, name in ((arguments.baseline_runtime, 'baseline.dex'), (output / 'overlay.jar', 'overlay.dex')):
        with zipfile.ZipFile(jar) as archive:
            (output / name).write_bytes(archive.read('classes.dex'))
    run(['javac', '-classpath', arguments.dexlib_classpath, '-d', str(tools),
         str(module / 'MergeRuntimeDex.java')], 'merger-javac.log')
    run(['java', '-cp', str(tools) + os.pathsep + arguments.dexlib_classpath, 'MergeRuntimeDex',
         str(output / 'baseline.dex'), str(output / 'overlay.dex'), str(output / 'merged.dex')], 'merge.log')
    with zipfile.ZipFile(output / 'merged.jar', 'x', zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo('classes.dex', (1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, (output / 'merged.dex').read_bytes())
    spec = importlib.util.spec_from_file_location('platform_encoder', module / 'encode-platform-dex.py')
    encoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encoder)
    flags = encoder.encode_jar(output / 'merged.jar', [arguments.baseline_runtime], output / 'runtime.jar')
    before_flags = encoder.read_members((output / 'baseline.dex').read_bytes())[1]
    with zipfile.ZipFile(output / 'runtime.jar') as archive:
        (output / 'candidate.dex').write_bytes(archive.read('classes.dex'))
    after_flags = encoder.read_members((output / 'candidate.dex').read_bytes())[1]
    assert all(after_flags[name] == value for name, value in before_flags.items())
    added_members = sorted(after_flags.keys() - before_flags.keys())
    assert all(name.startswith(('LSdAudio;', 'LSdAudioRecord;')) for name in added_members)
    for label in ('baseline', 'candidate'):
        run(['java', '-cp', arguments.dexlib_classpath, 'org.jf.baksmali.Main', 'disassemble',
             '--api', '28', '--output', str(output / (label + '-smali')),
             str(output / (label + '.dex'))], label + '-baksmali.log')
    before = {path.relative_to(output / 'baseline-smali').as_posix(): path.read_bytes()
              for path in (output / 'baseline-smali').rglob('*.smali')}
    after = {path.relative_to(output / 'candidate-smali').as_posix(): path.read_bytes()
             for path in (output / 'candidate-smali').rglob('*.smali')}
    changed = sorted(name for name, data in before.items() if data != after[name])
    assert changed == ['SdAppPermissions.smali', 'SdAudio.smali', 'SdCameraAppOps.smali', 'SdPackageManagerService.smali'], changed
    assert after.keys() - before.keys() == {'SdAudioRecord.smali'}
    record = {'passed': True, 'baseline_runtime_sha256': digest(arguments.baseline_runtime),
              'runtime_sha256': digest(output / 'runtime.jar'), 'runtime_classes': len(after),
              'changed_runtime_classes': changed, 'new_runtime_classes': ['SdAudioRecord.smali'],
              'unrelated_classes_identical': len(before) - len(changed),
              'hidden_api_members_preserved': len(before_flags), 'remaining_member_flags_preserved': True,
              'added_private_members': added_members, 'hidden_api': flags,
              'source_sha256': {name: digest(repository / name) for name in names}, 'commands': commands}
    (output / 'build-result.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({key: value for key, value in record.items() if key != 'commands'}, indent=2))


if __name__ == '__main__':
    main()
