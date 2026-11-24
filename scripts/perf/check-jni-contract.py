#!/usr/bin/env python3
"""Build-time JNI contract gate.

The bug this exists for: `sdwindow.c` asked for
`GetStaticFieldID(SdSurfaceStore, "lastLayerCount", "J")` while the Java field was
`private static int lastLayerCount;` (descriptor `I`). The call returned NULL, left a
pending `NoSuchFieldError`, and ART aborted the whole application at the next JNI
call -- looking like a GC crash. A grep for the *name* on both sides says "fine";
only the *signature* says otherwise.

So this gate compares both sides by exact JVM descriptor, before anything is built:

  * every `GetStaticFieldID(env, <class>, "<name>", "<sig>")`
  * every `GetStaticMethodID(env, <class>, "<name>", "<sig>")`
  * every class named in `FindClass` (own sources, or for `android/*` the framework jar)
  * every `JNINativeMethod` table entry registered with `RegisterNatives`: the Java
    side must declare `native ... name(sig)`, and the library must export the matching
    `Java_<Class>_<name>` symbol (checked with `nm -D` when `--so` is given)

Exit codes: 0 contract holds, 3 contract violated (build must be refused).

Run inside the build VM:

    python3 scripts/perf/check-jni-contract.py
    python3 scripts/perf/check-jni-contract.py --so /var/tmp/.../libsdwindow.so
"""
from pathlib import Path
import argparse, os, re, shutil, subprocess, sys, tempfile, zipfile

REPO = Path(__file__).resolve().parents[2]
NATIVE_DIR = REPO / 'native/window'
JAVA_DIR = REPO / 'scripts/device'
INPUTS = REPO / 'build/codex-api29/inputs'
FRAMEWORK_JAR = INPUTS / 'android-all-10-robolectric-5803371.jar'
JAVA_BIN = Path(os.environ.get('JAVA_HOME', '/tmp/jdkfull/jdk-21.0.13+9')) / 'bin'


def java_tool(name):
    """The VM JDK lives under /tmp/jdkfull; on the Mac use whatever is on PATH."""
    candidate = JAVA_BIN / name
    return str(candidate) if candidate.exists() else name
PRODUCT_CLASSES = ('SdBridge SdStartup SdClassLoaderNamespaces SdGraphicsEnvironment SdRuntime '
                   'SdRuntimeDiagnostics SdViewDump SdViewRepair SdRuntimeControl SdKernelServices '
                   'SdBinderRegistry SdSensorService SdServiceEndpoint SdRemoteServices '
                   'SdApkPackage SdAppPermissions SdActivityManagerService '
                   'SdActivityTaskManager SdActivityHost SdServiceHost SdServiceManagerStub '
                   'SdServices SdPackageManagerService SdStorageManager SdUsers SdDisplayShim '
                   'SdWindowHost SdWindowManager SdWindowSession SdDisplayFrames '
                   'SdSurfaceStore SdSurfaceControls SdMaliit SdInputMethods SdConnectivity '
                   'SdHostState SdPower SdKeyguard SdNotificationPolicy SdContentService '
                   'SdContentProviders SdSettingsProvider SdWebEngine SdWebInterfaces SdWebCookies SdWebViewProvider').split()

BINDING = re.compile(r'(\w+)\s*=\s*\(\*e\)->NewGlobalRef\(e,\(\*e\)->FindClass\(e,"([^"]+)"\)\)')
JCLASS_BINDING = re.compile(r'jclass\s+(\w+)\s*=\s*\(\*e\)->FindClass\(e,"([^"]+)"\)')
GLOBAL_BINDING = re.compile(r'(\w+)\s*=\s*\(\*e\)->NewGlobalRef\(e,c\)')
FIELD_CALL = re.compile(r'GetStaticFieldID\(e,(\w+),"([^"]+)","([^"]+)"\)')
METHOD_CALL = re.compile(r'GetStaticMethodID\(e,(\w+),"([^"]+)","([^"]+)"\)')
FINDCLASS = re.compile(r'FindClass\(e,"([^"]+)"\)')
TABLE_DECL = re.compile(r'JNINativeMethod\s+(\w+)\s*\[\]\s*=\s*\{(.*?)\};', re.S)
TABLE_ENTRY = re.compile(r'\{"(\w+)","([^"]+)",(\w+)\}')
REGISTER = re.compile(r'RegisterNatives\(e,\(\*e\)->FindClass\(e,"([^"]+)"\),(\w+),')
JNI_EXPORT = re.compile(r'JNIEXPORT\s+\w+(?:\s+\w+)*\s+JNICALL\s+(Java_\w+)')
HOST_FN = re.compile(r'Java_(\w+)_nativeInstall')


def native_sources():
    return sorted(NATIVE_DIR.glob('*.c'))


def parse_native():
    """Collect every JNI lookup the native side makes, with the class it targets."""
    bindings = {}
    host_class = None
    fields, methods, findclasses, tables = [], [], [], []
    for path in native_sources():
        text = path.read_text()
        for match in HOST_FN.finditer(text):
            host_class = match.group(1)
        bindings.update({var: cls for var, cls in BINDING.findall(text)})
        bindings.update({var: cls for var, cls in JCLASS_BINDING.findall(text)})
        for var in GLOBAL_BINDING.findall(text):
            bindings.setdefault(var, host_class)
        for var, name, sig in FIELD_CALL.findall(text):
            fields.append(dict(file=path.name, cls=bindings.get(var), var=var,
                               name=name, sig=sig))
        for var, name, sig in METHOD_CALL.findall(text):
            methods.append(dict(file=path.name, cls=bindings.get(var, host_class),
                                var=var, name=name, sig=sig))
        for cls in FINDCLASS.findall(text):
            findclasses.append(dict(file=path.name, cls=cls))
        for table, body in TABLE_DECL.findall(text):
            tables.append(dict(file=path.name, table=table,
                               entries=[dict(name=n, sig=s, symbol=f)
                                        for n, s, f in TABLE_ENTRY.findall(body)]))
    registers = []
    for path in native_sources():
        for cls, table in REGISTER.findall(path.read_text()):
            registers.append(dict(file=path.name, cls=cls, table=table))
    for table in tables:
        table['registered'] = [r for r in registers if r['table'] == table['table']]
    return fields, methods, findclasses, tables


FUNC_DEF = re.compile(r'^[A-Za-z_][\w\s\*]*?\b(\w+)\s*\([^;{}]*\)\s*\{', re.M)


def native_functions():
    """Names of functions defined in native/window/*.c (link targets of the tables)."""
    defined = set()
    for path in native_sources():
        defined.update(FUNC_DEF.findall(path.read_text()))
    return defined


def java_sources():
    sources = [JAVA_DIR / (name + '.java') for name in PRODUCT_CLASSES]
    sources += sorted((JAVA_DIR / 'org/saildroid/manager').glob('*.java'))
    return [path for path in sources if path.exists()]


def compile_java(workdir):
    classes = workdir / 'classes'
    classes.mkdir()
    cmd = [java_tool('javac'), '--release', '8', '-nowarn',
           '-cp', str(FRAMEWORK_JAR), '-d', str(classes)] + [str(p) for p in java_sources()]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stdout[-3000:])
        print(done.stderr[-3000:])
        raise SystemExit('GATE_REFUSED|javac_failed')
    return classes


def _class_members(data, public_only=False):
    """(name -> set of descriptors) for fields and methods, straight from bytecode."""
    pos = 10
    count = int.from_bytes(data[8:10], 'big')
    utf8, index = {}, 1
    while index < count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            size = int.from_bytes(data[pos:pos + 2], 'big')
            utf8[index] = data[pos + 2:pos + 2 + size].decode('utf-8', 'replace')
            pos += 2 + size
        elif tag in (7, 8, 16, 19, 20):
            pos += 2
        elif tag in (15,):
            pos += 3
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            pos += 4
        elif tag in (5, 6):
            pos += 8
            index += 1
        else:
            raise ValueError('unknown constant pool tag %d' % tag)
        index += 1
    class_access = int.from_bytes(data[pos:pos + 2], 'big')
    if public_only and not class_access & 5:
        return {}
    pos += 6                                       # access, this, super
    interfaces = int.from_bytes(data[pos:pos + 2], 'big')
    pos += 2 + 2 * interfaces
    found = {}
    for _section in (0, 1):                        # fields, then methods
        total = int.from_bytes(data[pos:pos + 2], 'big')
        pos += 2
        for _ in range(total):
            access = int.from_bytes(data[pos:pos + 2], 'big')
            name_index = int.from_bytes(data[pos + 2:pos + 4], 'big')
            descriptor_index = int.from_bytes(data[pos + 4:pos + 6], 'big')
            attributes = int.from_bytes(data[pos + 6:pos + 8], 'big')
            pos += 8
            for _attribute in range(attributes):
                size = int.from_bytes(data[pos + 2:pos + 6], 'big')
                pos += 6 + size
            if not public_only or access & 5:
                found.setdefault(utf8.get(name_index), set()).add(utf8.get(descriptor_index))
    return found


def members(classes, class_name):
    path = Path(classes) / (class_name.replace('.', '/') + '.class')
    if not path.exists():
        return None
    return _class_members(path.read_bytes())


def framework_members(jar, class_name):
    if not jar.exists():
        return None
    with zipfile.ZipFile(jar) as archive:
        entry = class_name + '.class'
        if entry not in archive.namelist():
            return None
        return _class_members(archive.read(entry))


def framework_classes():
    if not FRAMEWORK_JAR.exists():
        return set()
    with zipfile.ZipFile(FRAMEWORK_JAR) as jar:
        return set(jar.namelist())


def check_so(so_path):
    """A built library is only worth measuring if it exists and is non-trivial."""
    if not so_path.is_file():
        return 'built library %s is missing' % so_path
    if so_path.stat().st_size < 4096:
        return 'built library %s is suspiciously small' % so_path
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--so', default=None, help='built libsdwindow.so, to verify exports')
    ap.add_argument('--native-dir', default=str(NATIVE_DIR),
                    help='override the native source directory (self-test)')
    ap.add_argument('--java-dir', default=str(JAVA_DIR),
                    help='override the Java source directory (self-test)')
    args = ap.parse_args()
    globals()['NATIVE_DIR'] = Path(args.native_dir)
    globals()['JAVA_DIR'] = Path(args.java_dir)

    fields, methods, findclasses, tables = parse_native()
    problems, checked = [], 0

    workdir = Path(tempfile.mkdtemp(prefix='jni-contract-'))
    try:
        classes = compile_java(workdir)
        cache = {}
        for item in fields + methods:
            cls = item['cls']
            if not cls:
                problems.append('%s: %s(...) uses an unmapped class variable %r'
                                % (item['file'], 'GetStaticFieldID' if item in fields
                                   else 'GetStaticMethodID', item['var']))
                continue
            if cls not in cache:
                cache[cls] = members(classes, cls)
            table = cache[cls]
            if table is None:
                problems.append('%s: class %s not found in the compiled product'
                                % (item['file'], cls))
                continue
            checked += 1
            if item['sig'] not in (table.get(item['name']) or set()):
                actual = sorted(table.get(item['name']) or ['<missing>'])
                problems.append('%s: %s.%s wanted (%s) but Java has (%s)'
                                % (item['file'], cls, item['name'], item['sig'],
                                   ', '.join(actual)))

        fw = framework_classes()
        seen_findclass = set()
        for item in findclasses:
            cls = item['cls']
            if (item['file'], cls) in seen_findclass:
                continue
            seen_findclass.add((item['file'], cls))
            if cls.startswith('java/'):
                checked += 1        # boot classes are always present in ART
                continue
            if cls.startswith('android/'):
                checked += 1
                if fw and (cls + '.class') not in fw:
                    problems.append('%s: FindClass(%s) not found in the framework jar'
                                    % (item['file'], cls))
            else:
                checked += 1
                if cache.get(cls) is None and members(classes, cls) is None:
                    problems.append('%s: FindClass(%s) not in the product sources'
                                    % (item['file'], cls))

        functions = native_functions()
        if args.so:
            problem = check_so(Path(args.so))
            if problem:
                problems.append(problem)
        for table in tables:
            for entry in table['entries']:
                if table['registered']:
                    cls = table['registered'][0]['cls']
                    if cls.startswith(('android/', 'java/')):
                        # We deliberately re-register framework natives (that is the
                        # whole point of the shim); verify against the framework jar.
                        current = framework_members(FRAMEWORK_JAR, cls)
                        if current is None:
                            problems.append('%s: class %s is not in the framework jar'
                                            % (table['file'], cls))
                            continue
                    else:
                        current = cache.get(cls)
                        if current is None:
                            current = members(classes, cls)
                            cache[cls] = current
                    checked += 1
                    if current is None or entry['sig'] not in (current.get(entry['name']) or set()):
                        problems.append('%s: RegisterNatives %s.%s (%s) has no Java native '
                                        'method with that signature'
                                        % (table['file'], cls, entry['name'], entry['sig']))
                checked += 1
                if entry['symbol'] not in functions:
                    problems.append('%s: RegisterNatives %s registers %s, which is not '
                                    'defined in native/window' % (table['file'], table['table'],
                                                                  entry['symbol']))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print('JNI_CONTRACT_CHECKED=%d' % checked)
    if problems:
        for problem in problems:
            print('JNI_CONTRACT_MISMATCH|' + problem)
        print('BUILD_RC=refused_field_mismatch')
        return 3
    print('JNI_CONTRACT_OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
