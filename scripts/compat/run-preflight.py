#!/usr/bin/env python3
"""Run build-time linkage checks and optional packaged-ART regressions."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import time
import traceback

from api_inventory import Inventory, read_path
from jni_coverage import audit
from service_coverage import coverage
from product_sources import JAVA_DIRECTORIES, NATIVE_DIRECTORIES


FRAMEWORKS = {
    28: 'cf4aed5e458deb48ddc0ca92fc25156e6f478d9d5c1d948cdd1817a67ee11b32',
    29: 'a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c',
}
R8_SHA256 = '59753e70a74f918389cc87f1b7d66b5c0862932559167425708ded159e3de439'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def native_sources(repository):
    sources = [repository / 'scripts/device/sdbridge.c']
    for folder in NATIVE_DIRECTORIES:
        for path in (repository / folder).rglob('*'):
            if path.suffix in ('.c', '.cpp') and not set(path.relative_to(repository).parts) & {'tests', 'test', 'references', 'candidate', 'recipes', 'sources'}:
                sources.append(path)
    return sorted(set(sources))


def app_references(path, providers):
    application = read_path(path)
    combined = Inventory()
    combined.add(providers)
    combined.add(application)
    missing_types = sorted(name for name in application.types
                           if name not in combined.classes)
    missing_members = []
    for kind, owner, name, descriptor in sorted(application.references):
        if combined.resolve(kind, owner, name, descriptor) is None:
            missing_members.append(dict(kind=kind, owner=owner, name=name, descriptor=descriptor))
    return dict(input=str(path), sha256=digest(path), application_classes=len(application.classes),
                type_references=len(application.types), member_references=len(application.references),
                missing_types=missing_types, missing_members=missing_members,
                shadowed_classes=combined.duplicates,
                scope='Potential linkage gaps. SDK guards, reflection, dynamically loaded modules and hidden-API access require execution.')


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--classes', type=Path, action='append', default=[])
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--api', type=int, choices=(28, 29))
    parser.add_argument('--apk', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--r8', type=Path)
    parser.add_argument('--elf', action='store_true', help='Inventory ARM64 APK native dependencies with readelf on Linux')
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error('Output directory already exists')
    if not arguments.classes and not arguments.runtime_root:
        parser.error('Supply compiled product classes or an actual runtime root')
    if arguments.headless and (not arguments.runtime_root or not arguments.r8):
        parser.error('Packaged ART execution requires --runtime-root and --r8')
    if arguments.headless and (platform.system() != 'Linux' or platform.machine().lower() not in ('aarch64', 'arm64')):
        parser.error('Packaged ART contracts require an ARM64 Linux host')
    if arguments.runtime_root and arguments.classes:
        parser.error('Select either compiled source providers or a complete packaged runtime')
    if arguments.elf and (not arguments.runtime_root or platform.system() != 'Linux'):
        parser.error('Native ELF inventory requires --runtime-root on Linux')
    arguments.output.mkdir(parents=True)
    repository = Path(__file__).resolve().parents[2]
    report = dict(schema='saildroid-compatibility-preflight-v1', passed=False,
                  host=dict(system=platform.system(), machine=platform.machine()), phases={})
    try:
        framework_sha = digest(arguments.framework)
        api = arguments.api or next((key for key, value in FRAMEWORKS.items() if value == framework_sha), None)
        if api is None or FRAMEWORKS[api] != framework_sha:
            raise ValueError('The framework must match the pinned API28/API29 input')
        report['api'] = api
        report['framework'] = dict(path=str(arguments.framework), sha256=framework_sha)
        if arguments.headless:
            r8_sha = digest(arguments.r8)
            if r8_sha != R8_SHA256:
                raise ValueError('D8 must match the pinned R8 8.3.37 input')
            report['r8'] = dict(path=str(arguments.r8), sha256=r8_sha)
        tool_files = [path for path in (repository / 'scripts/compat').rglob('*')
                      if path.is_file() and path.suffix in ('.py', '.java', '.json')]
        tool_files.extend([repository / 'scripts/api29/build-product.py',
                           repository / 'scripts/api28/encode-platform-dex.py',
                           repository / 'scripts/api29/encode-hiddenapi-vm.py'])
        save(arguments.output / 'tool-inputs.json', {str(path.relative_to(repository)): digest(path)
                                                    for path in sorted(tool_files)})
        reference = read_path(arguments.framework)
        providers = Inventory()
        runtime_inputs = []
        if arguments.runtime_root:
            root = arguments.runtime_root.resolve()
            runtime = json.loads((root / 'runtime.json').read_text(encoding='utf-8'))
            if runtime['api'] != api:
                raise ValueError('Packaged runtime API differs from the framework baseline')
            for relative in runtime['boot_jars']:
                jar = (root / relative).resolve()
                if not jar.is_relative_to(root):
                    raise ValueError('Boot classpath escapes the runtime root')
                providers.add(read_path(jar))
                runtime_inputs.append(dict(path=str(jar), sha256=digest(jar)))
            # The private runtime classes are JNI providers. Keep the application
            # inventory separate from these implementation-only classes.
            jni_providers = Inventory()
            jni_providers.add(providers)
            runtime_jar = root / 'lib/runtime.jar'
            jni_providers.add(read_path(runtime_jar))
            runtime_inputs.append(dict(path=str(runtime_jar), sha256=digest(runtime_jar)))
            report['runtime'] = dict(root=str(root), metadata_sha256=digest(root / 'runtime.json'),
                                     inputs=runtime_inputs, api=runtime['api'])
            if api == 28:
                from sdk_coverage import audit as sdk_audit
                sdk = sdk_audit(providers)
                save(arguments.output / 'sdk-coverage.json', sdk)
                report['phases']['sdk'] = dict(passed=sdk['passed'],
                    expected_members=sdk['expected_members'], resolved_members=sdk['resolved_members'],
                    missing_classes=len(sdk['missing_classes']), missing_members=len(sdk['missing_members']),
                    inaccessible_members=len(sdk['inaccessible_members']))
        else:
            compiled_inputs = []
            for classes in arguments.classes:
                providers.add(read_path(classes))
                inputs = ({str(path.relative_to(classes)): digest(path) for path in sorted(classes.rglob('*.class'))}
                          if classes.is_dir() else {'sha256': digest(classes)})
                compiled_inputs.append(dict(path=str(classes), inputs=inputs))
            providers.add(reference)
            jni_providers = providers
            save(arguments.output / 'compiled-inputs.json', compiled_inputs)
        source_files = native_sources(repository)
        if arguments.runtime_root and 'java/lang/Object' not in providers.classes:
            raise ValueError('Packaged boot classpath is missing java/lang/Object')
        incomplete_core = () if 'java/lang/Object' in jni_providers.classes else ('java/', 'javax/', 'sun/', 'libcore/')
        jni = audit(source_files, jni_providers, api, incomplete_prefixes=incomplete_core)
        save(arguments.output / 'jni-contracts.json', jni)
        report['phases']['jni'] = dict(passed=not jni['problems'], checked=len(jni['checked']),
                                     unresolved=len(jni['unresolved']), problems=len(jni['problems']),
                                     core_provider_supplied=not incomplete_core)
        java_directories = [repository / name for name in JAVA_DIRECTORIES]
        services = coverage(java_directories, reference)
        save(arguments.output / 'service-coverage.json', services)
        route_errors = [row for row in services['route_problems']
                        if row['reason'] in ('advertised-without-dispatch-branch', 'dispatch-branch-not-advertised')]
        report['phases']['services'] = dict(completed=True, **services['totals'], route_errors=len(route_errors))
        all_sources = source_files + [path for directory in java_directories for path in sorted(directory.glob('*.java'))]
        save(arguments.output / 'source-inputs.json', {str(path.relative_to(repository)): digest(path)
                                                      for path in all_sources})
        if arguments.headless:
            from headless_art import run
            headless = run(arguments.runtime_root.resolve(), arguments.framework.resolve(),
                           arguments.r8.resolve(), arguments.output / 'headless', repository)
            report['phases']['headless'] = headless
            if api == 28 and runtime.get('sip_service'):
                spec = importlib.util.spec_from_file_location('sip_contracts', repository / 'scripts/compat/sip/run.py')
                sip_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sip_module)
                sip = sip_module.run(argparse.Namespace(runtime_root=arguments.runtime_root.resolve(),
                    framework=arguments.framework.resolve(), r8=arguments.r8.resolve(),
                    output=arguments.output / 'sip', reference_classes=None, sip_references=None,
                    overlay_root=None, raw_art=False, group=None))
                report['phases']['sip'] = sip
        app_paths = list(arguments.apk)
        fixture_apk = arguments.output / 'headless/contracts.apk'
        if fixture_apk.exists():
            app_paths.append(fixture_apk)
        apps = [app_references(path, providers) for path in app_paths]
        save(arguments.output / 'application-linkage.json', apps)
        report['phases']['applications'] = dict(scanned=len(apps),
            potential_missing_types=sum(len(app['missing_types']) for app in apps),
            potential_missing_members=sum(len(app['missing_members']) for app in apps))
        if arguments.elf:
            from elf_inventory import scan_applications
            native = scan_applications(app_paths, arguments.runtime_root.resolve())
            save(arguments.output / 'native-linkage.json', native)
            libraries = [library for app in native['applications'] for library in app['libraries']]
            report['phases']['native'] = dict(scanned=len(native['applications']), libraries=len(libraries),
                providers=len(native['providers']),
                potential_missing_libraries=sum(len(row['missing_libraries']) for row in libraries),
                potential_missing_symbols=sum(len(row['potential_missing_symbols']) for row in libraries))
        report['passed'] = report['phases'].get('sdk', {}).get('passed', True) and not jni['problems'] and not route_errors and (
            not arguments.headless or report['phases']['headless']['passed']) and report['phases'].get('sip', {}).get('passed', True)
    except Exception as failure:
        report['error'] = dict(type=type(failure).__name__, message=str(failure))
        (arguments.output / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        save(arguments.output / 'result.json', report)
        lines = ['# SailDroid compatibility preflight', '', 'API ' + str(report.get('api', 'unknown')), '',
                 'Result ' + ('PASS' if report['passed'] else 'FAIL'), '',
                 'Elapsed ' + str(report['elapsed_seconds']) + ' seconds', '']
        for name, phase in report['phases'].items():
            summary = phase
            if name == 'headless':
                summary = {key: phase[key] for key in ('passed', 'api', 'uid', 'reference', 'comparison',
                           'runtime_unchanged', 'fixture_removed', 'cleanup_errors', 'error') if key in phase}
                summary['groups'] = [dict(name=group['name'], passed=group['passed'],
                    returncode=group['returncode'], tests=len(group['terminal_events'])) for group in phase['groups']]
            lines.extend(['## ' + name, '', '```json', json.dumps(summary, indent=2), '```', ''])
        if report.get('error'):
            lines.extend(['## Error', '', report['error']['message'], ''])
        lines.extend(['## Evidence scope', '',
                      'Service dispatch presence is source coverage. Application gaps are candidates for execution.',
                      'Literal JNI checks and packaged ART contracts have separate results.',
                      'The core reference runs pinned AOSP tests on the host JDK.',
                      'Intent delivery uses a seeded process-local Activity fixture and the production reuse branch.',
                      'Device window, input and hardware acceptance is a separate validation stage.', ''])
        links = [('JNI contracts', 'jni-contracts.json'), ('Service coverage', 'service-coverage.json'),
                 ('Public SDK coverage', 'sdk-coverage.json'),
                 ('Application linkage', 'application-linkage.json'), ('Native linkage', 'native-linkage.json'),
                 ('Packaged ART results', 'headless/result.json')]
        lines.append(' · '.join('[' + label + '](' + path + ')' for label, path in links
                              if (arguments.output / path).exists()))
        lines.append('')
        (arguments.output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    print('COMPAT_PREFLIGHT=' + ('passed' if report['passed'] else 'failed') + '|output=' + str(arguments.output))
    if report.get('error'):
        print(json.dumps(report['error']))
    return 0 if report['passed'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
