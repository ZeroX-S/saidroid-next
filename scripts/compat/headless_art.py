"""Execute packaged ART contracts with private Android paths and test data."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import traceback
import zipfile


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def namespace_command(root, work, main, case, bootstrap=None):
    runtime = json.loads((root / 'runtime.json').read_text())
    release = runtime.get('rpm_activation', {}).get('release_id', root.name)
    if not release or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in release):
        raise ValueError('Invalid runtime release identity')
    installed = '/opt/saildroid/releases/' + release
    user = 'nobody'
    args = ['bwrap', '--die-with-parent', '--new-session', '--chmod', '0755', '/']
    for directory in ('/opt', '/opt/saildroid', '/opt/saildroid/releases', '/var', '/var/tmp', '/home', '/tmp', '/run'):
        args.extend(['--perms', '0755', '--dir', directory])
    args.extend(['--ro-bind', '/usr', '/usr', '--ro-bind', '/etc', '/etc',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/sbin', '/sbin', '--dev-bind', '/dev', '/dev',
            '--ro-bind', '/sys', '/sys', '--proc', '/proc', '--unshare-pid', '--unshare-net',
            '--ro-bind', str(root), installed,
            '--ro-bind', str(work), '/var/tmp/saildroid-compat',
            '--bind', str(work / 'homeart'), '/home/art',
            '--dev-bind', str(work / 'homeart/runtime/binder'), '/home/art/runtime/binder',
            '--bind', str(work / 'home'), '/home/' + user,
            '--ro-bind', str(work / 'system'), '/system',
            '--ro-bind', str(root / 'system/fonts'), '/system/fonts',
            '--ro-bind', str(root / 'system/framework'), '/system/framework'])
    if bootstrap:
        args.extend(['--ro-bind', str(bootstrap), installed + '/lib/java-cli-bootstrap.jar'])
    args.extend(['--chdir', '/home/' + user, '--', 'runuser', '-u', user, '--', 'env', '-i',
                 'PATH=/usr/bin:/bin', 'LC_ALL=C', 'HOME=/home/' + user,
                 'USER=' + user, 'LOGNAME=' + user, 'ANDROID_DATA=/home/art/data',
                 'SAILDROID_ANDROID_LOG_STDERR=1', 'SAILDROID_HWUI=0',
                 'XDG_RUNTIME_DIR=/var/tmp/saildroid-compat/wayland',
                 'WAYLAND_DISPLAY=compat-wayland',
                 'SAILDROID_DISPLAY_WIDTH=480', 'SAILDROID_DISPLAY_HEIGHT=960',
                 installed + '/bin/dalvikvm', '-Xcheck:jni', '-cp',
                 '/var/tmp/saildroid-compat/contracts.apk', main, case])
    # sudo on this host uses umask 077. Set namespace directory permissions
    # explicitly before bubblewrap creates paths traversed by the ordinary user.
    driver = 'import os,resource,sys; os.umask(0o022); resource.setrlimit(resource.RLIMIT_CORE,(0,0)); os.execvp(sys.argv[1],sys.argv[1:])'
    return ['sudo', '-n', 'python3', '-c', driver, 'timeout', '--kill-after=5s', '180s', *args]


def prepare_paths(root, work):
    runtime = json.loads((root / 'runtime.json').read_text())
    installed = '/opt/saildroid/releases/' + runtime.get('rpm_activation', {}).get('release_id', root.name)
    for name in ('home', 'homeart/data/compat', 'homeart/apps', 'homeart/runtime/binder',
                 'system/etc', 'system/fonts', 'system/framework', 'wayland'):
        (work / name).mkdir(parents=True, exist_ok=True)
    (work / 'homeart/api29-root').symlink_to(installed)
    if runtime['api'] == 28:
        (work / 'system/etc/ld.config.28.txt').write_text(
            '# API28 loader selection inside the compatibility mount namespace.\n')
    for name in ('fonts.xml', 'font_fallback.xml'):
        source = root / 'system/etc' / name
        if source.exists():
            shutil.copyfile(source, work / 'system/etc' / name)


def execute(command, log, timeout=210, environment=None):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', env=environment, timeout=timeout)
    except subprocess.TimeoutExpired as failure:
        text = failure.stdout or b''
        result = subprocess.CompletedProcess(command, 124, text.decode('utf-8', 'replace')
                                              if isinstance(text, bytes) else text)
    log.write_text(result.stdout, encoding='utf-8')
    return result


def events(text):
    rows = []
    for line in text.replace('\0', '').splitlines():
        if line.startswith('COMPAT_EVENT='):
            name, status, detail = line.removeprefix('COMPAT_EVENT=').split('|', 2)
            rows.append(dict(name=name, status=status, detail=detail))
    return rows


def run(root, framework, r8, output, repository):
    output.mkdir(parents=True)
    runtime = json.loads((root / 'runtime.json').read_text())
    upstream = repository / 'scripts/compat/upstream'
    sources = repository / 'scripts/compat/headless'
    manifest = json.loads((upstream / 'manifest.json').read_text())
    canonical_sources = {}
    source_checks = {}
    for name, record in manifest['files'].items():
        raw = (upstream / name).read_bytes()
        canonical = raw.replace(b'\r\n', b'\n')
        canonical_sha = hashlib.sha256(canonical).hexdigest()
        if canonical_sha != record['sha256']:
            raise ValueError('Pinned AOSP test source differs: ' + name)
        canonical_sources[name] = canonical
        source_checks[name] = dict(raw_sha256=hashlib.sha256(raw).hexdigest(),
                                   canonical_sha256=canonical_sha)
    image_paths = [path.relative_to(root).as_posix()
                   for path in sorted((root / 'system/framework/arm64').glob('boot*'))
                   if path.is_file() and path.suffix in ('.art', '.oat', '.vdex')]
    if 'system/framework/arm64/boot.art' not in image_paths:
        raise ValueError('Packaged ARM64 boot image is missing')
    native_inputs = runtime.get('api28_public_api', {}).get('native_libraries', {})
    before = {relative: digest(root / relative) for relative in
              ['runtime.json', 'bin/dalvikvm', 'libexec/dalvikvm-real',
               'lib/libart.so', 'lib/libsdbridge.so', 'lib/libsdwindow.so',
               'lib/java-cli-bootstrap.jar', 'lib/runtime.jar', 'linker-config/runtime.cfg',
               *runtime['boot_jars'], *image_paths, *native_inputs]}
    for relative, expected in native_inputs.items():
        if before[relative] != expected:
            raise ValueError('Public API native input differs: ' + relative)
    result = dict(passed=False, api=runtime['api'], uid=pwd.getpwnam('nobody').pw_uid,
                  framework_registrations_expected=97 if runtime['api'] == 28 else 104,
                  runtime_inputs=before, aosp_sources=manifest,
                  aosp_source_checks=source_checks, groups=[])
    work = Path(tempfile.mkdtemp(prefix='saildroid-compat-', dir='/var/tmp'))
    marker = dict(work=str(work), creator_uid=os.getuid())
    result['fixture'] = marker
    (work / 'owner.json').write_text(json.dumps(marker))
    compositor = None
    compositor_log = None
    try:
        work.chmod(0o755)
        prepare_paths(root, work)
        java_directory = Path(os.environ['JAVA_HOME']) / 'bin' if os.environ.get('JAVA_HOME') else None
        java = str(java_directory / 'java') if java_directory else 'java'
        javac = str(java_directory / 'javac') if java_directory else 'javac'
        version = execute([java, '-version'], output / 'reference-java-version.log')
        compiler_version = execute([javac, '-version'], output / 'javac-version.log')
        if version.returncode or compiler_version.returncode:
            raise RuntimeError('The selected Java toolchain is unavailable')
        result['toolchain'] = dict(java=version.stdout.strip(), javac=compiler_version.stdout.strip())
        classes = work / 'classes'
        classes.mkdir()
        bridge_classes = work / 'bridge-classes'
        bridge_classes.mkdir()
        canonical_directory = work / 'upstream'
        canonical_directory.mkdir()
        for name, content in canonical_sources.items():
            (canonical_directory / name).write_bytes(content)
        commands = [
            [javac, '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-cp', str(framework),
             '-d', str(classes), *[str(path) for path in sorted(sources.glob('*.java'))
                                  if path.name != 'RuntimeContracts.java'],
             *[str(canonical_directory / name) for name in manifest['files']]],
            [javac, '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-cp', str(framework),
             '-d', str(bridge_classes), str(sources / 'RuntimeContracts.java')],
        ]
        for index, command in enumerate(commands):
            compiled = execute(command, output / ('compile-' + str(index) + '.log'))
            if compiled.returncode:
                raise RuntimeError('Contract compilation failed, stage ' + str(index))
        for index, (directory, target) in enumerate(((classes, 'contracts-dex.jar'),
                                                     (bridge_classes, 'bridge-raw.jar')), start=2):
            compiled_classes = sorted(directory.rglob('*.class'))
            if not compiled_classes:
                raise RuntimeError('Contract class files missing, stage ' + str(index))
            command = [java, '-cp', str(r8), 'com.android.tools.r8.D8', '--release',
                       '--min-api', str(runtime['api']), '--lib', str(framework),
                       '--output', str(work / target), *map(str, compiled_classes)]
            compiled = execute(command, output / ('compile-' + str(index) + '.log'))
            if compiled.returncode:
                raise RuntimeError('Contract DEX compilation failed, stage ' + str(index))
        xml = ('<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
               'package="org.saildroid.compat" android:versionCode="1" android:versionName="1">'
               '<uses-sdk android:minSdkVersion="' + str(runtime['api']) + '" android:targetSdkVersion="' + str(runtime['api']) + '"/>'
               '<application android:label="Compatibility fixture" android:hardwareAccelerated="false">'
               '<activity android:name="org.saildroid.compat.ProbeActivity" android:exported="true"/>'
               '<receiver android:name="org.saildroid.compat.ProbeReceiver" android:process=":receiver" android:exported="false"/>'
               '</application></manifest>')
        (work / 'AndroidManifest.xml').write_text(xml)
        packaged = execute(['aapt', 'package', '-f', '-M', str(work / 'AndroidManifest.xml'),
                            '-I', str(root / 'system/framework/framework-res.apk'),
                            '-F', str(work / 'contracts.apk')], output / 'aapt.log')
        if packaged.returncode:
            raise RuntimeError('Contract APK resource packaging failed')
        with zipfile.ZipFile(work / 'contracts.apk', 'a') as apk, zipfile.ZipFile(work / 'contracts-dex.jar') as dex:
            for item in dex.infolist():
                apk.writestr(item, dex.read(item))
            if runtime['api'] == 28:
                public_api = repository / 'scripts/api28/public-api-compat'
                restored = (public_api / 'restored-members.txt').read_bytes()
                pinned = json.loads((public_api / 'sources.json').read_text())
                if hashlib.sha256(restored).hexdigest() != pinned['restored_members_sha256']:
                    raise ValueError('Restored public member fixture differs')
                apk.writestr('org/saildroid/compat/api28-restored-members.txt', restored)
        shutil.copyfile(work / 'contracts.apk', output / 'contracts.apk')
        spec = importlib.util.spec_from_file_location('compat_encoder', repository / 'scripts/api28/encode-platform-dex.py')
        encoder = importlib.util.module_from_spec(spec); spec.loader.exec_module(encoder)
        public = {'Lorg/saildroid/compat/RuntimeContracts;->run(Ljava/lang/String;Ljava/lang/ClassLoader;)V'}
        flags = encoder.encode_jar(work / 'bridge-raw.jar', [], work / 'bridge.jar', public_members=public)
        bootstrap = work / 'java-cli-bootstrap.jar'
        shutil.copyfile(root / 'lib/java-cli-bootstrap.jar', bootstrap)
        with zipfile.ZipFile(bootstrap, 'a') as target, zipfile.ZipFile(work / 'bridge.jar') as bridge:
            existing = target.namelist()
            index = 2
            while 'classes' + str(index) + '.dex' in existing:
                index += 1
            target.writestr('classes' + str(index) + '.dex', bridge.read('classes.dex'))
        identity = dict(apk_sha256=digest(work / 'contracts.apk'), bootstrap_sha256=digest(bootstrap),
                        bootstrap_baseline_sha256=before['lib/java-cli-bootstrap.jar'], bridge_flags=flags,
                        runtime_jar_sha256=before['lib/runtime.jar'],
                        boot_images={path: before[path] for path in image_paths},
                        namespace=dict(private_android_paths=True, api28_loader_marker=runtime['api'] == 28,
                                       network='private', compositor='headless-weston-pixman', binder='private-binderfs'))
        (output / 'test-inputs.json').write_text(json.dumps(identity, indent=2) + '\n')
        # Normalize only this newly created fixture. The CLI bootstrap overlay
        # needs root ownership while private application data belongs to nobody.
        prepare = '''import fcntl,json,os,pathlib,pwd,subprocess,sys
p = pathlib.Path(sys.argv[1])
expected = json.loads(sys.argv[2])
assert json.loads((p / 'owner.json').read_text()) == expected
assert p.resolve().parent == pathlib.Path('/var/tmp') and p.name.startswith('saildroid-compat-')
u = pwd.getpwnam('nobody')
for folder in [p/'home',p/'homeart',p/'wayland']:
    for item in [folder,*folder.rglob('*')]:
        if not item.is_symlink():os.chown(item,u.pw_uid,u.pw_gid)
os.chmod(p/'wayland',0o700)
os.chown(p/'java-cli-bootstrap.jar',0,0);os.chmod(p/'java-cli-bootstrap.jar',0o644)
subprocess.run(['modprobe', 'binder_linux'], check=True)
binder = p / 'homeart/runtime/binder'
subprocess.run(['mount', '-t', 'binder', 'binder', str(binder)], check=True)
# linux/android/binderfs.h defines a 256-byte name followed by two uint32 values.
request = bytearray(264)
request[:7] = b'binder\\0'
with (binder / 'binder-control').open('rb') as control:
    fcntl.ioctl(control.fileno(), 0xc1086201, request, True)
os.chown(binder / 'binder', u.pw_uid, u.pw_gid)
os.chmod(binder / 'binder', 0o600)
print('COMPAT_BINDER=ready|backend=private-binderfs|uid=' + str(u.pw_uid))
'''
        prepared = execute(['sudo', '-n', 'python3', '-c', prepare, str(work), json.dumps(marker)],
                           output / 'fixture-prepare.log')
        if prepared.returncode:
            raise RuntimeError('Private test fixture preparation failed')
        result['binder'] = dict(backend='private-binderfs', device_owner_uid=result['uid'])
        reference = execute([java, '-cp', str(classes) + ':' + str(framework),
                             'org.saildroid.compat.CoreContracts', 'core'], output / 'reference-jdk.log')
        reference_events = events(reference.stdout)
        result['reference'] = dict(kind='host-JDK', source='Pinned unmodified AOSP libcore tests',
                                    returncode=reference.returncode, tests=len(reference_events))
        compositor_log = (output / 'weston.log').open('w')
        compositor = subprocess.Popen(['sudo', '-n', 'timeout', '--kill-after=5s', '900s',
            'runuser', '-u', 'nobody', '--', 'env', 'XDG_RUNTIME_DIR=' + str(work / 'wayland'),
            'weston', '--backend=headless', '--renderer=pixman', '--socket=compat-wayland',
            '--width=480', '--height=960', '--idle-time=0', '--no-config'],
            stdout=compositor_log, stderr=subprocess.STDOUT, start_new_session=True)
        # XDG_RUNTIME_DIR belongs to nobody with mode 0700. Check the socket
        # through the same scoped sudo access used to create the fixture.
        readiness = '''import pathlib,sys,time
socket = pathlib.Path(sys.argv[1]) / 'wayland/compat-wayland'
deadline = time.monotonic() + 15
while not socket.is_socket() and time.monotonic() < deadline:
    time.sleep(0.1)
sys.exit(0 if socket.is_socket() else 1)
'''
        ready = execute(['sudo', '-n', 'python3', '-c', readiness, str(work)],
                        output / 'weston-ready.log', timeout=20)
        if ready.returncode or compositor.poll() is not None:
            raise RuntimeError('Private headless compositor failed to start')
        groups = ['core', 'activity-task', 'activity-routing', 'window-jni', 'intent-loader',
                  'bitmap-jni', 'receiver-jni']
        if runtime['api'] == 28:
            groups.extend(['api28-public-members', 'sip-profile', 'rtp-jni'])
        for group in groups:
            main = 'org.saildroid.compat.CoreContracts' if group == 'core' else 'org.saildroid.compat.PlatformContracts'
            command = namespace_command(root, work, main, group, bootstrap)
            execution = execute(command, output / (group + '.log'))
            terminal = events(execution.stdout)
            passed = execution.returncode == 0 and bool(terminal) and all(row['status'] == 'PASS' for row in terminal)
            if group == 'core':
                passed = passed and len(terminal) == len(reference_events) and 'COMPAT_SUITE=core|' in execution.stdout
            bootstrap_ready = 'SD_JAVA_CLI=ready|sdk=' + str(runtime['api']) in execution.stdout
            passed = passed and bootstrap_ready
            result['groups'].append(dict(name=group, passed=passed, returncode=execution.returncode,
                                         terminal_events=terminal, bootstrap_ready=bootstrap_ready))
            print('HEADLESS_CONTRACT=' + group + '|' + ('PASS' if passed else 'FAIL'), flush=True)
        art_events = result['groups'][0]['terminal_events']
        reference_by_name = {row['name']: row['status'] for row in reference_events}
        art_by_name = {row['name']: row['status'] for row in art_events}
        result['comparison'] = dict(matched=len(reference_by_name.keys() & art_by_name.keys()),
            changed=[name for name in sorted(reference_by_name.keys() & art_by_name.keys())
                     if reference_by_name[name] != art_by_name[name]],
            missing=sorted(reference_by_name.keys() - art_by_name.keys()),
            added=sorted(art_by_name.keys() - reference_by_name.keys()))
        result['passed'] = reference.returncode == 0 and all(row['passed'] for row in result['groups']) and not any(
            result['comparison'][name] for name in ('changed', 'missing', 'added'))
    except Exception as failure:
        result['error'] = dict(type=type(failure).__name__, message=str(failure))
        (output / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
    finally:
        cleanup_errors = []
        try:
            if compositor and compositor.poll() is None:
                if os.getpgid(compositor.pid) != compositor.pid:
                    raise RuntimeError('Compositor process identity differs during cleanup')
                subprocess.run(['sudo', '-n', 'kill', '-TERM', '--', '-' + str(compositor.pid)], check=True)
                try:
                    compositor.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if os.getpgid(compositor.pid) != compositor.pid:
                        raise RuntimeError('Compositor process identity differs before forced cleanup')
                    subprocess.run(['sudo', '-n', 'kill', '-KILL', '--', '-' + str(compositor.pid)], check=True)
                    compositor.wait(timeout=5)
        except Exception as failure:
            cleanup_errors.append('compositor: ' + str(failure))
        try:
            if compositor_log:
                compositor_log.close()
            after = {relative: digest(root / relative) for relative in before}
            result['runtime_unchanged'] = before == after
        except Exception as failure:
            result['runtime_unchanged'] = False
            cleanup_errors.append('runtime verification: ' + str(failure))
        cleanup = '''import json,pathlib,shutil,subprocess,sys
p=pathlib.Path(sys.argv[1]); assert not p.is_symlink() and p.resolve().parent==pathlib.Path('/var/tmp') and p.name.startswith('saildroid-compat-')
assert json.loads((p/'owner.json').read_text())==json.loads(sys.argv[2])
binder = p / 'homeart/runtime/binder'
mounts = [line.split()[4] for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines()]
if str(binder) in mounts:
    subprocess.run(['umount', str(binder)], check=True)
shutil.rmtree(p)
'''
        try:
            removed = subprocess.run(['sudo', '-n', 'python3', '-c', cleanup, str(work), json.dumps(marker)],
                                     capture_output=True, text=True, timeout=30)
            result['fixture_removed'] = removed.returncode == 0 and not work.exists()
            if not result['fixture_removed']:
                cleanup_errors.append('fixture: ' + removed.stderr.strip())
        except Exception as failure:
            result['fixture_removed'] = False
            cleanup_errors.append('fixture: ' + str(failure))
        result['cleanup_errors'] = cleanup_errors
        result['passed'] = (result['passed'] and result['runtime_unchanged']
                            and result['fixture_removed'] and not cleanup_errors)
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result
