#!/usr/bin/env python3
"""Unified host regression test, live-daemon verification, AArch64 QEMU, and native build runner."""
from pathlib import Path
import argparse
import json
import os
import py_compile
import shutil
import stat
import subprocess
import sys
import tempfile
import time


REPO = Path(__file__).resolve().parents[1]
FRAMEWORK_JAR = 'android-all-9-robolectric-4913185-2.jar'


def resolve_java_home() -> Path:
    configured = os.environ.get('JAVA_HOME')
    if configured and (Path(configured) / 'bin/javac').is_file():
        return Path(configured)
    compiler = shutil.which('javac')
    if not compiler:
        raise SystemExit('ERROR: javac not found; set JAVA_HOME or install JDK 21')
    return Path(compiler).resolve().parents[1]


def run_step(label: str, command: list[str], env: dict[str, str] | None = None) -> float:
    started = time.monotonic()
    print(f'==> [{label}]', flush=True)
    subprocess.run(command, cwd=REPO, env=env, check=True)
    elapsed = time.monotonic() - started
    print(f'    PASS ({elapsed:.2f}s)', flush=True)
    return elapsed


def verify_native_builds(work: Path, jni_include: Path) -> Path:
    out = work / 'native'
    out.mkdir(parents=True, exist_ok=True)
    jni_flags = [f'-I{jni_include}', f'-I{jni_include / "linux"}']
    art_includes = [
        f'-I{REPO / "third_party/art-standalone/libnativehelper/include/nativehelper"}',
        f'-I{REPO / "third_party/art-standalone/libnativehelper/include"}',
    ]
    wayland_flags = subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'wayland-client', 'libpng'], text=True
    ).split()
    gio_flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0'], text=True).split()
    pulse_flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libpulse'], text=True).split()
    gst_flags = subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'gstreamer-1.0', 'gstreamer-app-1.0', 'gstreamer-video-1.0'], text=True
    ).split()

    xdg_xml = '/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml'
    subprocess.run(['wayland-scanner', 'client-header', xdg_xml, str(out / 'xdg-shell-client-protocol.h')], check=True)
    subprocess.run(['wayland-scanner', 'private-code', xdg_xml, str(out / 'xdg-shell-protocol.c')], check=True)
    surf_xml = str(REPO / 'native/window/surface-extension.xml')
    subprocess.run(['wayland-scanner', 'client-header', surf_xml, str(out / 'surface-extension-client-protocol.h')], check=True)
    subprocess.run(['wayland-scanner', 'private-code', surf_xml, str(out / 'surface-extension-protocol.c')], check=True)

    maliit_xml = (REPO / 'native/ime/minputmethodcontext1interface.xml').read_text(encoding='utf-8')
    (out / 'maliit-client-xml.h').write_text(
        'static const char maliit_client_xml[]=' + json.dumps(maliit_xml) + ';\n', encoding='utf-8'
    )

    subprocess.run([
        'g++', '-c', '-fPIC', '-O2', '-Wall', '-fno-exceptions', '-fno-rtti',
        '-o', str(out / 'binder.o'), str(REPO / 'native/compat/runtime-binder.cpp'), *jni_flags,
    ], check=True)
    subprocess.run([
        'gcc', '-c', '-fPIC', '-O2', '-Wall',
        '-Dsd_activation_start=sd_runtime_control_start',
        '-Dsd_activation_stop=sd_runtime_control_stop',
        '-o', str(out / 'runtime-control.o'), str(REPO / 'native/window/sdactivate.c'),
    ], check=True)
    subprocess.run([
        'gcc', '-shared', '-fPIC', '-O2', '-Wall',
        '-o', str(out / 'libsdbridge.so'),
        str(REPO / 'scripts/device/sdbridge.c'),
        str(REPO / 'native/compat/runtime-memory.c'),
        str(REPO / 'native/compat/runtime-eventlog.c'),
        str(REPO / 'native/compat/runtime-hardware-properties.c'),
        str(out / 'binder.o'),
        str(out / 'runtime-control.o'),
        str(REPO / 'native/launcher/sdruntime-control.c'),
        *jni_flags, '-ldl', '-pthread',
    ], check=True)
    subprocess.run([
        'gcc', '-shared', '-fPIC', '-O2', '-Wall',
        '-o', str(out / 'libsdwindow.so'),
        str(REPO / 'native/window/sdwindow.c'),
        str(REPO / 'native/window/native-display-events.c'),
        str(REPO / 'native/hwui/sd-hwui-host.c'),
        str(REPO / 'native/hwui/sd-hwui-background.c'),
        str(REPO / 'native/window/sdcontrol.c'),
        str(REPO / 'native/window/sdactivate.c'),
        str(out / 'xdg-shell-protocol.c'),
        str(out / 'surface-extension-protocol.c'),
        f'-I{out}', *jni_flags, *wayland_flags, '-pthread', '-ldl',
    ], check=True)
    subprocess.run([
        'gcc', '-shared', '-fPIC', '-O2', '-Wall',
        '-o', str(out / 'libsdhost29.so'),
        *[str(REPO / f'native/compat/runtime-{part}.c') for part in (
            'host', 'fdsan', 'signal', 'diagnostics', 'regex', 'egl-host',
            'thread', 'cfi', 'renderscript', 'native-loader', 'hardware-loader', 'shared-dex',
        )],
        *jni_flags, '-ldl', '-pthread',
    ], check=True)
    subprocess.run([
        'gcc', '-shared', '-fPIC', '-O2', '-Wall',
        '-o', str(out / 'libsdmaliit.so'),
        str(REPO / 'native/ime/sdmaliit.c'),
        f'-I{out}', *jni_flags, *gio_flags, '-pthread',
    ], check=True)
    subprocess.run([
        'gcc', '-O2', '-Wall', '-Wextra',
        '-o', str(out / 'saildroid-app'),
        str(REPO / 'native/host/host-bootstrap.c'),
    ], check=True)
    subprocess.run([
        'g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-fPIC', '-shared',
        '-o', str(out / 'libsdhostapi.so'),
        str(REPO / 'native/host/host-api.cpp'),
        str(REPO / 'native/host/host-audio.cpp'),
        str(REPO / 'native/host/host-audio-record.cpp'),
        str(REPO / 'native/host/host-network.cpp'),
        *art_includes, *gio_flags, *pulse_flags, '-pthread',
    ], check=True)
    subprocess.run([
        'g++', '-std=c++17', '-O2', '-fwrapv', '-Wall', '-Wextra', '-fPIC', '-shared',
        '-o', str(out / 'libsdvoip.so'),
        str(REPO / 'native/rtp/PulseAudioGroup.cpp'),
        str(REPO / 'native/rtp/G711Codec.cpp'),
        str(REPO / 'native/rtp/EchoSuppressor.cpp'),
        *art_includes, *pulse_flags, '-pthread',
    ], check=True)
    for host_unit in ('saildroid-app.cpp', 'host-entry.cpp', 'host-manager.cpp'):
        subprocess.run([
            'g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-c',
            '-o', str(out / (host_unit + '.o')),
            str(REPO / 'native/host' / host_unit),
            *art_includes, *gio_flags,
        ], check=True)
    subprocess.run([
        'g++', '-O2', '-std=c++17', '-Wall', '-Wextra', '-Werror=return-type',
        str(REPO / 'native/media/droid-camera/camera-helper.cpp'),
        '-o', str(out / 'sdcamera-helper'), '-ldl', '-pthread',
    ], check=True)
    subprocess.run([
        'g++', '-shared', '-fPIC', '-O2', '-std=c++17', '-Wall', '-Wextra', '-Werror=return-type',
        *jni_flags, str(REPO / 'native/media/droid-camera/camera-host.cpp'),
        '-o', str(out / 'libsdcamera-host.so'), '-ldl', '-pthread', '-Wl,-z,defs',
    ], check=True)
    subprocess.run([
        'g++', '-shared', '-fPIC', '-O2', '-std=c++17', '-Wall', '-Wextra', '-Werror=return-type',
        *jni_flags, str(REPO / 'native/media/gstreamer-player/player-host.cpp'),
        '-o', str(out / 'libsdmediaplayer-host.so'), *gst_flags, '-ldl', '-pthread', '-Wl,-z,defs',
    ], check=True)
    subprocess.run([
        'g++', '-std=c++17', '-O2', '-Wall', '-Wextra',
        str(REPO / 'native/webview/qt-helper/native-host.cpp'),
        '-o', str(out / 'sdwebview-host'),
    ], check=True)
    moc = '/usr/lib/qt5/bin/moc' if Path('/usr/lib/qt5/bin/moc').is_file() else shutil.which('moc')
    if moc:
        qt_cflags = subprocess.check_output(
            ['pkg-config', '--cflags', 'Qt5Quick', 'Qt5Qml', 'Qt5Gui', 'Qt5Core', 'glesv2', 'gobject-2.0', 'glib-2.0'],
            text=True,
        ).split()
        qt_libs = subprocess.check_output(
            ['pkg-config', '--libs', 'Qt5Quick', 'Qt5Qml', 'Qt5Gui', 'Qt5Core', 'glesv2', 'gobject-2.0', 'glib-2.0'],
            text=True,
        ).split()
        subprocess.run([str(moc), str(REPO / 'native/webview/qt-helper/sdwebviewd.cpp'), '-o', str(out / 'sdwebviewd.moc')], check=True)
        subprocess.run([
            'g++', '-std=c++17', '-O2', '-fPIC', '-Wall', '-Wextra', '-Wno-deprecated-copy',
            *qt_cflags, f'-I{out}',
            str(REPO / 'native/webview/qt-helper/sdwebviewd.cpp'),
            '-Wl,--allow-shlib-undefined', *qt_libs,
            '-o', str(out / 'sdwebviewd'),
        ], check=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=REPO / 'build/inputs')
    parser.add_argument('--skip-native', action='store_true')
    args = parser.parse_args()

    inputs = args.inputs.resolve()
    framework = inputs / FRAMEWORK_JAR
    if not framework.is_file():
        raise SystemExit(f'ERROR: missing {framework}; run bash tools/setup-dev-env.sh first')

    java_home = resolve_java_home()
    jni_include = java_home / 'include'
    env = dict(os.environ, JAVA_HOME=str(java_home))
    started_all = time.monotonic()
    passed = 0

    with tempfile.TemporaryDirectory(prefix='saildroid-test-suite-') as temp_dir:
        work = Path(temp_dir)
        product_out = work / 'product'
        classes_dir = product_out / 'classes'

        run_step(
            'product-compat-preflight',
            [sys.executable, 'scripts/runtime/build-product.py', str(inputs), str(product_out), '--compat-only'],
            env=env,
        )
        passed += 1

        native_out: Path | None = None
        if not args.skip_native:
            print('==> [native-compile-all]', flush=True)
            t0 = time.monotonic()
            native_out = verify_native_builds(work, jni_include)
            print(f'    PASS ({time.monotonic() - t0:.2f}s)', flush=True)
            passed += 1

        run_step(
            'compat-unit-tests',
            [sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts/compat/tests'],
            env=env,
        )
        passed += 1

        run_step(
            'cts-unit-tests',
            [sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts/cts/tests'],
            env=env,
        )
        passed += 1

        pa_cmd = [
            sys.executable, 'native/host/tests/test-pulseaudio-live.py',
            '--framework', str(framework), '--classes', str(classes_dir), '--jni-include', str(jni_include),
        ]
        if native_out and (native_out / 'libsdhostapi.so').is_file():
            pa_cmd.extend(['--hostapi-so', str(native_out / 'libsdhostapi.so')])

        wl_cmd = [
            sys.executable, 'native/window/tests/test-wayland-headless.py',
            '--framework', str(framework), '--classes', str(classes_dir), '--jni-include', str(jni_include),
        ]
        if native_out and (native_out / 'libsdwindow.so').is_file():
            wl_cmd.extend(['--window-so', str(native_out / 'libsdwindow.so')])

        for label, cmd in [
            ('hardware-identity', [sys.executable, 'scripts/runtime/tests/check-hardware-identity.py']),
            ('webview-geometry', [sys.executable, 'scripts/runtime/tests/test-webview-geometry-vm.py', '--android-jar', str(framework)]),
            ('webview-shm', [sys.executable, 'scripts/runtime/tests/test-webview-shm.py', '--android-jar', str(framework)]),
            ('native-loader', [sys.executable, 'scripts/runtime/tests/test-native-loader-vm.py']),
            ('app-aot-cache', [sys.executable, 'scripts/perf/test-app-aot-cache-vm.py']),
            ('aarch64-contracts', [sys.executable, 'tools/test-aarch64-contracts.py']),
            ('host-manager-dbus', ['bash', 'native/host/tests/run-vm.sh']),
            ('pulseaudio-live', pa_cmd),
            ('wayland-headless', wl_cmd),
            ('audio-output-registration', [sys.executable, 'scripts/api28/tests/check-audio-output-registration.py', '--jni-include', str(jni_include)]),
            ('audio-sink-metadata', [sys.executable, 'scripts/api28/tests/check-audio-sink-metadata.py', '--jni-include', str(jni_include)]),
            ('component-identity', [sys.executable, 'scripts/api28/tests/check-component-identity.py', '--jni-include', str(jni_include)]),
        ]:
            run_step(label, cmd, env=env)
            passed += 1

        fakeroot = shutil.which('fakeroot')
        if os.geteuid() == 0 or fakeroot:
            prefix = [] if os.geteuid() == 0 else [fakeroot]
            for label, cmd in [
                ('binder-setup', [*prefix, sys.executable, 'scripts/packaging/test-binder-setup.py']),
                ('product-properties', [*prefix, sys.executable, 'native/compat/tests/check-product-properties.py']),
                ('host-timezone', [
                    *prefix, sys.executable, 'native/compat/tests/check-host-timezone.py',
                    '--framework', str(framework), '--jni-include', str(jni_include),
                ]),
            ]:
                run_step(label, cmd, env=env)
                passed += 1
            if os.geteuid() == 0:
                run_step('setup-vm', [sys.executable, 'scripts/packaging/test-setup-vm.py', '--output', str(work / 'setup-vm')], env=env)
                passed += 1
        else:
            print('==> [packaging-root-fixtures] SKIP (requires root or fakeroot)', flush=True)

        for test_name in (
            'test-process-startup.py',
            'test-activity-clear-top.py',
            'test-document-picker-render.py',
            'test-explicit-broadcast-dispatch.py',
            'test-popup-touch-target.py',
        ):
            run_step(f'runtime-{test_name}', [sys.executable, f'scripts/runtime/tests/{test_name}'], env=env)
            passed += 1

        device_tests_with_classes = {
            'check-activity-task-id.py',
            'check-audio-speakerphone.py',
            'check-connectivity-callbacks.py',
            'check-foreign-broadcast.py',
            'check-input-method-finish.py',
            'check-package-safe-mode.py',
            'check-text-services.py',
            'check-wake-locks.py',
        }
        device_tests_framework_only = {
            'check-app-widgets.py',
            'check-notification-channel-arguments.py',
            'check-runtime-permissions.py',
            'check-window-haptics.py',
        }
        for script in sorted((REPO / 'scripts/device/tests').glob('check-*.py')):
            cmd = [sys.executable, str(script.relative_to(REPO))]
            if script.name in device_tests_with_classes:
                cmd.extend(['--framework', str(framework), '--classes', str(classes_dir)])
            elif script.name in device_tests_framework_only:
                cmd.extend(['--framework', str(framework)])
            run_step(f'device-{script.name}', cmd, env=env)
            passed += 1

        print('==> [packaging-syntax-and-scripts]', flush=True)
        for pkg_py in sorted((REPO / 'scripts/packaging').glob('*.py')):
            py_compile.compile(str(pkg_py), doraise=True)
        subprocess.run([
            sys.executable, '-c',
            'import importlib.util; '
            's=importlib.util.spec_from_file_location("m","scripts/packaging/saildroid-setup.py"); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
            'scripts=m.rpm_install_scripts("api28-check"); '
            'assert "preinstall" in scripts and "posttrans" in scripts',
        ], cwd=REPO, check=True)
        print('    PASS', flush=True)
        passed += 1

    total_s = time.monotonic() - started_all
    print(f'\nSAILDROID_TESTS=PASS|suites={passed}|elapsed_s={total_s:.2f}', flush=True)


if __name__ == '__main__':
    main()
