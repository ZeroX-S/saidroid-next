"""Regression fixtures for linkage metadata and reachable service dispatch."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api_inventory import ClassInfo, Inventory, mutf8, read_class, read_dex, read_path
from jni_coverage import audit
from service_coverage import coverage
from elf_inventory import scan_applications
from sdk_coverage import audit as sdk_audit


def class_fixture():
    constants = [
        (1, 'Fixture'), (7, 1), (1, 'java/lang/Object'), (7, 3),
        (1, 'run'), (1, '(I)J'), (1, 'value'), (1, 'I'),
        (1, 'toString'), (1, '()Ljava/lang/String;'), (12, 9, 10), (10, 4, 11),
    ]
    data = bytearray(b'\xca\xfe\xba\xbe' + struct.pack('>HHH', 0, 52, len(constants) + 1))
    for tag, *values in constants:
        data.append(tag)
        if tag == 1:
            text = values[0].encode()
            data.extend(struct.pack('>H', len(text)) + text)
        else:
            data.extend(struct.pack('>' + 'H' * len(values), *values))
    data.extend(struct.pack('>HHHH', 0x21, 2, 4, 0))
    data.extend(struct.pack('>HHHHH', 1, 1, 7, 8, 0))
    data.extend(struct.pack('>HHHHH', 1, 0x109, 5, 6, 0))
    data.extend(struct.pack('>H', 0))
    return bytes(data)


def dex_fixture(version=b'039'):
    strings = ['LFixture;', 'Ljava/lang/Object;', 'run', 'I']
    data = bytearray(192)
    data[:8] = b'dex\n' + version + b'\0'
    string_offsets = []
    for value in strings:
        string_offsets.append(len(data))
        data.extend(bytes([len(value)]) + value.encode() + b'\0')
    class_data_offset = len(data)
    data.extend(b'\0\0\1\0\0\x89\2\0')
    struct.pack_into('<III', data, 32, len(data), 112, 0x12345678)
    struct.pack_into('<12I', data, 56, 4, 112, 3, 128, 1, 140, 0, 0, 1, 152, 1, 160)
    struct.pack_into('<4I', data, 112, *string_offsets)
    struct.pack_into('<3I', data, 128, 0, 1, 3)
    struct.pack_into('<3I', data, 140, 3, 2, 0)
    struct.pack_into('<HHI', data, 152, 0, 0, 2)
    struct.pack_into('<8I', data, 160, 0, 0x21, 1, 0, 0xffffffff, 0, class_data_offset, 0)
    return bytes(data)


class MetadataTests(unittest.TestCase):
    def test_class_descriptors_access_and_references(self):
        inventory = read_class(class_fixture(), 'fixture.class')
        definition = inventory.classes['Fixture']
        self.assertEqual(definition.superclass, 'java/lang/Object')
        self.assertEqual(definition.methods['run', '(I)J'], 0x109)
        self.assertEqual(definition.fields['value', 'I'], 1)
        self.assertIn(('method', 'java/lang/Object', 'toString', '()Ljava/lang/String;'),
                      inventory.references)

    def test_truncated_class_is_rejected(self):
        with self.assertRaises(ValueError):
            read_class(class_fixture()[:30], 'truncated.class')

    def test_modified_utf8(self):
        self.assertEqual(mutf8(b'a\xc0\x80b'), 'a\0b')
        self.assertEqual(mutf8(b'\xed\xa0\xbd\xed\xb8\x80'), '\U0001f600')
        self.assertEqual(mutf8(b'\xed\xa0\x80'), '\ud800')

    def test_supported_dex_metadata(self):
        for version in (b'035', b'037', b'038', b'039', b'040'):
            with self.subTest(version=version):
                inventory = read_dex(dex_fixture(version), 'fixture.dex')
                self.assertEqual(inventory.classes['Fixture'].methods['run', '()I'], 0x109)
                self.assertIn(('method', 'Fixture', 'run', '()I'), inventory.references)

    def test_dex_table_bounds(self):
        data = bytearray(dex_fixture())
        struct.pack_into('<I', data, 60, len(data))
        with self.assertRaises(ValueError):
            read_dex(data, 'invalid-table.dex')

    def test_dex_class_data_bounds(self):
        data = bytearray(dex_fixture())
        struct.pack_into('<I', data, 184, len(data))
        with self.assertRaises(ValueError):
            read_dex(data, 'invalid-class-data.dex')

    def test_dex_size_and_version(self):
        for data in (dex_fixture()[:-1], dex_fixture(b'041')):
            with self.subTest(size=len(data)):
                with self.assertRaises(ValueError):
                    read_dex(data, 'invalid.dex')

    def test_apk_multidex(self):
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary) / 'fixture.apk'
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr('classes.dex', dex_fixture())
                archive.writestr('classes2.dex', dex_fixture())
            inventory = read_path(apk)
            self.assertEqual(len(inventory.classes), 1)
            self.assertEqual(len(inventory.duplicates), 1)

    def test_inheritance_and_constructor_ownership(self):
        parent = ClassInfo('Parent', '', (), 1, methods={('run', '(I)J'): 1, ('<init>', '()V'): 1})
        child = ClassInfo('Child', 'Parent', (), 1)
        inventory = Inventory(classes={'Parent': parent, 'Child': child})
        self.assertEqual(inventory.resolve('method', 'Child', 'run', '(I)J')[0], parent)
        self.assertIsNone(inventory.resolve('method', 'Child', '<init>', '()V'))

    def test_shadowed_provider_preserves_first_definition(self):
        first = read_class(class_fixture(), 'boot.jar')
        second = read_class(class_fixture(), 'app.apk')
        first.add(second)
        self.assertEqual(first.classes['Fixture'].origin, 'boot.jar')
        self.assertEqual(first.duplicates[0]['shadowed'], 'app.apk')

    def test_array_clone_and_polymorphic_method(self):
        handle = ClassInfo('java/lang/invoke/MethodHandle', '', (), 1,
                           methods={('invokeExact', '([Ljava/lang/Object;)Ljava/lang/Object;'): 0x181})
        inventory = Inventory(classes={handle.name: handle})
        self.assertIsNotNone(inventory.resolve('method', '[I', 'clone', '()[I'))
        self.assertIsNotNone(inventory.resolve('method', handle.name, 'invokeExact', '(I)J'))

    def test_sdk_missing_and_inaccessible_members_fail(self):
        inventory = Inventory(classes={'Fixture': ClassInfo('Fixture', '', (), 1,
            fields={('privateValue', 'I'): 2}, methods={('run', '()V'): 1})})
        result = sdk_audit(inventory, {'LFixture;->run()V', 'LFixture;->privateValue:I',
                                       'LMissing;-><init>()V'})
        self.assertFalse(result['passed'])
        self.assertEqual(result['missing_classes'], ['Missing'])
        self.assertEqual(result['missing_members'], ['LMissing;-><init>()V'])
        self.assertEqual(result['inaccessible_members'], ['LFixture;->privateValue:I'])

    def test_sdk_inherited_public_member_is_resolved(self):
        inventory = Inventory(classes={
            'Parent': ClassInfo('Parent', '', (), 1, methods={('run', '()V'): 1}),
            'Child': ClassInfo('Child', 'Parent', (), 1),
        })
        result = sdk_audit(inventory, {'LChild;->run()V'})
        self.assertTrue(result['passed'])
        self.assertEqual(result['resolved_via_inheritance'], 1)


class SourceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.inventory = Inventory(classes={
            'Fixture': ClassInfo('Fixture', '', (), 1,
                                 fields={('value', 'I'): 1}, methods={('run', '(I)J'): 0x109}),
            'Other': ClassInfo('Other', '', (), 1, methods={('run', '()V'): 1}),
        })

    def scan(self, source):
        path = self.directory / 'fixture.c'
        path.write_text(source, encoding='utf-8')
        return audit([path], self.inventory, 28)

    def test_exact_native_descriptor(self):
        result = self.scan('''void install(JNIEnv *env) {
            JNINativeMethod methods[] = {{"run", "(I)J", run}};
            env->RegisterNatives(env->FindClass("Fixture"), methods, 1);
        }''')
        self.assertFalse(result['problems'])
        self.assertTrue(any(row.get('descriptor') == '(I)J' for row in result['checked']))

    def test_wrong_native_descriptor_fails(self):
        result = self.scan('''void install(JNIEnv *env) {
            JNINativeMethod methods[] = {{"run", "(I)I", run}};
            env->RegisterNatives(env->FindClass("Fixture"), methods, 1);
        }''')
        self.assertEqual(result['problems'][0]['reason'], 'missing-native-declaration')

    def test_static_instance_mismatch_fails(self):
        result = self.scan('''void install(JNIEnv *env) {
            jclass c = env->FindClass("Fixture");
            env->GetMethodID(c, "run", "(I)J");
        }''')
        self.assertEqual(result['problems'][0]['reason'], 'static-instance-mismatch')

    def test_function_scoped_class_binding(self):
        result = self.scan('''void first(JNIEnv *env) {
            jclass c = env->FindClass("Fixture");
            env->GetStaticMethodID(c, "run", "(I)J");
        }
        void second(JNIEnv *env) {
            jclass c = env->FindClass("Other");
            env->GetMethodID(c, "run", "()V");
        }''')
        self.assertFalse(result['problems'])
        self.assertFalse(result['unresolved'])

    def test_comments_and_quoted_braces(self):
        result = self.scan('''void install(JNIEnv *env) {
            // env->FindClass("Absent");
            const char *message = "a } brace";
            jclass c = env->FindClass("Fixture");
            env->GetFieldID(c, "value", "I");
        }''')
        self.assertFalse(result['problems'])
        self.assertEqual(len(result['checked']), 2)

    def test_conditional_and_dynamic_gaps_are_explicit(self):
        result = self.scan('''void install(JNIEnv *env, int framework_api) {
            if (framework_api == 29) env->FindClass("Absent");
            env->FindClass(dynamic_name);
        }''')
        self.assertFalse(result['problems'])
        self.assertEqual(len(result['unresolved']), 2)

    def test_extern_c_preserves_sdk_condition_scope(self):
        result = self.scan('''extern "C" JNIEXPORT void JNICALL Java_Fixture_install(JNIEnv *env, jclass cls) {
            int SDK_INT = 28;
            if (SDK_INT >= 29) env->FindClass("Api29OnlyClass");
        }''')
        self.assertFalse(result['problems'])
        self.assertEqual(result['unresolved'][0]['function'], 'Java_Fixture_install')
        self.assertEqual(result['unresolved'][0]['owner'], 'Api29OnlyClass')

    def test_inherited_jni_member(self):
        self.inventory.classes['Child'] = ClassInfo('Child', 'Fixture', (), 1)
        result = self.scan('''void install(JNIEnv *env) {
            jclass c = env->FindClass("Child");
            env->GetStaticMethodID(c, "run", "(I)J");
        }''')
        self.assertFalse(result['problems'])
        self.assertEqual(len(result['checked']), 2)

    def test_omitted_core_provider_stays_unresolved(self):
        path = self.directory / 'fixture.c'
        path.write_text('void install(JNIEnv *env) { env->FindClass("java/lang/Object"); }')
        complete = audit([path], self.inventory, 28)
        incomplete = audit([path], self.inventory, 28, incomplete_prefixes=('java/',))
        self.assertEqual(complete['problems'][0]['reason'], 'missing-class')
        self.assertFalse(incomplete['problems'])
        self.assertEqual(incomplete['unresolved'][0]['reason'], 'provider-not-supplied')

    def test_disconnected_service_route_fails(self):
        self.inventory.classes['pkg/IFixture'] = ClassInfo('pkg/IFixture', '', (), 0x201,
            methods={('getTask', '(I)I'): 0x401, ('moveToBack', '(Z)Z'): 0x401})
        (self.directory / 'Dispatcher.java').write_text('''class Dispatcher implements InvocationHandler {
            Object service = Proxy.newProxyInstance(loader, new Class[]{pkg.IFixture.class}, this);
            Object invoke(Object p, Method method, Object[] args) {
                String n = method.getName();
                if (Tasks.handles(n)) return Tasks.dispatch(p, method, args);
                return null;
            }
        }''')
        (self.directory / 'Tasks.java').write_text('''class Tasks {
            Set<String> operations = Arrays.asList("getTask");
            boolean handles(String name) { return operations.contains(name); }
            Object invoke(Object p, Method method, Object[] args) {
                String n = method.getName();
                switch (n) { case "moveToBack": return true; }
                return null;
            }
        }''')
        result = coverage(self.directory, self.inventory)
        self.assertEqual({row['reason'] for row in result['route_problems']},
                         {'advertised-without-dispatch-branch', 'dispatch-branch-not-advertised'})
        self.assertEqual(result['totals']['unhandled'], 2)

        helper = self.directory / 'Tasks.java'
        helper.write_text(helper.read_text().replace('Arrays.asList("getTask")', 'Arrays.asList("moveToBack")'))
        connected = coverage(self.directory, self.inventory)
        self.assertFalse(connected['route_problems'])
        self.assertEqual(connected['totals']['dispatch_names'], 1)


class ArtifactTests(unittest.TestCase):
    def test_source_snapshot_ignores_timestamps_and_tracks_content(self):
        spec = importlib.util.spec_from_file_location('compat_remote',
            Path(__file__).resolve().parents[1] / 'run-remote.py')
        remote = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(remote)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            source = root / 'scripts/input.py'
            source.write_text('print(1)\n')
            first, second, changed = [root / name for name in ('first.tar.gz', 'second.tar.gz', 'changed.tar.gz')]
            remote.source_archive(root, first)
            os.utime(source, (1, 2))
            remote.source_archive(root, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            source.write_text('print(2)\n')
            remote.source_archive(root, changed)
            self.assertNotEqual(hashlib.sha256(first.read_bytes()).digest(),
                                hashlib.sha256(changed.read_bytes()).digest())

    def test_elf_candidates_keep_application_providers_separate(self):
        def metadata(path):
            code = Path(path).read_bytes()[-1:]
            return dict(soname=Path(path).name, machine='AArch64', needed=[], weak_imports=set(),
                        exports={'app_private'} if code == b'A' else set(),
                        imports={'app_private', 'missing_symbol'} if code == b'B' else set())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'lib').mkdir()
            (root / 'lib/provider.so').write_bytes(b'\x7fELFP')
            (root / 'runtime.json').write_text(json.dumps({'rpm_activation': {'release_id': 'fixture'}}))
            apks = []
            for name in ('A', 'B'):
                apk = root / (name + '.apk')
                with zipfile.ZipFile(apk, 'w') as archive:
                    archive.writestr('lib/arm64-v8a/app.so', b'\x7fELF' + name.encode())
                apks.append(apk)
            with patch('elf_inventory.inspect', side_effect=metadata):
                result = scan_applications(apks, root)
            self.assertEqual(len(result['providers']), 1)
            self.assertEqual(result['applications'][1]['libraries'][0]['potential_missing_symbols'],
                             ['app_private', 'missing_symbol'])


if __name__ == '__main__':
    unittest.main()
