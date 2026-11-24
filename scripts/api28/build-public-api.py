#!/usr/bin/env python3
"""Restore the pinned API28 VoIP API and opcode constants in a packaged runtime."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'compat'))
from api_inventory import Inventory, read_path
from sdk_coverage import api28_members, audit as sdk_audit


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime-root', 'framework', 'r8', 'android-libs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--dexlib-classpath', required=True)
    parser.add_argument('--aidl', default='aidl')
    arguments = parser.parse_args()
    module = Path(__file__).resolve().parent
    source = module / 'public-api-compat'
    manifest = json.loads((source / 'sources.json').read_text(encoding='utf-8'))
    root = arguments.runtime_root.resolve()
    runtime = json.loads((root / 'runtime.json').read_text(encoding='utf-8'))
    if runtime['api'] != 28:
        parser.error('The runtime must use API28')
    if arguments.output.exists():
        parser.error('Output directory already exists')
    for name, record in manifest['files'].items():
        assert digest(source / name) == record['sha256'], name
    assert digest(arguments.framework) == 'cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32'
    assert digest(arguments.r8) == '59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
    for name, sha256 in manifest['native_inputs'].items():
        assert digest(arguments.android_libs / name) == sha256, name
    restored = set((source / 'restored-members.txt').read_text(encoding='utf-8').splitlines())
    assert digest(source / 'restored-members.txt') == manifest['restored_members_sha256']
    assert len(restored) == 185 and restored <= api28_members()

    providers = Inventory()
    for relative in runtime['boot_jars']:
        path = (root / relative).resolve()
        assert path.is_relative_to(root), relative
        providers.add(read_path(path))
    before = sdk_audit(providers)
    assert set(before['missing_members']) == restored, 'The baseline SDK gaps differ'
    opcode_owner = providers.classes['dalvik/bytecode/Opcodes'].origin.split('!', 1)[0]
    opcode_jar = Path(opcode_owner).relative_to(root).as_posix()
    framework_jar = 'java/dex/art/framework28-classes4.jar'
    assert framework_jar in runtime['boot_jars'] and opcode_jar != framework_jar
    output = arguments.output.resolve()
    output.mkdir(parents=True)
    classes, generated, tools = [output / name for name in ('classes', 'generated', 'tools')]
    for directory in (classes, generated, tools):
        directory.mkdir()
    commands = []

    def run(command, name):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=180)
        (output / name).write_text(result.stdout + result.stderr, encoding='utf-8')
        result.check_returncode()

    for aidl in sorted((source / 'source/android/net/sip').glob('I*.aidl')):
        run([arguments.aidl, '-I' + str(source / 'source'), '-o' + str(generated), str(aidl)],
            aidl.stem + '-aidl.log')
    java_sources = sorted((source / 'source').rglob('*.java')) + sorted(generated.rglob('*.java'))
    run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-sourcepath', '',
         '-cp', str(arguments.framework), '-d', str(classes), *map(str, java_sources)], 'javac.log')
    compiled = sorted(classes.rglob('*.class'))
    opcode_class = classes / 'dalvik/bytecode/Opcodes.class'
    for label, inputs in (('voip', [path for path in compiled if path != opcode_class]),
                          ('opcodes', [opcode_class])):
        run(['java', '-Xmx2g', '-cp', str(arguments.r8), 'com.android.tools.r8.D8', '--release',
             '--min-api', '28', '--lib', str(arguments.framework), '--output',
             str(output / (label + '-overlay.jar')), *map(str, inputs)], label + '-d8.log')
    overlay = read_path(output / 'voip-overlay.jar')
    assert not overlay.classes.keys() & providers.classes.keys(), 'VoIP classes shadow existing providers'
    run(['javac', '-cp', arguments.dexlib_classpath, '-d', str(tools), str(module / 'MergeRuntimeDex.java')],
        'merger-javac.log')
    tool_classpath = str(tools) + os.pathsep + arguments.dexlib_classpath
    specification = importlib.util.spec_from_file_location('platform_encoder', module / 'encode-platform-dex.py')
    encoder = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(encoder)
    patched = {}
    preservation = {}
    for label, relative in (('opcodes', opcode_jar), ('voip', framework_jar)):
        baseline = root / relative
        for jar, name in ((baseline, 'baseline'), (output / (label + '-overlay.jar'), 'overlay')):
            with zipfile.ZipFile(jar) as archive:
                (output / (label + '-' + name + '.dex')).write_bytes(archive.read('classes.dex'))
        command = ['java', '-Xmx2g', '-cp', tool_classpath, 'MergeRuntimeDex',
                   str(output / (label + '-baseline.dex')), str(output / (label + '-overlay.dex')),
                   str(output / (label + '-merged.dex'))]
        if label == 'opcodes':
            command.append('--append-fields')
        run(command, label + '-merge.log')
        merged = output / (label + '-merged.jar')
        with zipfile.ZipFile(merged, 'x', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('classes.dex', (output / (label + '-merged.dex')).read_bytes())
        encoded = output / (label + '-encoded.jar')
        flags = encoder.encode_jar(merged, [baseline], encoded, public_members=restored)
        _, previous_flags, _, _ = encoder.read_members((output / (label + '-baseline.dex')).read_bytes())
        with zipfile.ZipFile(encoded) as archive:
            _, current_flags, _, _ = encoder.read_members(archive.read('classes.dex'))
        assert all(current_flags[name] == value for name, value in previous_flags.items())
        public = restored & current_flags.keys()
        assert all(current_flags[name] == 0 for name in public)
        if label == 'opcodes':
            assert current_flags.keys() - previous_flags.keys() == public
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(baseline) as previous, zipfile.ZipFile(encoded) as new, \
                zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
            for entry in previous.infolist():
                archive.writestr(entry, new.read('classes.dex') if entry.filename == 'classes.dex'
                                 else previous.read(entry))
        with zipfile.ZipFile(target) as archive:
            (output / (label + '-candidate.dex')).write_bytes(archive.read('classes.dex'))
        disassembled = []
        for version in ('baseline', 'candidate'):
            directory = output / (label + '-' + version + '-smali')
            run(['java', '-Xmx2g', '-cp', arguments.dexlib_classpath, 'org.jf.baksmali.Main',
                 'disassemble', '--api', '28', '--output', str(directory),
                 str(output / (label + '-' + version + '.dex'))], label + '-' + version + '-baksmali.log')
            disassembled.append({path.relative_to(directory).as_posix(): path.read_bytes()
                                 for path in directory.rglob('*.smali')})
        previous_classes, current_classes = disassembled
        assert previous_classes.keys() <= current_classes.keys(), 'An existing class was removed'
        # DEX writers can explicitly encode a static field's implicit zero value.
        # Hidden-API restrictions are compared separately by member signature.
        def normalize(data):
            data = re.sub(rb'(?m)^(\.field[^\n]*\bstatic\b[^\n]*:(?:Z|I|L[^;\n]*;)) = (?:false|0x0|null)$', rb'\1', data)
            return re.sub(rb'(?m)^\.(?:method|field)[^\n]*$',
                lambda match: re.sub(rb'\b(?:blacklist|greylist(?:-max-[a-z])?|whitelist|core-platform-api|test-api)\b ?', b'', match.group()), data)
        compared = dict(current_classes)
        if label == 'opcodes':
            name = 'dalvik/bytecode/Opcodes.smali'
            compared[name], removed = re.subn(
                rb'(?m)^\.field[^\n]*\bOP_CONST_METHOD_(?:HANDLE|TYPE):I = 0x(?:fe|ff)\n\n',
                b'', current_classes[name])
            assert removed == 2, 'The opcode values differ'
        changed = sorted(name for name, data in previous_classes.items()
                         if normalize(data) != normalize(compared[name]))
        assert not changed, 'Existing class content changed: ' + repr(changed)
        added = sorted(current_classes.keys() - previous_classes.keys())
        assert len(added) == (len(overlay.classes) if label == 'voip' else 0)
        patched[relative] = dict(sha256=digest(target), baseline_sha256=digest(baseline))
        preservation[relative] = dict(flags=flags, existing_members_preserved=len(previous_flags),
                                     restored_public_members=len(public), existing_classes_preserved=len(previous_classes),
                                     added_classes=added, existing_class_content_preserved=True)
    candidate = Inventory()
    for relative in runtime['boot_jars']:
        candidate.add(read_path(output / relative if relative in patched else root / relative))
    after = sdk_audit(candidate)
    assert after['passed'] and after['expected_members'] == 65961, after['missing_members']
    for name, sha256 in manifest['native_inputs'].items():
        relative = 'android-libs/' + name
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(arguments.android_libs / name, target)
        target.chmod(0o644)
        assert digest(target) == sha256
        patched[relative] = dict(sha256=sha256)
    release = runtime['rpm_activation']['release_id']
    assert re.fullmatch('[a-z0-9][a-z0-9.-]{0,100}', release), 'Invalid release identity'
    native_names = {prefix + name for name in manifest['native_inputs']
                    for prefix in ('', '/system/lib64/', '/system/lib/')}
    configuration = 'linker-config/runtime.cfg'
    mappings = {name: '/opt/saildroid/releases/' + release + '/android-libs/' + Path(name).name
                for name in sorted(native_names)}
    lines = [line for line in (root / configuration).read_text(encoding='utf-8').splitlines()
             if not line.split() or line.split()[0] not in native_names]
    lines.extend(name + ' ' + target for name, target in mappings.items())
    (output / configuration).parent.mkdir(parents=True, exist_ok=True)
    (output / configuration).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    patched[configuration] = dict(sha256=digest(output / configuration),
                                 baseline_sha256=digest(root / configuration))
    result = dict(passed=True, api=28, schema='saildroid-api28-public-api-v1',
                  restored_members=sorted(restored), source_manifest=manifest,
                  files=patched, hidden_api=preservation, sdk_before=before, sdk_after=after,
                  native_linker_mappings=mappings, compiled_classes=len(compiled), commands=commands)
    (output / 'build-result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('API28_PUBLIC_API=restored|members=185|sdk_members=65961|missing=0')


if __name__ == '__main__':
    main()
