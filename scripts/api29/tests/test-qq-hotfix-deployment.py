#!/usr/bin/env python3

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
specification = importlib.util.spec_from_file_location('qq_hotfix', ROOT / 'scripts/packaging/qq-hotfix/apply.py')
helper = importlib.util.module_from_spec(specification)
specification.loader.exec_module(helper)


class FixtureHotfix(helper.Hotfix):
    def environment(self):
        self.configuration()

    @contextmanager
    def stopped(self):
        yield


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='qq-hotfix-test-')
        directory = Path(self.temporary.name)
        self.root = directory / 'component'
        self.bundle = directory / 'bundle'
        self.state = directory / 'state'
        self.state.mkdir()
        self.files = {}
        self.old_images = {}
        self.new_images = {}
        for number in range(14):
            for suffix in ('art', 'oat', 'vdex'):
                name = 'boot-' + str(number) + '.' + suffix
                relative = 'system/framework/arm64/' + name
                self.write(self.root / relative, 'old-' + name)
                self.write(self.bundle / 'payload' / relative, 'new-' + name)
                self.files[relative] = helper.digest(self.bundle / 'payload' / relative)
                self.old_images[name] = {'sha256': helper.digest(self.root / relative)}
                self.new_images[name] = {'sha256': self.files[relative]}
        self.write(self.root / 'lib/runtime.jar', 'old-runtime')
        self.write(self.bundle / 'payload/lib/runtime.jar', 'new-runtime')
        self.files['lib/runtime.jar'] = helper.digest(self.bundle / 'payload/lib/runtime.jar')
        self.write(self.root / helper.MANIFEST_NAME, json.dumps({'files': self.old_images, 'inputs': {'lib/runtime.jar': helper.digest(self.root / 'lib/runtime.jar')}}))
        self.write(self.bundle / 'payload' / helper.MANIFEST_NAME, json.dumps({'files': self.new_images, 'inputs': {'lib/runtime.jar': self.files['lib/runtime.jar']}}))
        self.files[helper.MANIFEST_NAME] = helper.digest(self.bundle / 'payload' / helper.MANIFEST_NAME)
        self.write(self.root / 'lib/native.so', 'native-unchanged')
        self.original_config = {'api': 28, 'boot_jars': ['platform.jar'],
                                'boot_image': {'path': 'framework/boot.art', 'files': 42,
                                               'manifest_sha256': helper.digest(self.root / helper.MANIFEST_NAME), 'device_option': 3},
                                'device_settings': {'keep': True}}
        self.write(self.root / 'runtime.json', json.dumps(self.original_config))
        self.manifest = {'component': str(self.root), 'files': self.files,
                         'baseline': {name: helper.digest(self.root / name) for name in ('lib/runtime.jar', helper.MANIFEST_NAME)},
                         'inputs': {'lib/native.so': helper.digest(self.root / 'lib/native.so')},
                         'config_requirements': {'api': 28, 'boot_jars': ['platform.jar']},
                         'boot_path': 'framework/boot.art', 'config_additions': {'qq_login_hotfix': {'runtime_sha256': self.files['lib/runtime.jar']}}}
        self.write(self.bundle / 'bundle.json', json.dumps(self.manifest))
        self.hotfix = FixtureHotfix(self.bundle, root=self.root, state=self.state,
                                   username=helper.pwd.getpwuid(helper.os.getuid()).pw_name)
        self.original = {name: helper.digest(self.root / name) for name in self.hotfix.names}

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, path, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def test_ready_then_complete_apply(self):
        self.assertEqual(self.hotfix.check(), 'ready')
        self.assertEqual(self.hotfix.apply(), 'applied')
        self.hotfix.verify()
        self.hotfix.verify_hashes(self.root, self.files)
        self.assertEqual(len(self.hotfix.backup_index()), 45)

    def test_preserves_device_settings(self):
        self.hotfix.apply()
        config = helper.load(self.root / 'runtime.json')
        self.assertEqual(config['device_settings'], self.original_config['device_settings'])
        self.assertEqual(config['boot_image']['device_option'], 3)
        self.assertEqual(helper.digest(self.root / 'lib/native.so'), self.manifest['inputs']['lib/native.so'])

    def test_repeat_apply_is_noop(self):
        self.hotfix.apply()
        journal = (self.state / 'state.json').read_bytes()
        self.assertEqual(self.hotfix.apply(), 'already-applied')
        self.assertEqual((self.state / 'state.json').read_bytes(), journal)

    def test_full_rollback_and_repeat(self):
        self.hotfix.apply()
        self.assertEqual(self.hotfix.rollback(), 'rolled-back')
        self.hotfix.verify_hashes(self.root, self.original)
        self.assertEqual(self.hotfix.rollback(), 'already-rolled-back')

    def test_refuses_unknown_runtime(self):
        self.write(self.root / 'lib/runtime.jar', 'other-patch')
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.hotfix.apply()
        self.assertFalse(self.hotfix.backup.exists())

    def test_refuses_incompatible_native(self):
        self.write(self.root / 'lib/native.so', 'other-native')
        with self.assertRaisesRegex(RuntimeError, 'lib/native.so'):
            self.hotfix.check()

    def test_refuses_changed_boot_configuration(self):
        config = dict(self.original_config, boot_jars=['other.jar'])
        self.write(self.root / 'runtime.json', json.dumps(config))
        with self.assertRaisesRegex(RuntimeError, 'Boot configuration differs'):
            self.hotfix.check()

    def test_refuses_corrupt_image_payload(self):
        name = next(iter(self.files))
        self.write(self.bundle / 'payload' / name, 'corrupt')
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.hotfix.apply()
        self.assertFalse(self.hotfix.backup.exists())

    def test_refuses_corrupt_baseline_image(self):
        self.write(self.root / next(iter(self.files)), 'corrupt')
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.hotfix.check()

    def test_requires_complete_closure(self):
        del self.manifest['files'][next(iter(self.files))]
        self.write(self.bundle / 'bundle.json', json.dumps(self.manifest))
        with self.assertRaisesRegex(RuntimeError, 'complete 42-image closure'):
            FixtureHotfix(self.bundle)

    def test_refuses_unsafe_image_path(self):
        first = next(iter(self.files))
        self.manifest['files']['system/framework/arm64/../../unsafe.art'] = self.manifest['files'].pop(first)
        self.write(self.bundle / 'bundle.json', json.dumps(self.manifest))
        with self.assertRaisesRegex(RuntimeError, 'Unsafe boot-image'):
            FixtureHotfix(self.bundle)

    def test_refuses_corrupt_backup_before_touching_runtime(self):
        self.hotfix.apply()
        self.write(self.hotfix.backup / 'lib/runtime.jar', 'corrupt')
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.hotfix.rollback()
        self.hotfix.verify()

    def test_does_not_erase_later_patch(self):
        self.hotfix.apply()
        self.write(self.root / 'lib/runtime.jar', 'later-hotfix')
        with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
            self.hotfix.rollback()
        self.assertEqual((self.root / 'lib/runtime.jar').read_text(), 'later-hotfix')

    def test_install_failure_restores_all_files(self):
        copy = helper.atomic_copy
        failed = False

        def fail_once(source, target, mode=0o644):
            nonlocal failed
            if not failed and str(source).startswith(str(self.bundle / 'payload')):
                failed = True
                raise OSError('injected installation failure')
            return copy(source, target, mode)

        with mock.patch.object(helper, 'atomic_copy', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.hotfix.apply()
        self.hotfix.verify_hashes(self.root, self.original)
        self.assertEqual(helper.load(self.hotfix.journal)['status'], 'rolled-back')

    def test_close_failure_leaves_recoverable_snapshot(self):
        @contextmanager
        def refuse():
            raise RuntimeError('other application is running')
            yield

        with mock.patch.object(self.hotfix, 'stopped', refuse):
            with self.assertRaisesRegex(RuntimeError, 'other application'):
                self.hotfix.apply()
        self.assertEqual(helper.load(self.hotfix.journal)['status'], 'prepared')
        self.assertEqual(self.hotfix.rollback(), 'rolled-back')
        self.hotfix.verify_hashes(self.root, self.original)

    def test_interrupted_install_can_rollback(self):
        self.hotfix.apply()
        record = helper.load(self.hotfix.journal)
        record['status'] = 'applying'
        helper.atomic_json(self.hotfix.journal, record)
        name = next(iter(self.files))
        helper.atomic_copy(self.hotfix.backup / name, self.root / name)
        self.assertEqual(self.hotfix.rollback(), 'rolled-back')
        self.hotfix.verify_hashes(self.root, self.original)

    def test_interrupted_install_refuses_foreign_changes(self):
        self.hotfix.apply()
        record = helper.load(self.hotfix.journal)
        record['status'] = 'applying'
        helper.atomic_json(self.hotfix.journal, record)
        self.write(self.root / 'lib/runtime.jar', 'foreign-change')
        with self.assertRaisesRegex(RuntimeError, 'Files changed since interrupted'):
            self.hotfix.rollback()

    def test_refuses_unrelated_image_users_without_closing_them(self):
        with mock.patch.object(self.hotfix, 'live_records', return_value=iter([])), \
                mock.patch.object(self.hotfix, 'image_users', return_value={999999}), \
                mock.patch.object(helper.subprocess, 'run') as command:
            with self.assertRaisesRegex(RuntimeError, 'Other applications use'):
                self.hotfix.close_runtime()
            command.assert_not_called()

    def test_stale_session_records_are_not_live(self):
        self.hotfix.session = self.state / 'sessions'
        self.hotfix.session.mkdir()
        process = Path('/proc') / str(helper.os.getpid())
        fields = (process / 'stat').read_text().rsplit(')', 1)[1].split()
        record = {'pid': helper.os.getpid(), 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'start_ticks': int(fields[19]) + 1}
        self.write(self.hotfix.session / 'stale.json', json.dumps(record))
        self.assertEqual(list(self.hotfix.live_records()), [])

    def test_stopped_refuses_images_remapped_after_close(self):
        self.hotfix.session = self.state / 'sessions'
        self.hotfix.session.mkdir()
        self.write(self.hotfix.session / 'host-manager.lock', '')
        with mock.patch.object(self.hotfix, 'close_runtime'), \
                mock.patch.object(self.hotfix, 'image_users', return_value={999999}):
            with self.assertRaisesRegex(RuntimeError, 'Images remapped'):
                with helper.Hotfix.stopped(self.hotfix):
                    self.fail('Installation must not start')

    def test_rollback_rechecks_files_after_closing(self):
        self.hotfix.apply()

        @contextmanager
        def changed_during_close():
            self.write(self.root / 'lib/runtime.jar', 'later-patch-during-close')
            yield

        with mock.patch.object(self.hotfix, 'stopped', changed_during_close):
            with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
                self.hotfix.rollback()
        self.assertEqual((self.root / 'lib/runtime.jar').read_text(), 'later-patch-during-close')


if __name__ == '__main__':
    unittest.main()
