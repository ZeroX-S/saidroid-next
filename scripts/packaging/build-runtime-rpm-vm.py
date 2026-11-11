#!/usr/bin/env python3
"""Build a version-isolated development RPM and verify every extracted byte.

This packages an explicitly supplied, hash-pinned snapshot. It neither certifies
runtime closure nor installs the result. Activation policy comes from the sealed
runtime configuration. Run only in the build VM.
"""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, os, re, runpy, shutil, stat, subprocess, sys


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inventory(root):
    result = {'files': {}, 'symlinks': {}, 'directories': []}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if not re.fullmatch(r'[A-Za-z0-9_./+@=-]+', relative):
            raise ValueError('Unsafe RPM pathname: ' + relative)
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Symlink outside release: ' + relative)
            result['symlinks'][relative] = target
        elif path.is_file():
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o7022:
                raise ValueError('Writable or privileged payload: ' + relative)
            result['files'][relative] = dict(sha256=digest(path), size=path.stat().st_size, mode=mode)
        elif path.is_dir():
            result['directories'].append(relative)
        else:
            raise ValueError('Unsupported payload node: ' + relative)
    return result


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--manifest', type=Path, required=True)
p.add_argument('--manifest-sha256', required=True)
p.add_argument('--release-id', required=True)
p.add_argument('--version', required=True)
p.add_argument('--rpm-release', default='1')
p.add_argument('--output', type=Path, required=True)
p.add_argument('--extract-timeout', type=int, default=600)
a = p.parse_args()
assert 30 <= a.extract_timeout <= 1800, 'Extraction timeout must be bounded'
for value in (a.release_id, a.version, a.rpm_release):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.]*(?:-[a-z0-9.]+)*', value):
        raise ValueError('Unsafe package identity')
if '-' in a.version or '-' in a.rpm_release:
    raise ValueError('RPM version/release cannot contain a hyphen')
if a.output.exists():
    raise ValueError('Output already exists')
root = a.root.resolve()
runtime = json.loads((root / 'runtime.json').read_text())
api = runtime['api']
assert api in (28, 29), 'Unsupported Android API'
assert digest(a.manifest) == a.manifest_sha256, 'Snapshot manifest hash mismatch'
expected = json.loads(a.manifest.read_text())
assert inventory(root) == expected, 'Payload differs from exact manifest'
if api == 28:
    subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'api28/prepare-core-linker.py'),
                    '--root', str(root), '--release-id', a.release_id, '--check'], check=True)
allowed_apks = {'share/manager.apk', 'system/framework/framework-res.apk'}
assert {s for s in expected['files'] if s.endswith('.apk')} == allowed_apks
assert not any(s.startswith(('data/', 'apps/', 'home/')) for s in expected['files'])
assert not any(s.endswith(('.service', '.desktop')) for s in expected['files'])
assert 'libexec/saildroid-app' in expected['files']

# Android/Bionic DSOs must never generate host RPM requirements. Derive host
# ABI requirements from glibc ELF version tables only, including the isolated
# compiler, and suppress providers for all privately shipped libraries.
def private_names(prefix):
    return {Path(s).name for s in (*expected['files'], *expected['symlinks']) if s.startswith(prefix) and '/' not in s[len(prefix):]}
provided_runtime = private_names('lib/')
provided_compiler = private_names('compiler/lib/')
requirements = {'glibc >= 2.38', 'libstdc++ >= 13.2'}
if 'bin/saildroid-setup' in expected['files']:
    # Python's actual file provider is portable across python3/python3-base
    # package naming. The helper independently checks its supported version.
    requirements.add('/usr/bin/python3')
webview = runtime.get('host_webview_runtime')
if webview is not None:
    manifest_relative = PurePosixPath(webview['manifest'])
    manifest_path = (root / manifest_relative).resolve()
    assert (not manifest_relative.is_absolute()
            and manifest_path.is_relative_to(root)), 'WebView manifest outside release'
    assert digest(manifest_path) == webview['manifest_sha256'], 'WebView manifest hash mismatch'
    engine = json.loads(manifest_path.read_text())
    packages = {package['name']: package for package in engine['engine_rpms']}
    assert len(packages) == len(engine['engine_rpms']), 'Duplicate WebView engine package'
    # Recorded engine inputs define minimum versions for the rolling repository.
    for package_name in webview['dependency_packages']:
        assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', package_name), 'Unsafe WebView package name'
        package = packages[package_name]
        assert package['arch'] in ('aarch64', 'noarch'), 'Unsupported WebView package architecture'
        version = package['version']
        epoch = str(version.get('epoch') or '0')
        evr = version['ver'] + '-' + version['rel']
        if epoch != '0':
            evr = epoch + ':' + evr
        assert re.fullmatch(
            r'(?:[0-9]+:)?[A-Za-z0-9][A-Za-z0-9._+~^]*-[A-Za-z0-9][A-Za-z0-9._+~^]*',
            evr), 'Unsafe WebView package version'
        requirements.add(package_name + ' >= ' + evr)
host_elf = []
for relative in expected['files']:
    file = root / relative
    with file.open('rb') as stream:
        if stream.read(4) != b'\x7fELF':
            continue
    version = subprocess.check_output(['readelf', '-VW', str(file)], text=True)
    if 'GLIBC_' not in version:
        continue
    host_elf.append(relative)
    provided = provided_compiler if relative.startswith('compiler/') else provided_runtime
    dynamic = subprocess.check_output(['readelf', '-dW', str(file)], text=True)
    for soname in re.findall(r'\(NEEDED\).*\[([^]]+)\]', dynamic):
        if soname not in provided:
            requirements.add(soname + '()(64bit)')
    current = None
    for line in version.splitlines():
        match = re.search(r'File: (\S+)', line)
        if match:
            current = match.group(1)
        match = re.search(r'Name: ((?:GLIBC|GLIBCXX|CXXABI)_[\w.]+)', line)
        if match and current and current not in provided:
            requirements.add(current + '(' + match.group(1) + ')(64bit)')

a.output.mkdir(parents=True)
top = a.output.resolve() / 'rpmbuild'
for name in ('SPECS', 'SOURCES', 'BUILD', 'BUILDROOT', 'RPMS', 'SRPMS'):
    (top / name).mkdir(parents=True)
installed = '/opt/saildroid/releases/' + a.release_id
name = 'saildroid-runtime-' + a.release_id
setup = runpy.run_path(str(root / 'bin/saildroid-setup')) if 'bin/saildroid-setup' in expected['files'] else None
bootstrap_capability = 'cap_sys_resource=ep'
if runtime.get('native_bootstrap') is not None:
    assert setup and 'native_bootstrap_capability' in setup, 'Bootstrap policy requires an updated setup helper'
    bootstrap_capability = setup['native_bootstrap_capability'](runtime)
auto_activate = False
if runtime.get('rpm_activation') is not None:
    assert setup and 'rpm_activation_enabled' in setup, 'Activation policy requires an updated setup helper'
    auto_activate = setup['rpm_activation_enabled'](runtime, a.release_id)
scripts_expected = setup['rpm_install_scripts'](a.release_id) if auto_activate else {}
lines = [
    '%global __os_install_post %{nil}', '%global debug_package %{nil}',
    '%global _build_id_links none', '%global _binary_payload w9.gzdio',
    'Name: ' + name, 'Version: ' + a.version, 'Release: ' + a.rpm_release,
    'Summary: Isolated SailDroid API' + str(api) + ' development runtime',
    'License: Multiple; see bundled source provenance',
    'BuildArch: aarch64', 'AutoReqProv: no',
    *['Requires: ' + r for r in sorted(requirements)],
    '', '%description',
    'Explicit development snapshot in a private versioned runtime directory.',
    'The packaged activation policy determines installation-time activation.',
    '', '%prep', '%build', '%install',
    'mkdir -p "%{buildroot}' + installed + '"',
    "cp -a '" + str(root) + "/.' \"%{buildroot}" + installed + '/"',
    '', '%files', '%defattr(-,root,root,-)',
    '%dir %attr(0755,root,root) /opt/saildroid',
    '%dir %attr(0755,root,root) /opt/saildroid/releases',
    '%dir %attr(0755,root,root) ' + installed,
]
for directory in expected['directories']:
    lines.append('%dir %attr(0755,root,root) ' + installed + '/' + directory)
for relative, value in expected['files'].items():
    capability = '%caps(' + bootstrap_capability + ') ' if relative == 'libexec/saildroid-app' else ''
    lines.append(capability + '%%attr(%04o,root,root) ' % value['mode'] + installed + '/' + relative)
for relative in expected['symlinks']:
    lines.append(installed + '/' + relative)
for script_name, body in scripts_expected.items():
    lines.extend(['', '%pre' if script_name == 'preinstall' else '%posttrans', body])
spec = top / 'SPECS' / (name + '.spec')
spec.write_text('\n'.join(lines) + '\n')
command = ['rpmbuild', '-bb', '--define', '_topdir ' + str(top), str(spec)]
with (a.output / 'build.log').open('wb') as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
rpms = list((top / 'RPMS').rglob('*.rpm'))
assert len(rpms) == 1
rpm = rpms[0]
query = lambda *args: subprocess.check_output(['rpm', '-qp', *args, str(rpm)], text=True)
identity = query('--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}')
assert identity == name + '-' + a.version + '-' + a.rpm_release + '.aarch64'
assert requirements <= set(query('--requires').splitlines()), 'RPM omitted declared host requirements'
scripts = query('--scripts')
if setup and 'check_rpm_scripts' in setup:
    setup['check_rpm_scripts'](runtime, a.release_id, scripts)
else:
    assert not scripts.strip(), 'Unexpected installation scriptlets'
capabilities = query('--qf', '[%{FILENAMES} %{FILECAPS}\n]')
cap_lines = [line for line in capabilities.splitlines() if 'cap_' in line]
assert cap_lines == [installed + '/libexec/saildroid-app ' + bootstrap_capability]
extract = a.output.resolve() / 'extracted'
extract.mkdir()
with (a.output / 'extract.log').open('wb') as log:
    producer = subprocess.Popen(['rpm2cpio', str(rpm)], stdout=subprocess.PIPE, stderr=log)
    try:
        consumer = subprocess.run(['cpio', '-idm', '--quiet'], stdin=producer.stdout,
                                  stdout=log, stderr=log, cwd=extract, timeout=a.extract_timeout)
        producer.stdout.close()
        assert consumer.returncode == 0 and producer.wait(timeout=30) == 0
    finally:
        producer.stdout.close()
        if producer.poll() is None:
            producer.terminate()
            try:
                producer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                producer.kill()
                producer.wait(timeout=5)
assert inventory(extract / installed.lstrip('/')) == expected, 'RPM changed payload bytes/modes/links'
result = dict(passed=True, rpm=str(rpm), nevra=identity, sha256=digest(rpm), size=rpm.stat().st_size,
              installed_root=installed, manifest_sha256=a.manifest_sha256,
              files=len(expected['files']), symlinks=len(expected['symlinks']),
              requirements=sorted(requirements), host_elf_count=len(host_elf),
              capabilities=cap_lines, scriptlets=scripts, extracted_manifest_matches=True,
              target_installed=False, target_tested=False, closure_certified=False,
              automatic_activation=auto_activate, app_caches_included=False,
              system_apks=sorted(allowed_apks))
(a.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
