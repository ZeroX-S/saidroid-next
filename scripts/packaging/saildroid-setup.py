#!/usr/bin/env python3
"""Sailfish runtime activation and private Binder setup.

Production CLI has no prefix/test override. Tests inject a separate Platform
implementation and are refused on Sailfish. Every production mutation is local.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

RELEASES = '/opt/saildroid/releases'
LEGACY_RELEASES = '/home/art/releases'
STATE = '/var/lib/saildroid'
MANIFEST = 'share/packaging/activation-manifest.json'
REGISTRY_JAR = 'share/packaging/setup-registry.jar'
MANAGER = 'org.saildroid.manager'
MANAGER_ID = 'org.saildroid.app.p' + hashlib.sha256(MANAGER.encode()).hexdigest()[:20]
ID = re.compile(r'[a-z0-9][a-z0-9.-]{0,100}\Z')
PACKAGE = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\Z')


def rpm_install_scripts(release_id):
    require(ID.fullmatch(release_id), 'Unsafe release id')
    release = RELEASES + '/' + release_id
    preflight = '''import os
from pathlib import Path
release = %r
busy = []
for process in Path('/proc').iterdir():
    if not process.name.isdigit():
        continue
    try:
        executable = os.readlink(process / 'exe').removesuffix(' (deleted)')
        if executable.startswith(release + '/'):
            busy.append(process.name)
    except (FileNotFoundError, ProcessLookupError):
        pass
if busy:
    raise SystemExit('Close SailDroid before updating this runtime. Processes: ' + ', '.join(busy))
''' % release
    return {'preinstall': '/usr/bin/python3 -c ' + shlex.quote(preflight),
            'posttrans': shlex.quote(release + '/bin/saildroid-setup') + ' activate ' + shlex.quote(release_id)}


def rpm_activation_enabled(runtime, release_id):
    activation = runtime.get('rpm_activation')
    if activation is None:
        return False
    require(activation == dict(schema='saildroid-rpm-activation-v1', mode='posttrans', release_id=release_id),
            'Unsupported RPM activation policy')
    return True


def check_rpm_scripts(runtime, release_id, scripts):
    expected = rpm_install_scripts(release_id) if rpm_activation_enabled(runtime, release_id) else {}
    sections = re.split(r'^([a-z]+) scriptlet \(using /bin/sh\):\n', scripts, flags=re.MULTILINE)
    require(sections[0] == '', 'Unexpected RPM installation scriptlet header')
    actual = {}
    for index in range(1, len(sections), 2):
        name, body = sections[index:index + 2]
        require(name not in actual, 'Duplicate RPM installation scriptlet')
        actual[name] = body.rstrip()
    require(actual == {name: body.rstrip() for name, body in expected.items()},
            'Runtime RPM installation scriptlets differ from the activation policy')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def native_bootstrap_capability(runtime):
    bootstrap = runtime.get('native_bootstrap')
    if bootstrap is None:
        return 'cap_sys_resource=ep'
    require(isinstance(bootstrap, dict)
            and bootstrap.get('schema') == 'saildroid-native-bootstrap-v1'
            and set(bootstrap) == {'schema', 'capabilities'}
            and bootstrap['capabilities'] in ('cap_sys_resource=ep', 'cap_dac_override,cap_sys_resource=ep'),
            'Unsupported native bootstrap capability policy')
    return bootstrap['capabilities']


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def document(path):
    return json.loads(path.read_text())


def fsync_directory(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_file(path, data, mode=0o600):
    fd, name = tempfile.mkstemp(prefix='.saildroid-', dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path, value):
    atomic_file(path, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def no_links(path, floor=Path('/')):
    require(path.is_absolute(), 'Path must be absolute')
    current = floor
    for part in path.relative_to(floor).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            require(not current.is_symlink(), 'Unexpected symlink: ' + str(current))


def trusted(path, floor=Path('/'), directory=False):
    no_links(path, floor)
    current = path
    while True:
        s = current.lstat()
        require(s.st_uid == 0 and not stat.S_IMODE(s.st_mode) & 0o022,
                'Path is not root-owned and immutable: ' + str(current))
        if current == floor:
            break
        current = current.parent
    s = path.lstat()
    require(stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode),
            'Wrong trusted path type: ' + str(path))


def safe_relative(name):
    p = PurePosixPath(name)
    require(name and not p.is_absolute() and '..' not in p.parts and '.' not in p.parts
            and re.fullmatch(r'[A-Za-z0-9_./+@=-]+', name), 'Unsafe manifest path')
    return p


def desktop_id(package):
    return 'org.saildroid.app.p' + hashlib.sha256(package.encode()).hexdigest()[:20]


def user_files(home, operation, values):
    """Executed after dropping to defaultuser; never write a user path as root."""
    home = Path(home)
    no_links(home)
    require(home.is_dir(), 'User home missing')
    def path_for(relative):
        p = PurePosixPath(relative)
        require(p.parent.as_posix() in ('.local/share/applications', '.local/share/dbus-1/services')
                and p.name.startswith(('org.saildroid.app.p', 'saildroid-'))
                and p.suffix in ('.desktop', '.service') and '/' not in p.name,
                'User file is outside the SailDroid launcher namespace')
        path = home / relative
        no_links(path)
        return path
    if operation == 'snapshot':
        result = {}
        for relative in values:
            path = path_for(relative)
            if not path.exists():
                result[relative] = None
                continue
            require(path.is_file() and path.stat().st_size <= 1024 * 1024,
                    'Invalid launcher file: ' + relative)
            result[relative] = dict(data=base64.b64encode(path.read_bytes()).decode(),
                                    mode=stat.S_IMODE(path.stat().st_mode))
        return result
    require(operation == 'restore', 'Unknown user operation')
    for relative, value in values.items():
        path = path_for(relative)
        if value is None:
            if path.exists():
                require(path.is_file(), 'Cannot remove non-file launcher')
                path.unlink()
                fsync_directory(path.parent)
            continue
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        no_links(path)
        require(value['mode'] in (0o600, 0o644, 0o700, 0o755), 'Unexpected launcher mode')
        atomic_file(path, base64.b64decode(value['data'], validate=True), value['mode'])
    return {'ready': True}


class Platform:
    prefix = Path('/')
    fixture = False

    def path(self, absolute):
        p = PurePosixPath(absolute)
        require(p.is_absolute() and '..' not in p.parts, 'Invalid absolute path')
        return self.prefix.joinpath(*p.parts[1:])

    def account(self):
        account = pwd.getpwnam('defaultuser')
        require(account.pw_uid > 0 and account.pw_gid > 0, 'defaultuser must be an ordinary account')
        return dict(name=account.pw_name, uid=account.pw_uid, gid=account.pw_gid,
                    home=account.pw_dir, groups=os.getgrouplist(account.pw_name, account.pw_gid))

    def check_system(self):
        require(os.geteuid() == 0 and os.getuid() == 0, 'Run this command explicitly as root')
        require(sys.version_info >= (3, 9), 'Setup requires Python 3.9 or newer for explicit UID/group dropping')
        values = {}
        for line in self.path('/etc/os-release').read_text().splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                parsed = shlex.split(value)
                if parsed:
                    values[key] = parsed[0]
        require(values.get('ID') == 'sailfishos' and re.fullmatch(r'5\.[23](?:\.[0-9]+)*', values.get('VERSION_ID', '')),
                'This setup supports Sailfish OS 5.2 and 5.3')
        require(platform.machine() == 'aarch64', 'This release requires aarch64')
        for tool in ('rpm', 'getcap'):
            require(shutil.which(tool), 'Required platform tool missing: ' + tool)
        return values

    def run(self, command, **kwargs):
        return subprocess.run(command, capture_output=True, text=True, timeout=120,
                              env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}, **kwargs)

    def prepare_binder(self, account, release):
        helper = release / 'bin/saildroid-binder-setup.py'
        if not helper.exists():
            # Older releases can still use an already provisioned private device.
            require(self.path('/home/art/runtime/binder/binder').exists(),
                    'This release lacks private Binder provisioning; install an updated release')
            return
        trusted(helper, self.prefix)
        result = self.run([sys.executable, str(helper), '--install-service'])
        require(result.returncode == 0 and 'SAILDROID_BINDER_READY' in result.stdout,
                'Private Binder provisioning failed: ' + result.stdout + result.stderr)

    def check_package(self, release, release_id):
        name = 'saildroid-runtime-' + release_id
        q = self.run(['rpm', '-qf', '--qf', '%{NAME}\n%{ARCH}\n', str(release / 'runtime.json')])
        require(q.returncode == 0 and q.stdout.splitlines() == [name, 'aarch64'],
                'Release is not owned by its expected aarch64 RPM')
        q = self.run(['rpm', '-V', '--noscripts', name])
        require(q.returncode == 0 and not q.stdout.strip(), 'RPM verification failed: ' + q.stdout + q.stderr)
        q = self.run(['rpm', '-q', '--scripts', name])
        require(q.returncode == 0, 'Cannot inspect RPM installation scriptlets')
        check_rpm_scripts(document(release / 'runtime.json'), release_id, q.stdout)
        q = self.run(['rpm', '-q', '--requires', name])
        require(q.returncode == 0, 'Cannot read RPM dependencies')
        requirements = q.stdout.splitlines()
        # RPM verifies installed dependency expressions with its own solver.
        # `rpm -q --whatprovides 'name >= version'` is a name lookup on some
        # target RPM versions and incorrectly rejects satisfied dependencies.
        dependencies = self.run(['rpm', '-V', '--nofiles', '--noscripts', name])
        require(dependencies.returncode == 0 and not dependencies.stdout.strip(),
                'Unsatisfied RPM dependency: ' + dependencies.stdout + dependencies.stderr)
        return dict(package=name, dependencies=len(requirements))

    def check_capabilities(self, release, legacy=False):
        q = self.run(['getcap', '-r', str(release)])
        require(q.returncode == 0, 'Cannot inspect file capabilities')
        capability = native_bootstrap_capability(document(release / 'runtime.json'))
        ordinary = [str(release / 'libexec/saildroid-app') + ' ' + capability]
        lines = q.stdout.splitlines()
        if lines == ordinary:
            return
        # The accepted pre-RPM native release carried two distinct historical
        # capability bootstrap ELFs. Preserve that immutable recovery target;
        # never infer an exception from its self-declared manifest alone.
        known_legacy = {
            'libexec/saildroid-app': '2ff709408f21d8f2b514e76ebb63a489652eba41c073341cb28db2f54630fe98',
            'libexec/saildroid-launch': 'a56df520408a7856f0ae63463c3a13ed4b212001c955332a3c0105be7f72bfbb',
        }
        expected = {str(release / relative) + ' cap_sys_resource=ep' for relative in known_legacy}
        require(capability == 'cap_sys_resource=ep'
                and legacy and release.parent == self.path(LEGACY_RELEASES)
                and len(lines) == len(expected) and set(lines) == expected,
                'Only the native bootstrap may carry its declared capabilities')
        for relative, expected_hash in known_legacy.items():
            path = release / relative
            trusted(path, self.prefix)
            require(path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o755
                    and digest(path) == expected_hash,
                    'Unrecognized legacy capability bootstrap: ' + relative)

    def busy(self):
        result = []
        for p in Path('/proc').iterdir():
            if not p.name.isdigit() or int(p.name) == os.getpid():
                continue
            try:
                raw = (p / 'stat').read_text()
                if raw[raw.rfind(') ') + 2:].split()[0] in ('Z', 'X'):
                    continue
                exe = os.readlink(p / 'exe')
                if exe.endswith(' (deleted)'):
                    exe = exe[:-10]
                command = (p / 'cmdline').read_bytes()
                scoped = any(exe.startswith(root + '/') for root in (RELEASES, LEGACY_RELEASES))
                if ((scoped and Path(exe).name in ('saildroid-host', 'saildroid-app', 'dalvikvm', 'dalvikvm-real'))
                    or exe == '/home/art/bin/dalvikvm'
                    or b'api29-root/lib/runtime.jar' in command
                    or command.startswith((b'org.saildroid.manager\0', b'saildroid-supervisor:'))):
                    result.append(dict(pid=int(p.name), executable=exe))
            except (FileNotFoundError, ProcessLookupError):
                continue
        return result

    def user_environment(self, account):
        runtime = '/run/user/' + str(account['uid'])
        return dict(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LC_ALL='C.UTF-8', HOME=account['home'],
                    USER=account['name'], LOGNAME=account['name'], XDG_RUNTIME_DIR=runtime,
                    DBUS_SESSION_BUS_ADDRESS='unix:path=' + runtime + '/dbus/user_bus_socket',
                    WAYLAND_DISPLAY='../../display/wayland-0', ANDROID_DATA='/home/art/data')

    def as_user(self, account, command, data=None):
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, start_new_session=True,
                                 env=self.user_environment(account), user=account['uid'],
                                 group=account['gid'], extra_groups=account['groups'])
        try:
            stdout, stderr = child.communicate(data, timeout=120)
        except subprocess.TimeoutExpired:
            import signal
            os.killpg(child.pid, signal.SIGKILL)  # Only this setup-owned child group.
            child.communicate()
            raise RuntimeError('Bounded setup subprocess timed out')
        require(child.returncode == 0, 'User setup failed: ' + stderr[-6000:])
        return stdout

    def user_files(self, account, operation, values):
        output = self.as_user(account, [sys.executable, str(Path(__file__).resolve()), '_user-files'],
                              json.dumps(dict(home=account['home'], operation=operation, values=values)))
        return json.loads(output)

    def refresh(self, account, release, helper_release, count):
        classpath = str(helper_release / REGISTRY_JAR) + ':' + str(release / 'share/manager.apk')
        output = self.as_user(account, [str(release / 'bin/dalvikvm'), '-cp', classpath,
                                      'org.saildroid.setup.RefreshLaunchers', str(release)])
        require('SAILDROID_SETUP_REGISTRY=ready|apps=' + str(count) + '|root=' + str(release) in output,
                'Real installed registry did not confirm refresh')
        return output

    def check_session(self, account):
        runtime = self.path('/run/user/' + str(account['uid']))
        no_links(runtime, self.prefix)
        require(runtime.is_dir() and runtime.stat().st_uid == account['uid'], 'defaultuser session is not active')
        for path in (runtime / 'dbus/user_bus_socket', self.path('/run/display/wayland-0')):
            require(path.exists() and stat.S_ISSOCK(path.stat().st_mode), 'Session socket missing: ' + str(path))


class Setup:
    def __init__(self, host):
        self.host = host
        self.account = host.account()
        self.state = host.path(STATE)
        self.link = host.path('/home/art/api29-root')
        self.handles = []

    def make_directory(self, absolute, owner, mode):
        path = self.host.path(absolute)
        no_links(path, self.host.prefix)
        if path.exists():
            require(path.is_dir(), 'Expected a directory: ' + str(path))
            s = path.stat()
            legacy_container = (absolute in ('/home/art/data', '/home/art/runtime')
                                and owner == self.account['uid'] and s.st_uid == 0
                                and s.st_mode & 0o005 == 0o005)
            kernel_binder = False
            if absolute == '/home/art/runtime/binder' and owner == self.account['uid'] and s.st_uid == 0:
                # Existing kernel-binder provisioning belongs to root. Inspect it
                # without opening, replacing or changing the device or metadata.
                trusted(path, self.host.prefix, True)
                require(s.st_gid == 0 and stat.S_IMODE(s.st_mode) == 0o755,
                        'Untrusted kernel-binder directory: ' + str(path))
                node, provision = path / 'binder', path / 'provision.json'
                require(node.exists() and not node.is_symlink() and provision.exists() and not provision.is_symlink(),
                        'Kernel-binder provisioning is missing or linked')
                ns, ps = node.lstat(), provision.lstat()
                require(stat.S_ISCHR(ns.st_mode) and ns.st_uid == owner and stat.S_IMODE(ns.st_mode) == 0o600,
                        'Untrusted kernel-binder device')
                require(stat.S_ISREG(ps.st_mode) and ps.st_uid == 0 and stat.S_IMODE(ps.st_mode) == 0o644,
                        'Untrusted kernel-binder provision metadata')
                kernel_binder = True
            require(s.st_uid == owner or legacy_container or kernel_binder,
                    'Existing storage ownership differs: ' + str(path))
            return path
        path.mkdir(mode=mode)
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            require(os.fstat(descriptor).st_uid == 0, 'Untrusted new storage directory: ' + str(path))
            os.fchown(descriptor, owner, self.account['gid'] if owner else 0)
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)
        return path

    def prepare(self, binder=True):
        for path in ('/home/art', '/home/art/bin', STATE):
            self.make_directory(path, 0, 0o755 if path != STATE else 0o700)
            trusted(self.host.path(path), self.host.prefix, True)
        trusted(self.state, self.host.prefix, True)
        for path in ('/home/art/apps', '/home/art/data', '/home/art/data/shared', '/home/art/data/logs',
                     '/home/art/data/manager', '/home/art/data/binder', '/home/art/runtime'):
            self.make_directory(path, self.account['uid'], 0o700)
        if binder:
            self.make_directory('/home/art/runtime/binder', self.account['uid'], 0o700)
        runtime = '/run/user/' + str(self.account['uid']) + '/saildroid'
        self.make_directory(runtime, self.account['uid'], 0o700)
        self.lock(self.state / 'setup.lock', 0)
        self.lock(self.host.path(runtime) / 'host-manager.lock', self.account['uid'])

    def lock(self, path, owner):
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        s = os.fstat(fd)
        require(stat.S_ISREG(s.st_mode) and s.st_uid in (0, owner), 'Untrusted setup lock')
        if s.st_uid != owner:
            os.fchown(fd, owner, self.account['gid'])
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise RuntimeError('Another setup or native manager startup holds the lock')
        self.handles.append((fd, path))

    def quiet(self):
        busy = self.host.busy()
        require(not busy, 'Close SailDroid-owned apps and native session manager first: ' + json.dumps(busy))
        for fd, path in self.handles:
            s, actual = os.fstat(fd), path.lstat()
            require(s.st_ino == actual.st_ino and s.st_dev == actual.st_dev, 'Setup lock identity changed')

    def read_link(self):
        if not self.link.exists() and not self.link.is_symlink():
            return None
        require(self.link.is_symlink(), 'api29-root must be a symlink; directories are never replaced')
        return os.readlink(self.link)

    def switch(self, value):
        if value is None:
            if self.link.is_symlink():
                self.link.unlink()
                fsync_directory(self.link.parent)
            return
        temporary = self.link.with_name('.api29-root-' + str(os.getpid()))
        require(not temporary.exists() and not temporary.is_symlink(), 'Temporary activation link already exists')
        temporary.symlink_to(value)
        try:
            os.replace(temporary, self.link)
            fsync_directory(self.link.parent)
        finally:
            if temporary.is_symlink():
                temporary.unlink()

    def verify(self, release, legacy=False, expected_manifest=None):
        require(release.parent == self.host.path(LEGACY_RELEASES if legacy else RELEASES), 'Release outside trusted root')
        require(ID.fullmatch(release.name), 'Unsafe release id')
        trusted(release, self.host.prefix, True)
        manifest_path = release / ('install-manifest.json' if legacy else MANIFEST)
        trusted(manifest_path, self.host.prefix)
        manifest_hash = digest(manifest_path)
        if expected_manifest:
            require(manifest_hash == expected_manifest, 'Previous release manifest changed')
        manifest = document(manifest_path)
        if not legacy:
            require(manifest.get('schema') == 'saildroid-activation-manifest-v1' and manifest.get('release_id') == release.name,
                    'Activation manifest identity mismatch')
        files, links = manifest['files'], manifest.get('symlinks', {})
        allowed = set(files) | set(links) | {str(manifest_path.relative_to(release))}
        actual = set()
        actual_directories = set()
        for path in release.rglob('*'):
            relative = str(path.relative_to(release))
            if path.is_symlink():
                actual.add(relative)
            elif path.is_dir():
                actual_directories.add(relative)
                trusted(path, self.host.prefix, True)
            else:
                actual.add(relative)
        require(actual == allowed, 'Release contains missing or unexpected payload files')
        if 'directories' in manifest:
            require(actual_directories == set(manifest['directories']), 'Release directory inventory differs')
        for relative, value in files.items():
            safe_relative(relative)
            path = release / relative
            trusted(path, self.host.prefix)
            s = path.stat()
            require(not value['mode'] & 0o7022 and stat.S_IMODE(s.st_mode) == value['mode'], 'Payload mode mismatch: ' + relative)
            require(s.st_size == value.get('size', value.get('bytes')) and digest(path) == value['sha256'], 'Payload hash mismatch: ' + relative)
        for relative, target in links.items():
            safe_relative(relative)
            path = release / relative
            require(path.is_symlink() and path.exists() and os.readlink(path) == target and not Path(target).is_absolute()
                    and release in path.resolve().parents, 'Payload symlink escapes release: ' + relative)
            require(path.lstat().st_uid == 0, 'Untrusted payload symlink')
        runtime = document(release / 'runtime.json')
        require(runtime.get('api') in (28, 29) and runtime.get('native_host') is True, 'Only the native API28/API29 bootstrap is supported')
        for required in ('libexec/saildroid-app', 'libexec/saildroid-host', 'bin/dalvikvm', 'share/manager.apk'):
            require(required in files, 'Required native installation entry is absent: ' + required)
        if not legacy:
            require(REGISTRY_JAR in files, 'Packaged registry setup payload missing')
        self.host.check_capabilities(release, legacy=legacy)
        package = None if legacy else self.host.check_package(release, release.name)
        return dict(path=str(release), manifest_sha256=manifest_hash, legacy=legacy, package=package)

    def previous(self, link):
        if link is None:
            return None
        resolved = (self.link.parent / link).resolve() if not Path(link).is_absolute() else self.host.path(link)
        # Fixture absolute targets use their own prefix; never resolve real /home.
        if self.host.fixture and str(link).startswith(str(self.host.prefix)):
            resolved = Path(link)
        if (resolved.parent in (self.host.path(RELEASES), self.host.path(LEGACY_RELEASES))
                and ID.fullmatch(resolved.name) and not resolved.exists() and not resolved.is_symlink()):
            return None
        return self.verify(resolved, resolved.parent == self.host.path(LEGACY_RELEASES))

    def installed(self):
        result = []
        store = self.host.path('/home/art/apps')
        if not store.exists():
            return result
        for directory in sorted(store.iterdir()):
            package = directory.name
            if not PACKAGE.fullmatch(package) or package == 'android' or package.startswith('org.saildroid.'):
                continue
            require(directory.is_dir() and not directory.is_symlink(), 'Invalid installed app directory')
            record_path = directory / 'record.json'
            require(record_path.is_file() and not record_path.is_symlink(), 'Installed app record missing')
            record = document(record_path)
            require(record.get('package') == package, 'App record package mismatch')
            result.append(record)
        return result

    def launcher_paths(self, records):
        paths = set()
        for package in [MANAGER] + [r['package'] for r in records]:
            name = desktop_id(package)
            paths.update(('.local/share/applications/' + name + '.desktop',
                          '.local/share/applications/saildroid-' + package + '.desktop',
                          '.local/share/dbus-1/services/' + name + '.service'))
        return sorted(paths)

    def manager_file(self):
        text = ('[Desktop Entry]\nType=Application\nName=SailDroid\n'
                'Exec=/home/art/api29-root/libexec/saildroid-app --manager --desktop-token org.saildroid.manager %u\n'
                'Icon=/home/art/api29-root/share/icons/saildroid.svg\nMimeType=application/vnd.android.package-archive;\n'
                'StartupNotify=true\nX-Sailfish-ApplicationType=generic\n\n[X-Sailjail]\nSandboxing=Disabled\n'
                'OrganizationName=org.saildroid.app\nApplicationName=' + MANAGER_ID.rsplit('.', 1)[1] + '\n')
        return dict(data=base64.b64encode(text.encode()).decode(), mode=0o644)

    def refresh(self, release, helper_release, records):
        self.host.refresh(self.account, release, helper_release, len(records))
        updates = {'.local/share/applications/' + MANAGER_ID + '.desktop': self.manager_file(),
                   '.local/share/applications/saildroid-' + MANAGER + '.desktop': None,
                   '.local/share/dbus-1/services/' + MANAGER_ID + '.service': None}
        self.host.user_files(self.account, 'restore', updates)
        snapshot = self.host.user_files(self.account, 'snapshot', self.launcher_paths(records))
        for record in records:
            if record.get('launchActivity') is None:
                continue
            value = snapshot['.local/share/applications/' + desktop_id(record['package']) + '.desktop']
            require(value is not None, 'Registry did not create app launcher')
            expected = 'Exec=' + str(release) + '/libexec/saildroid-app --package ' + record['package'] + ' --desktop-token ' + record['package']
            require(expected in base64.b64decode(value['data']).decode().splitlines(), 'Registry launcher targets wrong runtime')
        return snapshot

    def wrapper(self, create=True):
        path = self.host.path('/home/art/bin/saildroid-open')
        require(not path.exists() or path.is_symlink(), 'Existing saildroid-open must be the supported native symlink')
        if path.is_symlink():
            require(os.readlink(path) == '../api29-root/libexec/saildroid-app', 'Existing launcher wrapper is not the native bootstrap')
            return True
        if create:
            path.symlink_to('../api29-root/libexec/saildroid-app')
            fsync_directory(path.parent)
        return False

    def history(self):
        path = self.state / 'history.json'
        if not path.exists():
            return []
        trusted(path, self.host.prefix)
        return document(path)

    def check_pending(self):
        require(not (self.state / 'pending.json').exists(), 'Interrupted transaction found; run recover before another switch')

    def change(self, release_id):
        self.host.check_session(self.account)
        release = self.host.path(RELEASES + '/' + release_id)
        target = self.verify(release)
        # Provisioning must also be able to finish a previous partial attempt.
        self.prepare(binder=False)
        self.check_pending()
        self.quiet()
        self.host.prepare_binder(self.account, release)
        self.make_directory('/home/art/runtime/binder', self.account['uid'], 0o700)
        old_link = self.read_link()
        old = self.previous(old_link)
        same = bool(old and old['path'] == target['path'])
        records = self.installed()
        backup = self.host.user_files(self.account, 'snapshot', self.launcher_paths(records))
        for relative, value in backup.items():
            if value:
                text = base64.b64decode(value['data']).decode()
                lines = text.splitlines()
                commands = [line[5:] for line in lines if line.startswith('Exec=')]
                require(len(commands) == 1 and commands[0].startswith(('/home/art/', RELEASES + '/', str(self.host.path('/home/art')) + '/', str(self.host.path(RELEASES)) + '/')),
                        'Launcher namespace collision: ' + relative)
                if relative.endswith('.service'):
                    require('Name=' + Path(relative).stem in lines, 'D-Bus launcher identity differs: ' + relative)
        wrapper_existed = self.wrapper(create=False)
        history = self.history()
        transaction = dict(schema='saildroid-activation-transaction-v1', before_link=old_link, before=old,
                           after=target, launchers_before=backup, wrapper_existed=wrapper_existed,
                           created_epoch=time.time(), account=self.account['name'])
        atomic_json(self.state / 'pending.json', dict(transaction, history_before=history))
        try:
            self.quiet()
            self.wrapper()
            self.switch(str(release))
            self.refresh(release, release, records)
            self.quiet()
            committed = history if same else history + [transaction]
            if same and history and history[-1]['after']['path'] == target['path']:
                committed = history[:-1] + [dict(history[-1], after=target)]
            atomic_json(self.state / 'history.json', committed)
            (self.state / 'pending.json').unlink()
            fsync_directory(self.state)
        except BaseException:
            self.switch(old_link)
            self.host.user_files(self.account, 'restore', backup)
            if not wrapper_existed:
                wrapper = self.host.path('/home/art/bin/saildroid-open')
                if wrapper.is_symlink():
                    wrapper.unlink()
            atomic_json(self.state / 'history.json', history)
            (self.state / 'pending.json').unlink()
            fsync_directory(self.state)
            raise
        return dict(status='already-active' if same else 'activated', release=target, previous=old, refreshed_apps=len(records))

    def rollback(self):
        self.host.check_session(self.account)
        self.prepare()
        self.check_pending()
        self.quiet()
        history = self.history()
        require(history, 'No activation to roll back')
        saved = history[-1]
        require(self.read_link() == saved['after']['path'], 'Active symlink changed outside setup; refusing rollback')
        current = self.verify(Path(saved['after']['path']), expected_manifest=saved['after']['manifest_sha256'])
        previous = saved['before']
        if previous:
            self.verify(Path(previous['path']), previous['legacy'], previous['manifest_sha256'])
        records = self.installed()
        backup = self.host.user_files(self.account, 'snapshot', self.launcher_paths(records))
        pending = dict(saved, rollback=True, rollback_launchers=backup, history_before=history)
        atomic_json(self.state / 'pending.json', pending)
        try:
            self.switch(saved['before_link'] if previous else None)
            if previous and not previous['legacy']:
                self.refresh(Path(previous['path']), Path(current['path']), records)
            elif previous:
                # A pre-helper immutable root has no trusted setup boot class.
                # Restore its exact prior launchers instead of bypassing ART's
                # hidden-API policy or editing that old release in place.
                self.host.user_files(self.account, 'restore', saved['launchers_before'])
                extra = {p: None for p in self.launcher_paths(records) if p not in saved['launchers_before']}
                self.host.user_files(self.account, 'restore', extra)
            else:
                self.host.user_files(self.account, 'restore', saved['launchers_before'])
                # Newly installed apps are preserved but cannot have a working
                # launcher without an active runtime. Remove only their entries.
                extra = {p: None for p in self.launcher_paths(records) if p not in saved['launchers_before']}
                self.host.user_files(self.account, 'restore', extra)
                if not saved['wrapper_existed']:
                    self.host.path('/home/art/bin/saildroid-open').unlink()
            self.quiet()
            atomic_json(self.state / 'history.json', history[:-1])
            (self.state / 'pending.json').unlink()
            fsync_directory(self.state)
        except BaseException:
            self.switch(saved['after']['path'])
            self.wrapper()
            self.host.user_files(self.account, 'restore', backup)
            atomic_json(self.state / 'history.json', history)
            (self.state / 'pending.json').unlink()
            fsync_directory(self.state)
            raise
        return dict(status='rolled-back', release=previous, app_data_preserved=True, launcher_refresh='restored-legacy-snapshot-open-manager-for-new-apps' if previous and previous['legacy'] else 'registry' if previous else 'unconfigured')

    def recover(self):
        self.host.check_session(self.account)
        self.prepare()
        self.quiet()
        path = self.state / 'pending.json'
        require(path.exists(), 'No interrupted transaction')
        trusted(path, self.host.prefix)
        saved = document(path)
        require(self.read_link() in (saved['before_link'], saved['after']['path']),
                'Active symlink changed outside the interrupted transaction')
        # Recovery always restores the pre-operation pointer and desktop files.
        if saved.get('rollback'):
            target = saved['after']
            self.verify(Path(target['path']), expected_manifest=target['manifest_sha256'])
            self.switch(target['path'])
            self.wrapper()
            self.host.user_files(self.account, 'restore', saved['rollback_launchers'])
        else:
            old = saved['before']
            if old:
                self.verify(Path(old['path']), old['legacy'], old['manifest_sha256'])
            self.switch(saved['before_link'])
            self.host.user_files(self.account, 'restore', saved['launchers_before'])
            if not saved['wrapper_existed']:
                wrapper = self.host.path('/home/art/bin/saildroid-open')
                if wrapper.is_symlink():
                    wrapper.unlink()
        atomic_json(self.state / 'history.json', saved['history_before'])
        path.unlink()
        fsync_directory(self.state)
        return dict(status='recovered', active_link=self.read_link())

    def status(self):
        link = self.read_link()
        active = None
        if link is not None:
            resolved = (self.link.parent / link).resolve() if not Path(link).is_absolute() else self.host.path(link)
            if self.host.fixture and str(link).startswith(str(self.host.prefix)):
                resolved = Path(link)
            available = (resolved.parent in (self.host.path(RELEASES), self.host.path(LEGACY_RELEASES))
                         and resolved.is_dir() and (resolved / 'runtime.json').is_file())
            active = dict(path=str(resolved), available=available,
                          api=document(resolved / 'runtime.json').get('api') if available else None)
        history = self.history()
        previous = history[-1]['before'] if history and active and active['path'] == history[-1]['after']['path'] else None
        previous_available = bool(previous and Path(previous['path']).is_dir()
                                  and (Path(previous['path']) / ('install-manifest.json' if previous['legacy'] else MANIFEST)).is_file())
        status = 'ready' if active and active['available'] else 'missing-runtime' if active else 'unconfigured'
        return dict(status=status, active_link=link, active=active, previous=previous, previous_available=previous_available,
                    interrupted=(self.state / 'pending.json').exists(), busy=self.host.busy(),
                    user=self.account['name'], uid=self.account['uid'])

    def close(self):
        for fd, _ in reversed(self.handles):
            os.close(fd)
        self.handles.clear()


def main():
    if sys.argv[1:] == ['_user-files']:
        require(os.geteuid() != 0 and os.getuid() == os.geteuid(), 'User file step must be unprivileged')
        data = json.load(sys.stdin)
        print(json.dumps(user_files(data['home'], data['operation'], data['values'])))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    activate = sub.add_parser('activate')
    activate.add_argument('release')
    sub.add_parser('rollback')
    sub.add_parser('recover')
    args = parser.parse_args()
    os.environ['PATH'] = '/usr/sbin:/usr/bin:/sbin:/bin'
    host = Platform()
    host.check_system()
    setup = Setup(host)
    try:
        if args.command == 'activate':
            require(ID.fullmatch(args.release), 'Unsafe release id')
            result = setup.change(args.release)
        else:
            result = getattr(setup, args.command)()
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        setup.close()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        print('SAILDROID_SETUP=failed|' + str(error), file=sys.stderr)
        sys.exit(1)
