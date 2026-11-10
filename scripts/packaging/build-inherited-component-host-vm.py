#!/usr/bin/env python3
"""Apply the component-name fix to an exactly reproduced, accepted API29 Host.

This is for inherited r321o native payloads whose API29 JNI closure must remain
unchanged. It does not replace the product builder or modify the supplied root.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    provenance = root / 'share/build/manager-self-retirement321'
    accepted = json.loads((provenance / 'integrated-build-result.json').read_text())
    closure = json.loads((provenance / 'all-source-closure.json').read_text())
    assert accepted['passed'] and closure['passed']
    assert sha(root / 'libexec/saildroid-host') == accepted['candidate_sha256']
    pins = dict(accepted['pins'])
    for files in closure['closures'].values():
        for name, digest in files.items():
            assert name not in pins or pins[name] == digest, name
            pins[name] = digest
    for name, digest in pins.items():
        assert sha(name) == digest, 'Source closure changed: ' + name
    command = next(row['argv'] for row in accepted['commands']
                   if row['label'] == 'candidate-build')[:]
    compiler_index = command.index('-o') + 1
    command[compiler_index] = str(out / 'baseline-host')
    commands = []

    def run(argv, label, timeout=120):
        result = subprocess.run(argv, capture_output=True, timeout=timeout)
        (out / (label + '.stdout')).write_bytes(result.stdout)
        (out / (label + '.stderr')).write_bytes(result.stderr)
        commands.append(dict(argv=argv, label=label, returncode=result.returncode))
        assert result.returncode == 0, label
        return result.stdout.decode()

    try:
        run(command, 'baseline-build')
        assert sha(out / 'baseline-host') == accepted['candidate_sha256'], 'Baseline did not reproduce'
        headers = [Path(name) for name in pins if name.endswith('/host-common.hpp')]
        assert len(headers) == 1
        old_header = headers[0]
        header = old_header.read_text()
        assert 'valid_component' not in header
        repository = Path(__file__).resolve().parents[2]
        current_header = (repository / 'native/host/host-common.hpp').read_text()
        function = current_header[current_header.index('static inline bool valid_component('):current_header.index('static const char *BUS')]
        assert function.count('std::regex_match') == 1
        include = out / 'include'
        include.mkdir()
        for name in pins:
            source_header = Path(name)
            if source_header.is_relative_to(old_header.parent):
                target_header = include / source_header.relative_to(old_header.parent)
                target_header.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_header, target_header)
        (include / 'host-common.hpp').write_text(header + '\n' + function)
        (out / 'host-common-before.hpp').write_text(header)
        candidate = command[:]
        candidate[compiler_index] = str(out / 'saildroid-host')
        candidate.insert(1, '-I' + str(include))
        patched_sources = {}
        for source in [x for x in candidate if x.endswith('.cpp')]:
            text = Path(source).read_text()
            original = text
            if source.endswith('/host-manager.cpp'):
                old_check = 'if (!valid_package(a) || !valid_package(b) ||'
                assert text.count(old_check) == 1
                text = text.replace(old_check, 'if (!valid_package(a) || !valid_component(b) ||')
            elif source.endswith('/host-entry.cpp'):
                for role in ['service', 'activity', 'provider', 'receiver']:
                    before = '!valid(' + role + ')'
                    assert text.count(before) == 1
                    text = text.replace(before, '!valid_component(' + role + ')')
            if text != original:
                target = out / Path(source).name
                target.write_text(text)
                candidate[candidate.index(source)] = str(target)
                patched_sources[source] = str(target)
                candidate.insert(1, '-I' + str(Path(source).parent))
        assert len(patched_sources) == 2
        # Recompute each actual translation unit's include closure. Require the
        # patched header in every TU that included the accepted original header.
        actual_closures = {}
        for i, source in enumerate(x for x in candidate if x.endswith('.cpp')):
            dep = ['g++', '-M', '-std=c++17', '-I' + str(include)]
            dep += [x for x in candidate if x.startswith('-I')]
            dep += [source]
            data = run(dep, 'dependencies-' + str(i))
            paths = data.replace('\\\n', ' ').split()[1:]
            actual_closures[source] = {name: sha(name) for name in paths if Path(name).is_file()}
            if str(old_header) in closure['closures'].get(source, {}) or source.endswith('/host-manager.cpp'):
                assert str(include / 'host-common.hpp') in actual_closures[source]
            assert str(old_header) not in actual_closures[source]
            if source.endswith(('/host-manager.cpp', '/host-entry.cpp')):
                assert str(include / 'host-common.hpp') in actual_closures[source]
        run(candidate, 'candidate-build')
        exports = {}
        dynamic = {}
        for kind, filename in [('baseline', 'baseline-host'), ('candidate', 'saildroid-host')]:
            exports[kind] = [line.split()[-1] for line in run(
                ['nm', '-D', '--defined-only', str(out / filename)], kind + '-exports').splitlines()]
            dynamic[kind] = re.findall(r'\((NEEDED|RUNPATH|RPATH)\).*\[([^\]]*)\]',
                run(['readelf', '-d', str(out / filename)], kind + '-dynamic'))
        assert set(exports['baseline']) <= set(exports['candidate'])
        added_exports = sorted(set(exports['candidate']) - set(exports['baseline']))
        assert all(name.startswith('_Z12signal_owned') for name in added_exports), added_exports
        assert [name for name in exports['baseline'] if not name.startswith('_Z')] == [name for name in exports['candidate'] if not name.startswith('_Z')]
        assert dynamic['baseline'] == dynamic['candidate']
        repository = Path(__file__).resolve().parents[2]
        flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0'], text=True).split()
        fixture = repository / 'native/host/tests/component-identity.cpp'
        # Compile the existing positive/negative contract against this exact
        # patched legacy header, rather than just the current product header.
        fixture_text = fixture.read_text().replace('#include "../host-manager.cpp"', '#include "host-manager.cpp"')
        assert '#include "host-manager.cpp"' in fixture_text
        (out / 'component-identity.cpp').write_text(fixture_text)
        run(['g++', '-std=c++17', '-O2', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-I' + str(out), '-I' + str(include), '-I' + str(old_header.parent),
             str(out / 'component-identity.cpp'), *flags, '-ldl', '-pthread', '-o', str(out / 'component-test')], 'fixture-build')
        run([str(out / 'component-test')], 'component-test')
        for name, digest in pins.items():
            assert sha(name) == digest, name
        result = dict(passed=True, baseline_byte_identical=True,
                      baseline_sha256=accepted['candidate_sha256'], candidate_sha256=sha(out / 'saildroid-host'),
                      source_change='Allow Java nested-class $ identifiers in component names',
                      existing_exports_preserved=True, c_and_jni_exports_unchanged=True,
                      added_internal_exports=added_exports, dynamic_dependencies_runpath_unchanged=True,
                      source_pins=pins, patched_sources=patched_sources, actual_closures=actual_closures, commands=commands,
                      phone_accessed=False, runtime_root_modified=False)
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({key: value for key, value in result.items()
                          if key not in ['source_pins', 'patched_sources', 'actual_closures', 'commands']}), flush=True)
    except BaseException as error:
        (out / 'failure.json').write_text(json.dumps(dict(passed=False, error=repr(error), commands=commands), indent=2) + '\n')
        raise


if __name__ == '__main__':
    main()
