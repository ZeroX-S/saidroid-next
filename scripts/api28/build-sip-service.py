#!/usr/bin/env python3
"""Compile SIP references or merge the service into a complete API28 runtime."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_smali(data):
    data = re.sub(rb'(?m)^(\.field[^\n]*\bstatic\b[^\n]*:(?:Z|I|L[^;\n]*;)) = (?:false|0x0|null)$', rb'\1', data)
    data = re.sub(rb'(?m)^\.(?:method|field)[^\n]*$',
        lambda match: re.sub(rb'\b(?:blacklist|greylist(?:-max-[a-z])?|whitelist|core-platform-api|test-api)\b ?', b'', match.group()), data)
    return re.sub(rb'(?m)^\s*\.line \d+\n', b'', data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('framework', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--references-only', action='store_true')
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--r8', type=Path)
    parser.add_argument('--reference-classes', type=Path, action='append', default=[])
    parser.add_argument('--dexlib-classpath')
    parser.add_argument('--aidl', default='aidl')
    parser.add_argument('--baseline-source', type=Path)
    parser.add_argument('--baseline-java21-javac')
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    module = repository / 'scripts/api28'
    output = arguments.output.resolve()
    if output.exists(): parser.error('Output directory already exists')
    output.mkdir(parents=True)
    commands = []

    def run(command, log):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, timeout=240)
        (output / log).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(log + '\n' + result.stderr.decode('utf-8', 'replace')[-6000:])

    public_source = module / 'public-api-compat/source'
    generated = output / 'generated'
    references = output / 'references'
    generated.mkdir()
    references.mkdir()
    for aidl in sorted((public_source / 'android/net/sip').glob('I*.aidl')):
        run([arguments.aidl, '-I' + str(public_source), '-o' + str(generated), str(aidl)], aidl.stem + '-aidl.log')
    public_sources = sorted((public_source / 'android/net').rglob('*.java')) + sorted(generated.rglob('*.java'))
    run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-sourcepath', '', '-cp',
         str(arguments.framework), '-d', str(references), *map(str, public_sources)], 'references-javac.log')
    with zipfile.ZipFile(output / 'references.jar', 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(references.rglob('*.class')):
            archive.write(path, path.relative_to(references).as_posix())
    if arguments.references_only:
        print('SIP_REFERENCES=' + str(output / 'references.jar'))
        return
    if not all((arguments.runtime_root, arguments.r8, arguments.dexlib_classpath)):
        parser.error('Runtime, R8 and dexlib classpath are required for a service merge')
    root = arguments.runtime_root.resolve()
    runtime = json.loads((root / 'runtime.json').read_text())
    assert runtime['api'] == 28
    assert digest(arguments.framework) == 'cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32'
    assert digest(arguments.r8) == '59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'
    source_names = ['scripts/device/' + name + '.java' for name in
        ('SdAudio', 'SdAppPermissions', 'SdPackageManagerService', 'SdServices', 'SdBinderRegistry', 'SdRtp')]
    source_names += ['scripts/api29/pending-intent-compat/source/scripts/device/SdPendingIntents.java']
    source_names += [path.relative_to(repository).as_posix() for path in sorted((repository / 'scripts/device/sip').glob('*.java'))]
    families = {Path(name).stem for name in source_names}
    sys.path.insert(0, str(repository / 'scripts/compat'))
    from product_sources import JAVA_DIRECTORIES
    classpath = os.pathsep.join(map(str, [references, arguments.framework, *arguments.reference_classes]))
    current_classes = output / 'classes'
    current_classes.mkdir()
    run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn',
         '-sourcepath', os.pathsep.join(str(repository / name) for name in JAVA_DIRECTORIES),
         '-cp', classpath, '-d', str(current_classes), *[str(repository / name) for name in source_names]], 'service-javac.log')
    selected = [path for path in sorted(current_classes.glob('*.class')) if path.stem.split('$', 1)[0] in families]
    run(['java', '-Xmx2g', '-cp', str(arguments.r8), 'com.android.tools.r8.D8', '--release', '--min-api', '28',
         '--lib', str(arguments.framework), '--classpath', str(output / 'references.jar'), '--output',
         str(output / 'service-overlay.jar'), *map(str, selected)], 'service-d8.log')
    codec_classes = output / 'codec-classes'
    codec_classes.mkdir()
    codec_sources = sorted((module / 'sip-service-compat/source').rglob('*.java'))
    run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-cp', classpath, '-d', str(codec_classes),
         *map(str, codec_sources)], 'codec-javac.log')
    run(['java', '-cp', str(arguments.r8), 'com.android.tools.r8.D8', '--release', '--min-api', '28', '--lib',
         str(arguments.framework), '--output', str(output / 'codec-overlay.jar'),
         *map(str, sorted(codec_classes.rglob('*.class')))], 'codec-d8.log')
    tools = output / 'tools'
    tools.mkdir()
    run(['javac', '-cp', arguments.dexlib_classpath, '-d', str(tools), str(module / 'MergeRuntimeDex.java')], 'merger-javac.log')
    spec = importlib.util.spec_from_file_location('platform_encoder', module / 'encode-platform-dex.py')
    encoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encoder)

    def disassemble(label, dex):
        directory = output / (label + '-smali')
        run(['java', '-Xmx2g', '-cp', arguments.dexlib_classpath, 'org.jf.baksmali.Main',
             'disassemble', '--api', '28', '--output', str(directory), str(dex)], label + '-baksmali.log')
        return {path.relative_to(directory).as_posix(): normalize_smali(path.read_bytes())
                for path in directory.rglob('*.smali')}

    files = {}
    for label, relative in (('service', 'lib/runtime.jar'), ('codec', 'java/dex/art/framework28-classes4.jar')):
        previous = root / relative
        for name, source in (('baseline', previous), ('overlay', output / (label + '-overlay.jar'))):
            with zipfile.ZipFile(source) as archive:
                (output / (label + '-' + name + '.dex')).write_bytes(archive.read('classes.dex'))
        merged = output / (label + '-merged.dex')
        run(['java', '-Xmx2g', '-cp', str(tools) + os.pathsep + arguments.dexlib_classpath, 'MergeRuntimeDex',
             str(output / (label + '-baseline.dex')), str(output / (label + '-overlay.dex')), str(merged),
             '--preserve-synthetic'], label + '-merge.log')
        with zipfile.ZipFile(output / (label + '-merged.jar'), 'x') as archive: archive.writestr('classes.dex', merged.read_bytes())
        encoded = output / (label + '-encoded.jar')
        flags = encoder.encode_jar(output / (label + '-merged.jar'), [previous], encoded, public_members=set())
        with zipfile.ZipFile(encoded) as archive: new_dex = archive.read('classes.dex')
        old_members = encoder.read_members((output / (label + '-baseline.dex')).read_bytes())[1]
        new_members = encoder.read_members(new_dex)[1]
        assert old_members.keys() <= new_members.keys(), 'An existing runtime member was removed'
        assert all(new_members[name] == flag for name, flag in old_members.items()), 'Hidden API flags changed'
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(previous) as baseline, zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as destination:
            for item in baseline.infolist():
                destination.writestr(item, new_dex if item.filename == 'classes.dex' else baseline.read(item))
        (output / (label + '-candidate.dex')).write_bytes(new_dex)
        baseline_classes = disassemble(label + '-baseline', output / (label + '-baseline.dex'))
        candidate_classes = disassemble(label + '-candidate', output / (label + '-candidate.dex'))
        assert baseline_classes.keys() <= candidate_classes.keys(), 'An existing class was removed'
        changed = sorted(name for name in baseline_classes if baseline_classes[name] != candidate_classes[name])
        added = sorted(candidate_classes.keys() - baseline_classes.keys())
        allowed = families if label == 'service' else {'android/net/rtp/AudioCodec', 'android/net/sip/SipAudioCall'}
        assert all(name.removesuffix('.smali').split('$', 1)[0] in allowed for name in changed + added), changed + added
        files[relative] = dict(sha256=digest(target), baseline_sha256=digest(previous),
                               original_members_preserved=len(old_members), hidden_api=flags,
                               changed_classes=changed, added_classes=added,
                               unrelated_classes_identical=len(baseline_classes) - len(changed))
        if arguments.baseline_source:
            baseline_names = [name for name in source_names if (arguments.baseline_source / name).exists()] if label == 'service' else [
                'scripts/api28/public-api-compat/source/android/net/rtp/AudioCodec.java',
                'scripts/api28/public-api-compat/source/android/net/sip/SipAudioCall.java']
            rebuilt_classes = output / (label + '-baseline-rebuilt-classes')
            rebuilt_classes.mkdir()
            run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-sourcepath',
                 os.pathsep.join(str(repository / name) for name in JAVA_DIRECTORIES), '-cp', classpath,
                 '-d', str(rebuilt_classes), *[str(arguments.baseline_source / name) for name in baseline_names]],
                 label + '-baseline-rebuild-javac.log')
            if label == 'service' and arguments.baseline_java21_javac:
                pending_name = 'scripts/api29/pending-intent-compat/source/scripts/device/SdPendingIntents.java'
                run([arguments.baseline_java21_javac, '--release', '8', '-encoding', 'UTF-8', '-nowarn',
                     '-sourcepath', '', '-cp', os.pathsep.join([classpath, str(current_classes)]),
                     '-d', str(rebuilt_classes), str(arguments.baseline_source / pending_name)],
                     'pending-baseline-java21-javac.log')
                pinned = json.loads((root / 'share/build/pending-intent/runtime-build.json').read_text())
                reproduced_pending = {path.name: digest(path) for path in rebuilt_classes.glob('SdPendingIntents*.class')}
                assert all(pinned['classfiles_after'][name] == sha256 for name, sha256 in reproduced_pending.items()), reproduced_pending
            baseline_families = {Path(name).stem for name in baseline_names}
            selected_baseline = [path for path in sorted(rebuilt_classes.rglob('*.class'))
                                 if path.stem.split('$', 1)[0] in baseline_families]
            pending_classes = []
            if label == 'service' and arguments.baseline_java21_javac:
                pending_classes = [path for path in selected_baseline if path.stem.split('$', 1)[0] == 'SdPendingIntents']
                selected_baseline = [path for path in selected_baseline if path not in pending_classes]
            baseline_overlay = output / (label + '-baseline-rebuilt-overlay.jar')
            run(['java', '-Xmx2g', '-cp', str(arguments.r8), 'com.android.tools.r8.D8', '--release', '--min-api', '28',
                 '--lib', str(arguments.framework), '--classpath', str(output / 'references.jar'), '--output',
                 str(baseline_overlay), *map(str, selected_baseline)], label + '-baseline-rebuild-d8.log')
            with zipfile.ZipFile(baseline_overlay) as archive:
                (output / (label + '-baseline-rebuilt-overlay.dex')).write_bytes(archive.read('classes.dex'))
            rebuilt = output / (label + '-baseline-rebuilt.dex')
            run(['java', '-Xmx2g', '-cp', str(tools) + os.pathsep + arguments.dexlib_classpath, 'MergeRuntimeDex',
                 str(output / (label + '-baseline.dex')), str(output / (label + '-baseline-rebuilt-overlay.dex')),
                 str(rebuilt), '--preserve-synthetic'], label + '-baseline-rebuild-merge.log')
            if pending_classes:
                pending_overlay = output / 'pending-baseline-overlay.jar'
                run(['java', '-cp', str(arguments.r8), 'com.android.tools.r8.D8', '--release', '--min-api', '29',
                     '--lib', str(arguments.framework), '--output', str(pending_overlay), *map(str, pending_classes)],
                     'pending-baseline-d8.log')
                with zipfile.ZipFile(pending_overlay) as archive:
                    (output / 'pending-baseline-overlay.dex').write_bytes(archive.read('classes.dex'))
                pending_merged = output / 'pending-baseline-merged.dex'
                run(['java', '-Xmx2g', '-cp', str(tools) + os.pathsep + arguments.dexlib_classpath, 'MergeRuntimeDex',
                     str(rebuilt), str(output / 'pending-baseline-overlay.dex'), str(pending_merged), '--preserve-synthetic'],
                     'pending-baseline-merge.log')
                pending_merged.replace(rebuilt)
            reproduced = disassemble(label + '-baseline-rebuilt', rebuilt)
            differences = sorted(name for name in baseline_classes if baseline_classes[name] != reproduced.get(name))
            (output / (label + '-baseline-rebuild-differences.json')).write_text(json.dumps(differences, indent=2) + '\n')
            assert baseline_classes.keys() == reproduced.keys() and not differences, differences
            files[relative]['baseline_source_rebuild_identical'] = True
            files[relative]['baseline_source_hashes'] = {name: digest(arguments.baseline_source / name) for name in baseline_names}
    from api_inventory import Inventory, read_path
    from sdk_coverage import audit
    inventory = Inventory()
    for name in runtime['boot_jars']:
        inventory.add(read_path(output / name if name in files else root / name))
    sdk = audit(inventory)
    assert sdk['passed'] and sdk['resolved_members'] == 65961
    result = dict(passed=True, api=28, files=files, sdk=sdk, source_families=sorted(families),
        selected_classes=len(selected), sources={name:digest(repository / name) for name in source_names},
        framework_sources={path.relative_to(repository).as_posix(): digest(path) for path in codec_sources}, commands=commands)
    (output / 'build-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('SIP_SERVICE_BUILD=PASS|sdk_members=65961|missing=0')


if __name__ == '__main__':
    main()
