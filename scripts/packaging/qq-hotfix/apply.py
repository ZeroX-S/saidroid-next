#!/usr/bin/python3
"""Apply a hash-pinned SailDroid runtime bundle without touching app data."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import tempfile
import time


BUNDLE = Path('/opt/saildroid/hotfixes/qq-20261111')
MANIFEST_NAME = 'share/build/boot-image-manifest.json'
CONFIG_NAME = 'runtime.json'


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def atomic_copy(source, target, mode=0o644):
    descriptor, temporary = tempfile.mkstemp(prefix='.qq-hotfix-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream, Path(source).open('rb') as original:
            shutil.copyfileobj(original, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(target, value, mode=0o600):
    descriptor, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        atomic_copy(temporary, target, mode)
    finally:
        os.unlink(temporary)


class Hotfix:
    def __init__(self, bundle=BUNDLE, root=None, state=None, username='defaultuser'):
        self.bundle = Path(bundle)
        self.manifest = load(self.bundle / 'bundle.json')
        self.root = Path(root or self.manifest['component'])
        self.state = Path(state or '/var/lib/saildroid/qq-hotfix-20261111')
        self.account = pwd.getpwnam(username)
        self.session = Path('/run/user') / str(self.account.pw_uid) / 'saildroid'
        self.names = sorted(self.manifest['files']) + [CONFIG_NAME]
        self.backup = self.state / 'backup'
        self.journal = self.state / 'state.json'
        self.validate_names()

    def validate_names(self):
        names = self.manifest['files']
        images = {name for name in names if name.startswith('system/framework/arm64/')}
        if len(images) != 42 or set(names) != images | {'lib/runtime.jar', MANIFEST_NAME}:
            raise RuntimeError('Bundle must include the complete 42-image closure')
        for name in images:
            path = Path(name)
            if str(path) != name or path.parent != Path('system/framework/arm64') or path.suffix not in {'.art', '.oat', '.vdex'}:
                raise RuntimeError('Unsafe boot-image pathname')
        for name in self.manifest['inputs']:
            if Path(name).is_absolute() or '..' in Path(name).parts or str(Path(name)) != name:
                raise RuntimeError('Unsafe compatibility input pathname')

    def verify_hashes(self, root, expected):
        for name, checksum in expected.items():
            if digest(root / name) != checksum:
                raise RuntimeError('Checksum mismatch: ' + name)

    def candidate(self):
        self.verify_hashes(self.bundle / 'payload', self.manifest['files'])
        images = load(self.bundle / 'payload' / MANIFEST_NAME)
        expected = {'system/framework/arm64/' + name: value['sha256']
                    for name, value in images['files'].items()}
        if expected != {name: checksum for name, checksum in self.manifest['files'].items()
                        if name.startswith('system/framework/arm64/')}:
            raise RuntimeError('Image manifest and bundle disagree')
        if images['inputs']['lib/runtime.jar'] != self.manifest['files']['lib/runtime.jar']:
            raise RuntimeError('Image manifest and runtime disagree')

    def environment(self):
        if platform.machine() != 'aarch64':
            raise RuntimeError('This bundle requires aarch64')
        if Path('/home/art/api29-root').resolve() != self.root:
            raise RuntimeError('Active component differs; refusing alias changes')
        if (self.root / 'framework/arm64').resolve() != self.root / 'system/framework/arm64':
            raise RuntimeError('Boot-image alias differs')
        for name in self.names:
            path = self.root / name
            if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
                raise RuntimeError('Unsafe installation target: ' + name)
        self.configuration()

    def configuration(self):
        self.verify_hashes(self.root, self.manifest['inputs'])
        config = load(self.root / CONFIG_NAME)
        for name, value in self.manifest['config_requirements'].items():
            if config.get(name) != value:
                raise RuntimeError('Boot configuration differs: ' + name)
        if config['boot_image']['path'] != self.manifest['boot_path']:
            raise RuntimeError('Logical boot-image path differs')

    def check(self):
        self.candidate()
        self.environment()
        if digest(self.root / 'lib/runtime.jar') == self.manifest['files']['lib/runtime.jar']:
            self.verify()
            return 'already-applied'
        self.verify_hashes(self.root, self.manifest['baseline'])
        images = load(self.root / MANIFEST_NAME)
        self.verify_hashes(self.root, {'system/framework/arm64/' + name: value['sha256']
                                    for name, value in images['files'].items()})
        if set(images['files']) != set(load(self.bundle / 'payload' / MANIFEST_NAME)['files']):
            raise RuntimeError('Baseline image closure differs')
        if load(self.root / CONFIG_NAME)['boot_image']['manifest_sha256'] != digest(self.root / MANIFEST_NAME):
            raise RuntimeError('Baseline boot manifest reference differs')
        return 'ready'

    def verify(self):
        self.candidate()
        self.environment()
        self.verify_hashes(self.root, self.manifest['files'])
        config = load(self.root / CONFIG_NAME)
        if config['boot_image']['manifest_sha256'] != self.manifest['files'][MANIFEST_NAME] or config['boot_image']['files'] != 42:
            raise RuntimeError('Installed boot configuration differs')
        for name, value in self.manifest['config_additions'].items():
            if config.get(name) != value:
                raise RuntimeError('Installed hotfix metadata differs: ' + name)

    def live_records(self):
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        for path in self.session.glob('*.json'):
            try:
                record = load(path)
                fields = (Path('/proc') / str(record['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
                if record.get('boot') == boot and fields[0] != 'Z' and int(fields[19]) == record['start_ticks']:
                    yield record
            except (OSError, ValueError, KeyError):
                continue

    def image_users(self):
        users = set()
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                mappings = (process / 'maps').read_text()
            except (FileNotFoundError, ProcessLookupError):
                continue
            if any(str(self.root / name) in mappings for name in ('system/framework/arm64/boot', 'framework/arm64/boot')):
                users.add(int(process.name))
        return users

    def close_runtime(self):
        routes = [('com.tencent.mobileqq', ['--package', 'com.tencent.mobileqq']),
                  ('org.saildroid.manager', ['--manager']),
                  ('org.saildroid.binder', ['--broker'])]
        allowed = {package for package, arguments in routes}
        owned = {record['pid'] for record in self.live_records()
                 if record.get('package') in allowed and record.get('component') == str(self.root)}
        if self.image_users() - owned:
            raise RuntimeError('Other applications use these images; close them first')
        environment = dict(os.environ, HOME=self.account.pw_dir, USER=self.account.pw_name,
                           LOGNAME=self.account.pw_name, XDG_RUNTIME_DIR=str(self.session.parent),
                           DBUS_SESSION_BUS_ADDRESS='unix:path=' + str(self.session.parent / 'dbus/user_bus_socket'))
        for package, arguments in routes:
            if not any(record.get('package') == package and record.get('component') == str(self.root)
                       for record in self.live_records()):
                continue
            result = subprocess.run([str(self.root / 'libexec/saildroid-app'), *arguments, '--close'],
                                    env=environment, user=self.account.pw_uid, group=self.account.pw_gid,
                                    extra_groups=os.getgrouplist(self.account.pw_name, self.account.pw_gid),
                                    capture_output=True, timeout=20)
            if result.returncode:
                raise RuntimeError('Native close failed: ' + package)
            deadline = time.monotonic() + 30
            while any(record.get('package') == package and record.get('component') == str(self.root)
                      for record in self.live_records()):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Process family did not close: ' + package)
                time.sleep(0.1)
        if self.image_users():
            raise RuntimeError('Images still mapped; installation refused')

    @contextmanager
    def stopped(self):
        self.close_runtime()
        with (self.session / 'host-manager.lock').open('r+') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.image_users():
                raise RuntimeError('Images remapped; installation refused')
            yield

    def backup_index(self):
        index = load(self.backup / 'index.json')
        if set(index) != set(self.names):
            raise RuntimeError('Incomplete rollback snapshot')
        self.verify_hashes(self.backup, index)
        return index

    def restore(self, expected_current=None):
        index = self.backup_index()
        if expected_current is not None:
            self.verify_hashes(self.root, expected_current)
        for name in self.names:
            atomic_copy(self.backup / name, self.root / name)
        self.verify_hashes(self.root, index)
        atomic_json(self.journal, dict(status='rolled-back', original=index))

    def apply(self):
        status = self.check()
        if status == 'already-applied':
            return status
        if self.journal.exists():
            raise RuntimeError('A rollback snapshot already exists; inspect state before applying again')
        before = {name: digest(self.root / name) for name in self.names}
        required = sum((self.root / name).stat().st_size for name in self.names) * 2 + 32 * 1024 * 1024
        if shutil.disk_usage(self.state).free < required:
            raise RuntimeError('Insufficient space for snapshot and installation')
        if self.backup.exists():
            raise RuntimeError('Incomplete snapshot exists; refusing overwrite')
        self.backup.mkdir(mode=0o700)
        for name in self.names:
            target = self.backup / name
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_copy(self.root / name, target)
        atomic_json(self.backup / 'index.json', before)
        self.backup_index()
        config = load(self.root / CONFIG_NAME)
        config['boot_image']['files'] = 42
        config['boot_image']['manifest_sha256'] = self.manifest['files'][MANIFEST_NAME]
        config.update(self.manifest['config_additions'])
        atomic_json(self.state / 'candidate-runtime.json', config)
        desired = dict(self.manifest['files'], **{CONFIG_NAME: digest(self.state / 'candidate-runtime.json')})
        atomic_json(self.journal, dict(status='prepared', original=before, installed=desired))
        with self.stopped():
            self.verify_hashes(self.root, before)
            self.candidate()
            self.environment()
            atomic_json(self.journal, dict(status='applying', original=before, installed=desired))
            try:
                for name in self.names:
                    source = self.state / 'candidate-runtime.json' if name == CONFIG_NAME else self.bundle / 'payload' / name
                    atomic_copy(source, self.root / name)
                self.verify_hashes(self.root, desired)
                self.verify()
                atomic_json(self.journal, dict(status='applied', original=before, installed=desired))
            except BaseException:
                self.restore()
                raise
        return 'applied'

    def rollback(self):
        self.environment()
        record = load(self.journal)
        index = self.backup_index()
        if record['status'] == 'rolled-back':
            self.verify_hashes(self.root, index)
            return 'already-rolled-back'
        if record['status'] == 'prepared':
            self.verify_hashes(self.root, index)
        elif record['status'] == 'applied':
            self.verify_hashes(self.root, record['installed'])
        elif record['status'] == 'applying':
            for name in self.names:
                if digest(self.root / name) not in {record['installed'][name], index[name]}:
                    raise RuntimeError('Files changed since interrupted installation: ' + name)
        else:
            raise RuntimeError('Unknown rollback state')
        current = {name: digest(self.root / name) for name in self.names}
        with self.stopped():
            self.restore(current)
        return 'rolled-back'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check', 'apply', 'verify', 'rollback'])
    parser.add_argument('--user', default='defaultuser')
    arguments = parser.parse_args()
    hotfix = Hotfix(username=arguments.user)
    if arguments.operation in {'apply', 'rollback'}:
        if os.geteuid() != 0:
            parser.error('Apply and rollback require root')
        hotfix.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (hotfix.state / 'operation.lock').open('a+') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = getattr(hotfix, arguments.operation)()
    else:
        result = getattr(hotfix, arguments.operation)() or 'pass'
    print('SAILDROID_QQ_HOTFIX=' + result)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit('SAILDROID_QQ_HOTFIX=failed|' + str(error))
