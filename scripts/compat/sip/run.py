#!/usr/bin/env python3
"""Run public SIP contracts with an isolated registrar and private Binder."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command, log, timeout=240):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors='replace', timeout=timeout)
    log.write_text(result.stdout, encoding='utf-8')
    return result


def art_command(root, mode, peer, raw, binder=False):
    runtime = json.loads((root / 'runtime.json').read_text())
    installed = '/opt/saildroid/releases/' + runtime['rpm_activation']['release_id']
    arguments = ['org.saildroid.compat.sip.SipMain', mode, peer['address'], str(peer['sip_port']),
                 str(peer['control_port']), '/home/art/data/sip-fixture']
    if binder:
        arguments.append('/home/art/runtime/binder/binder')
    environment = ['env', '-i', 'PATH=/usr/bin:/bin', 'LC_ALL=C', 'HOME=/home/nobody',
                   'USER=nobody', 'LOGNAME=nobody', 'ANDROID_DATA=/home/art/data',
                   'SAILDROID_ANDROID_LOG_STDERR=1', 'SAILDROID_HWUI=0',
                   'XDG_RUNTIME_DIR=/home/nobody', 'SAILDROID_DISPLAY_WIDTH=480',
                   'SAILDROID_DISPLAY_HEIGHT=960', 'PULSE_SERVER=unix:/home/nobody/pulse-native']
    options = ['-Xcheck:jni', '-cp', '/home/art/data/sip-fixture/contracts.apk']
    if not raw:
        return ['runuser', '-u', 'nobody', '--', *environment,
                installed + '/bin/dalvikvm', *options, *arguments]
    boot = [installed + '/' + name for name in runtime['boot_jars']]
    boot.extend([installed + '/lib/runtime.jar', installed + '/lib/java-cli-bootstrap.jar'])
    locations = ['/home/art/api29-root/' + name for name in runtime['boot_jars']]
    locations.extend(['/home/art/api29-root/lib/runtime.jar', installed + '/lib/java-cli-bootstrap.jar'])
    environment.extend([
        'ANDROID_ROOT=' + installed,
        'ANDROID_RUNTIME_ROOT=' + installed + '/apex/com.android.runtime.debug',
        'ANDROID_TZDATA_ROOT=' + installed + '/apex/com.android.tzdata',
        'ICU_DATA=' + installed + '/usr/icu', 'SD_BUILD_PROP=' + installed + '/build.prop',
        'BIONIC_TRANSLATION_CONFIG_DIR=' + installed + '/linker-config',
        'LD_LIBRARY_PATH=' + installed + '/lib:/home/art/lib',
        'LD_PRELOAD=' + ':'.join(installed + '/lib/' + name for name in
            ('libsdmath-precision.so', 'libsdstrictmath-fdlibm.so', 'libsdcharacter-icu63.so',
             'libsdhost29.so', 'libdl_bio.so.0')) + ':libresolv.so.2'])
    options = ['-XXlib:' + installed + '/lib/libart.so', '-Xnoimage-dex2oat', '-Xusejit:false',
               '-Ximage:/home/art/data/sip-fixture/missing-boot.art',
               '-Xbootclasspath:' + ':'.join(boot), '-Xbootclasspath-locations:' + ':'.join(locations),
               '-Xtarget-sdk-version:28', '-Xhidden-api-policy:enabled',
               '-Djava.library.path=' + installed + '/lib:' + installed + '/android-libs:/home/art/lib',
               '-Dsaidroid.framework.api=28',
               '-Dsaidroid.bridge.library=' + installed + '/lib/libsdbridge.so',
               '-Dsaidroid.native.runtime=' + installed + '/android-libs', *options]
    return ['runuser', '-u', 'nobody', '--', *environment,
            installed + '/libexec/dalvikvm-real', *options, 'SdJavaCommand', *arguments]


def namespace_driver(configuration):
    """Processes live in one private PID/network namespace and share its Binder."""
    import time
    from urllib.request import urlopen

    work = Path('/var/tmp/saildroid-compat')
    data = Path('/home/art/data/sip-fixture')
    peer_log = (data / 'peer.log').open('w')
    peer = subprocess.Popen(['runuser', '-u', 'nobody', '--', 'python3', str(work / 'sip_peer.py'),
                             '--ready', str(data / 'peer-ready.json')], stdout=peer_log, stderr=subprocess.STDOUT)
    children = [peer]
    logs = [peer_log]
    owner = None
    pulse = None
    result = dict(passed=False, groups=[])

    def ready(name, process):
        deadline = time.monotonic() + 25
        while not (data / name).exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('SIP fixture readiness failed ' + name)
            time.sleep(0.05)

    def start(mode, settings):
        log = (data / (mode + '.log')).open('w')
        logs.append(log)
        process = subprocess.Popen(art_command(Path(configuration['root']), mode, settings,
                                               configuration['raw'], binder=mode in ('registry', 'ipc-owner', 'ipc-client')),
                                   stdout=log, stderr=subprocess.STDOUT)
        children.append(process)
        return process

    def group(mode, settings):
        process = start(mode, settings)
        status = process.wait(timeout=120)
        text = (data / (mode + '.log')).read_text(errors='replace')
        events = [line for line in text.splitlines() if line.startswith('COMPAT_EVENT=')]
        passed = status == 0 and bool(events) and all('|PASS|' in line for line in events)
        passed = passed and 'COMPAT_SUITE=sip|' in text and 'SD_JAVA_CLI=ready|sdk=28' in text
        result['groups'].append(dict(name=mode, passed=passed, returncode=status, events=events))
        print('SIP_CONTRACT=' + mode + '|' + ('PASS' if passed else 'FAIL'), flush=True)
        if not passed:
            print(text[-9000:], flush=True)
            raise RuntimeError('SIP public contracts failed ' + mode)

    try:
        ready('peer-ready.json', peer)
        settings = json.loads((data / 'peer-ready.json').read_text())
        from pulse_fixture import PulseFixture
        pulse = PulseFixture()
        pulse.start()
        if 'suite' in configuration['groups']:
            group('suite', settings)
        if 'ipc' in configuration['groups']:
            registry = start('registry', settings)
            ready('registry-ready', registry)
            owner = start('ipc-owner', settings)
            ready('ipc-owner-ready', owner)
            group('ipc-client', settings)
        if 'media' in configuration['groups']:
            group('media', settings)
        result['metrics'] = json.loads(urlopen('http://127.0.0.1:' + str(settings['control_port']) + '/metrics', timeout=3).read())
        required = ('register_challenges', 'proxy_challenges', 'tcp_requests', 'registration_successes',
                    'deregistrations', 'reinvite_rejections', 'cancel', 'late_answers', 'bye',
                    'incoming_answers', 'incoming_rejections', 'transient_registration_errors') if 'suite' in configuration['groups'] or 'ipc' in configuration['groups'] else ()
        result['peer_checks'] = {name: result['metrics'].get(name, 0) > 0 for name in required}
        result['peer_checks']['no_wildcard_deregistrations'] = not result['metrics'].get('wildcard_deregistrations', 0)
        result['peer_checks']['no_peer_errors'] = not result['metrics'].get('peer_errors', 0)
        result['passed'] = all(result['peer_checks'].values())
    except Exception as failure:
        result['error'] = dict(type=type(failure).__name__, message=str(failure))
    finally:
        (data / 'ipc-owner-stop').touch()
        if owner is not None and owner.poll() is None:
            try:
                owner.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        (data / 'registry-stop').touch()
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()
        if pulse:
            pulse.close()
        (data / 'namespace-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['passed'] else 1


def run(arguments):
    repository = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repository / 'scripts/compat'))
    from headless_art import prepare_paths
    from product_sources import JAVA_DIRECTORIES

    output = arguments.output.resolve()
    if output.exists():
        raise ValueError('SIP output directory already exists')
    output.mkdir(parents=True)
    root = arguments.runtime_root.resolve()
    runtime = json.loads((root / 'runtime.json').read_text())
    if runtime['api'] != 28:
        raise ValueError('SIP service contracts require API28')
    work = Path(tempfile.mkdtemp(prefix='saildroid-sip-', dir='/var/tmp'))
    marker = dict(work=str(work), creator_uid=os.getuid())
    (work / 'owner.json').write_text(json.dumps(marker))
    work.chmod(0o755)
    before = {name: digest(root / name) for name in ('runtime.json', *runtime['boot_jars'],
              'lib/runtime.jar', 'lib/java-cli-bootstrap.jar')}
    result = dict(passed=False, raw_art=arguments.raw_art, runtime_inputs=before,
                  fixture=marker, uid=pwd.getpwnam('nobody').pw_uid)
    try:
        prepare_paths(root, work)
        data = work / 'homeart/data/sip-fixture'
        data.mkdir()
        (data / 'empty-libs').mkdir()
        (data / 'app-data').mkdir()
        classes = work / 'classes'
        bridge_classes = work / 'bridge-classes'
        classes.mkdir()
        bridge_classes.mkdir()
        sip_references = arguments.sip_references
        if sip_references is None:
            reference_output = work / 'sip-references'
            prepared_references = execute(['python3', str(repository / 'scripts/api28/build-sip-service.py'),
                '--references-only', '--framework', str(arguments.framework), '--output', str(reference_output)],
                output / 'references.log')
            if prepared_references.returncode:
                raise RuntimeError('SIP reference compilation failed')
            sip_references = reference_output / 'references.jar'
        providers = [sip_references, arguments.framework]
        if arguments.reference_classes:
            providers.append(arguments.reference_classes.resolve())
        classpath = os.pathsep.join(map(str, providers))
        sources = repository / 'scripts/compat/sip'
        commands = [
            ['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-cp', classpath,
             '-d', str(classes), str(sources / 'SipMain.java')],
            ['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-cp', classpath,
             '-sourcepath', os.pathsep.join(str(repository / name) for name in JAVA_DIRECTORIES),
             '-d', str(bridge_classes), str(sources / 'SipContracts.java')],
        ]
        for directory, target in ((classes, 'contracts-dex.jar'), (bridge_classes, 'bridge-raw.jar')):
            commands.append(['java', '-cp', str(arguments.r8), 'com.android.tools.r8.D8', '--release',
                             '--min-api', '28', '--lib', str(arguments.framework),
                             '--classpath', str(sip_references), '--output', str(work / target)])
        for index, command in enumerate(commands):
            if index >= 2:
                directory = classes if index == 2 else bridge_classes
                selected = sorted(directory.rglob('*.class')) if index == 2 else sorted(directory.glob('SipContracts*.class'))
                command.extend(map(str, selected))
            compiled = execute(command, output / ('compile-' + str(index) + '.log'))
            if compiled.returncode:
                raise RuntimeError('SIP fixture compilation failed stage ' + str(index))
        shutil.copyfile(sources / 'AndroidManifest.xml', work / 'AndroidManifest.xml')
        packaged = execute(['aapt', 'package', '-f', '-M', str(work / 'AndroidManifest.xml'),
                            '-I', str(root / 'system/framework/framework-res.apk'),
                            '-F', str(data / 'contracts.apk')], output / 'aapt.log')
        if packaged.returncode:
            raise RuntimeError('SIP fixture APK packaging failed')
        with zipfile.ZipFile(data / 'contracts.apk', 'a') as apk, zipfile.ZipFile(work / 'contracts-dex.jar') as dex:
            apk.writestr('classes.dex', dex.read('classes.dex'))
        shutil.copyfile(data / 'contracts.apk', output / 'contracts.apk')
        spec = importlib.util.spec_from_file_location('sip_encoder', repository / 'scripts/api28/encode-platform-dex.py')
        encoder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(encoder)
        flags = encoder.encode_jar(work / 'bridge-raw.jar', [], work / 'bridge.jar',
                                   public_members={'LSipContracts;->run([Ljava/lang/String;)V'})
        bootstrap = work / 'java-cli-bootstrap.jar'
        shutil.copyfile(root / 'lib/java-cli-bootstrap.jar', bootstrap)
        with zipfile.ZipFile(bootstrap, 'a') as target, zipfile.ZipFile(work / 'bridge.jar') as bridge:
            index = 2
            while 'classes' + str(index) + '.dex' in target.namelist():
                index += 1
            target.writestr('classes' + str(index) + '.dex', bridge.read('classes.dex'))
        library_overlay = None
        if arguments.overlay_root:
            library_overlay = work / 'lib'
            shutil.copytree(root / 'lib', library_overlay, symlinks=True)
            for name in ('runtime.jar', 'libsdvoip.so'):
                source = arguments.overlay_root / 'lib' / name
                if source.exists():
                    shutil.copyfile(source, library_overlay / name)
            shutil.copyfile(bootstrap, library_overlay / 'java-cli-bootstrap.jar')
        result['fixture_inputs'] = dict(apk_sha256=digest(data / 'contracts.apk'),
                                        bootstrap_sha256=digest(bootstrap), bridge_flags=flags)
        for path in sources.glob('*.py'):
            shutil.copyfile(path, work / path.name)
        installed = '/opt/saildroid/releases/' + runtime['rpm_activation']['release_id']
        configuration = dict(root=installed, raw=arguments.raw_art, groups=arguments.group or ['suite', 'ipc', 'media'])
        (work / 'configuration.json').write_text(json.dumps(configuration))
        prepare = '''import fcntl,json,os,pathlib,pwd,subprocess,sys
p=pathlib.Path(sys.argv[1]);assert p.resolve().parent==pathlib.Path('/var/tmp') and p.name.startswith('saildroid-sip-')
assert json.loads((p/'owner.json').read_text())==json.loads(sys.argv[2])
u=pwd.getpwnam('nobody')
for folder in [p/'home',p/'homeart']:
    for item in [folder,*folder.rglob('*')]:
        if not item.is_symlink():os.chown(item,u.pw_uid,u.pw_gid)
os.chown(p/'java-cli-bootstrap.jar',0,0);os.chmod(p/'java-cli-bootstrap.jar',0o644)
if (p/'lib').exists():
    for item in [p/'lib',*(p/'lib').rglob('*')]:
        if not item.is_symlink():os.chown(item,0,0)
subprocess.run(['modprobe','binder_linux'],check=True)
binder=p/'homeart/runtime/binder';subprocess.run(['mount','-t','binder','binder',str(binder)],check=True)
request=bytearray(264);request[:7]=b'binder\\0'
with (binder/'binder-control').open('rb') as control:fcntl.ioctl(control.fileno(),0xc1086201,request,True)
os.chown(binder/'binder',u.pw_uid,u.pw_gid);os.chmod(binder/'binder',0o600)
'''
        prepared = execute(['sudo', '-n', 'python3', '-c', prepare, str(work), json.dumps(marker)], output / 'prepare.log')
        if prepared.returncode:
            raise RuntimeError('SIP private Binder preparation failed')
        installed = '/opt/saildroid/releases/' + runtime['rpm_activation']['release_id']
        command = ['bwrap', '--die-with-parent', '--new-session', '--chmod', '0755', '/']
        for name in ('/opt', '/opt/saildroid', '/opt/saildroid/releases', '/var', '/var/tmp', '/home', '/tmp', '/run'):
            command.extend(['--perms', '0755', '--dir', name])
        command.extend(['--ro-bind', '/usr', '/usr', '--ro-bind', '/etc', '/etc',
                        '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/sbin', '/sbin',
                        '--dev-bind', '/dev', '/dev', '--ro-bind', '/sys', '/sys', '--proc', '/proc',
                        '--unshare-pid', '--unshare-net', '--ro-bind', str(root), installed,
                        '--ro-bind', str(work), '/var/tmp/saildroid-compat',
                        '--bind', str(work / 'homeart'), '/home/art',
                        '--dev-bind', str(work / 'homeart/runtime/binder'), '/home/art/runtime/binder',
                        '--bind', str(work / 'home'), '/home/nobody', '--ro-bind', str(work / 'system'), '/system',
                        '--ro-bind', str(root / 'system/fonts'), '/system/fonts',
                        '--ro-bind', str(root / 'system/framework'), '/system/framework',
                        '--ro-bind', str(bootstrap), installed + '/lib/java-cli-bootstrap.jar'])
        if library_overlay:
            command.extend(['--ro-bind', str(library_overlay), installed + '/lib'])
        for name in ('java/dex/art/framework28-classes4.jar',):
            source = arguments.overlay_root / name if arguments.overlay_root else root / name
            if source.exists() and source.resolve() != (root / name).resolve():
                command.extend(['--ro-bind', str(source.resolve()), installed + '/' + name])
        command.extend(['--chdir', '/home/nobody', '--', 'python3', '/var/tmp/saildroid-compat/run.py',
                        '--namespace', '/var/tmp/saildroid-compat/configuration.json'])
        driver = 'import os,resource,sys;os.umask(0o022);resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.execvp(sys.argv[1],sys.argv[1:])'
        execution = execute(['sudo', '-n', 'python3', '-c', driver, 'timeout', '--kill-after=5s', '300s', *command],
                             output / 'namespace.log', timeout=320)
        for path in data.glob('*.log'):
            shutil.copyfile(path, output / path.name)
        for path in (work / 'home').glob('*.log'):
            shutil.copyfile(path, output / path.name)
        if (data / 'namespace-result.json').exists():
            result.update(json.loads((data / 'namespace-result.json').read_text()))
        result['returncode'] = execution.returncode
        result['passed'] = result['passed'] and execution.returncode == 0
        print(execution.stdout[-11000:], flush=True)
    except Exception as failure:
        result['error'] = dict(type=type(failure).__name__, message=str(failure))
        (output / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        result['runtime_unchanged'] = before == {name: digest(root / name) for name in before}
        cleanup = '''import json,pathlib,shutil,subprocess,sys
p=pathlib.Path(sys.argv[1]);assert not p.is_symlink() and p.resolve().parent==pathlib.Path('/var/tmp') and p.name.startswith('saildroid-sip-')
assert json.loads((p/'owner.json').read_text())==json.loads(sys.argv[2])
binder=p/'homeart/runtime/binder';mounts=[line.split()[4] for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines()]
if str(binder) in mounts:subprocess.run(['umount',str(binder)],check=True)
shutil.rmtree(p)
'''
        removed = execute(['sudo', '-n', 'python3', '-c', cleanup, str(work), json.dumps(marker)], output / 'cleanup.log')
        result['fixture_removed'] = removed.returncode == 0 and not work.exists()
        result['passed'] = result['passed'] and result['runtime_unchanged'] and result['fixture_removed']
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', type=Path)
    for name in ('runtime-root', 'framework', 'r8', 'reference-classes', 'sip-references', 'output', 'overlay-root'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--raw-art', action='store_true')
    parser.add_argument('--group', choices=('suite', 'ipc', 'media'), action='append')
    arguments = parser.parse_args()
    if arguments.namespace:
        return namespace_driver(json.loads(arguments.namespace.read_text()))
    if not all((arguments.runtime_root, arguments.framework, arguments.r8, arguments.output)):
        parser.error('Runtime, framework, R8 and output are required')
    result = run(arguments)
    print('SIP_RESULT=' + ('PASS' if result['passed'] else 'FAIL'), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
