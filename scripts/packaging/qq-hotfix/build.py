#!/usr/bin/env python3
"""Package a validated runtime and its complete boot-image closure as an inert RPM."""

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess


HERE = Path(__file__).resolve().parent
specification = importlib.util.spec_from_file_location('qq_hotfix', HERE / 'apply.py')
helper = importlib.util.module_from_spec(specification)
specification.loader.exec_module(helper)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--component', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifact = arguments.artifact.resolve()
    root = arguments.component.resolve()
    baseline = arguments.baseline.resolve()
    result = helper.load(artifact / 'boot-image/result.json')
    if not result['passed'] or not result['helper_present'] or len(result['files']) != 42:
        raise RuntimeError('Boot-image validation did not pass')
    recipe = helper.load(artifact / 'boot-image/recipe.json')
    config = helper.load(root / 'runtime.json')
    old_config = helper.load(baseline / 'runtime.json')
    payload = output / 'bundle/payload'
    payload.mkdir(parents=True)
    sources = {'lib/runtime.jar': artifact / 'runtime.jar',
               helper.MANIFEST_NAME: artifact / 'boot-image/boot-image-manifest.json'}
    sources.update({'system/framework/arm64/' + name: artifact / 'boot-image/arm64' / name
                    for name in result['files']})
    expected = {'system/framework/arm64/' + name: value['sha256'] for name, value in result['files'].items()}
    expected['lib/runtime.jar'] = recipe['runtime_jar_sha256']
    expected[helper.MANIFEST_NAME] = helper.digest(artifact / 'boot-image/boot-image-manifest.json')
    for name, source in sources.items():
        if helper.digest(source) != expected[name]:
            raise RuntimeError('Build artifact changed: ' + name)
        destination = payload / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o644)
    inputs = {name: checksum for name, checksum in recipe['inputs'].items()
              if name not in {'lib/runtime.jar', 'runtime.json', helper.MANIFEST_NAME}}
    for directory in ('lib', 'libexec', 'bin'):
        for source in (root / directory).iterdir():
            if source.is_file() and source.name != 'runtime.jar':
                inputs[str(source.relative_to(root))] = helper.digest(source)
    for name, checksum in inputs.items():
        if helper.digest(root / name) != checksum:
            raise RuntimeError('Component inputs changed: ' + name)
    additions = {name: value for name, value in config.items() if name not in old_config}
    allowed = {'qq_login_hotfix', 'document_picker_hotfix', 'activity_clear_top_hotfix',
               'explicit_broadcast_dispatch_hotfix', 'receiver_process_compat_hotfix', 'popup_touch_target_hotfix'}
    if set(additions) != allowed or any(config[name] != value for name, value in old_config.items() if name != 'boot_image'):
        raise RuntimeError('Unexpected configuration changes; cannot construct a narrow merge')
    bundle = dict(schema='saildroid-qq-hotfix-bundle-v1', component=str(root),
                  baseline={name: helper.digest(baseline / name) for name in ('lib/runtime.jar', helper.MANIFEST_NAME)},
                  files=expected, inputs=inputs, config_requirements={'api': old_config['api'], 'boot_jars': old_config['boot_jars']},
                  boot_path=old_config['boot_image']['path'], config_additions=additions,
                  local_user_acceptance={'file_forward': True, 'file_recall': True},
                  target_user_acceptance_required=True, app_data_included=False)
    (output / 'bundle/bundle.json').write_text(json.dumps(bundle, indent=2) + '\n')
    shutil.copyfile(HERE / 'README.md', output / 'bundle/README.md')
    helper.Hotfix(output / 'bundle').candidate()
    top = output / 'rpmbuild'
    for directory in ('BUILD', 'BUILDROOT', 'RPMS', 'SOURCES', 'SPECS', 'SRPMS'):
        (top / directory).mkdir(parents=True)
    name = 'saildroid-qq-hotfix-api28-r323k'
    installed = str(helper.BUNDLE)
    lines = ['%global __os_install_post %{nil}', '%global debug_package %{nil}',
             '%global _build_id_links none', '%global _binary_payload w6.gzdio',
             'Name: ' + name, 'Version: 20261111', 'Release: 1',
             'Summary: Validated SailDroid QQ login, media, receiver and popup fixes',
             'License: Multiple; see base runtime source provenance', 'BuildArch: aarch64', 'AutoReqProv: no',
             'Requires: saildroid-runtime-api28-r323k-dev-20261110 = 0.321.62-69',
             'Requires: /usr/bin/python3', '', '%description',
             'Stages a hash-pinned runtime and 42 matching boot-image files. Installation',
             'does not activate the overlay. Run saildroid-qq-hotfix check then apply as',
             'root. The helper preserves app data and supports rollback.', '', '%prep', '%build', '%install',
             'mkdir -p "%{buildroot}' + installed + '" "%{buildroot}/usr/sbin"',
             'cp -a "' + str(output / 'bundle') + '/." "%{buildroot}' + installed + '/"',
             'install -m 0755 "' + str(HERE / 'apply.py') + '" "%{buildroot}/usr/sbin/saildroid-qq-hotfix"',
             '', '%files', '%defattr(-,root,root,-)', installed, '/usr/sbin/saildroid-qq-hotfix']
    spec = top / 'SPECS' / (name + '.spec')
    spec.write_text('\n'.join(lines) + '\n')
    with (output / 'build.log').open('wb') as log:
        subprocess.run(['rpmbuild', '-bb', '--define', '_topdir ' + str(top), str(spec)],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    rpm = next((top / 'RPMS').rglob('*.rpm'))
    destination = output / rpm.name
    shutil.copyfile(rpm, destination)
    extracted = output / 'extracted'
    extracted.mkdir()
    with (output / 'extract.log').open('wb') as log:
        producer = subprocess.Popen(['rpm2cpio', str(destination)], stdout=subprocess.PIPE, stderr=log)
        try:
            subprocess.run(['cpio', '-id'], stdin=producer.stdout, cwd=extracted,
                           stdout=log, stderr=log, check=True, timeout=600)
            producer.stdout.close()
            if producer.wait(timeout=15):
                raise RuntimeError('RPM payload extraction failed')
        finally:
            if producer.poll() is None:
                producer.terminate()
                producer.wait(timeout=15)
    extracted_bundle = extracted / installed.lstrip('/')
    helper.Hotfix(extracted_bundle).candidate()
    for name in ('bundle.json', 'README.md'):
        if helper.digest(extracted_bundle / name) != helper.digest(output / 'bundle' / name):
            raise RuntimeError('RPM changed bundle metadata: ' + name)
    if helper.digest(extracted / 'usr/sbin/saildroid-qq-hotfix') != helper.digest(HERE / 'apply.py'):
        raise RuntimeError('RPM changed deployment helper')
    if (extracted / 'usr/sbin/saildroid-qq-hotfix').stat().st_mode & 0o777 != 0o755:
        raise RuntimeError('RPM changed helper permissions')
    if subprocess.check_output(['rpm', '-qp', '--scripts', str(destination)], text=True).strip():
        raise RuntimeError('RPM unexpectedly contains scriptlets')
    checksum = helper.digest(destination)
    (output / (rpm.name + '.sha256')).write_text(checksum + '  ' + rpm.name + '\n')
    print('QQ_HOTFIX_RPM=' + str(destination))
    print('SHA256=' + checksum)


if __name__ == '__main__':
    main()
