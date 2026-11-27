#!/usr/bin/env python3
"""Build one API29 component whose only difference from the installed baseline
is the rebuilt native window library (per-frame perf sampling included).

Run inside the MeeGo Build VM:

    python3 scripts/perf/build-perf-release-vm.py perf1 [--from-product DIR]

The product is compiled by the repository's own `scripts/runtime/build-product.py`
from the current worktree. The manifest records the git revision, the dirty
file list and the hashes of the frame-path sources, so any unrelated edit from
another work stream is visible in the evidence instead of silently mixed in.

`--from-product DIR` copies an existing product and rebuilds only
libsdwindow.so. Use it only when the Java side is known to be identical to the
baseline (a native-only change).
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys

REPO = Path('/media/psf/Home/WorkSpace/saidroid-next')
INPUTS = REPO / 'build/codex-api29/inputs'
BASELINE_PRODUCT = Path('/var/tmp/saidroid-next-api29-product-r78')
# Team baseline since r78: r63 inputs + the perf sampler/fast path + the fixed
# provider + the framework LayoutParams patches. A perf build must differ from the
# baseline in libsdwindow.so only, otherwise before/after is not a comparison.
FRAMEWORK = Path('/var/tmp/saidroid-next-api29-framework-20261027-r6')
CORE = Path('/var/tmp/saidroid-next-api29-core-20261025-r10')
NATIVE = Path('/var/tmp/saidroid-next-api29-native-20261025-r1')
LINKER = Path('/var/tmp/saidroid-next-api29-linker-20261026-r6')
MANAGER = Path('/var/tmp/saidroid-next-api29-manager-20261026-r18')
JAVA = Path(os.environ.get('JAVA_HOME', '/tmp/jdkfull/jdk-21.0.13+9')) / 'bin'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_native_library(product):
    """Same command as scripts/runtime/build-product.py, current sources."""
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'wayland-client'],
                                    text=True).split()
    include = JAVA.parent / 'include'
    command = ['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-o', str(product / 'libsdwindow.so'),
               str(REPO / 'native/window/sdwindow.c'),
               str(REPO / 'native/hwui/sd-hwui-host.c'),
               str(REPO / 'native/hwui/sd-hwui-background.c'),
               str(REPO / 'native/window/sdcontrol.c'),
               str(REPO / 'native/window/sdactivate.c'),
               str(product / 'xdg-shell-protocol.c'),
               str(product / 'surface-extension-protocol.c'),
               '-I' + str(product), '-I' + str(include), '-I' + str(include / 'linux'),
               *flags, '-pthread', '-ldl']
    log = (product / 'native-rebuild.log').open('wb')
    try:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    finally:
        log.close()
    return command


def jni_contract_gate(so=None):
    """Refuse to build when a JNI lookup in native/window would resolve to NULL.

    r64 shipped `GetStaticFieldID(..., "lastLayerCount", "J")` against a Java `int`
    field; the NULL id produced a pending NoSuchFieldError and ART aborted the app
    with SIGSEGV. A name-level grep cannot see that, a descriptor-level gate can.
    """
    command = [sys.executable, str(REPO / 'scripts/perf/check-jni-contract.py')]
    if so is not None:
        command += ['--so', str(so)]
    done = subprocess.run(command, capture_output=True, text=True)
    print(done.stdout.strip())
    if done.returncode != 0:
        raise SystemExit('BUILD_RC=refused_field_mismatch (see above; fix the Java/native '
                         'signature pair before building)')


def worktree_state():
    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=str(REPO), text=True).strip()
    return dict(commit=git('rev-parse', 'HEAD'),
                dirty=git('status', '--porcelain').splitlines())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tag')
    ap.add_argument('--from-product', type=Path, default=None)
    ap.add_argument('--skip-package', action='store_true')
    ap.add_argument('--framework', type=Path, default=None,
                    help='override the framework input (default: the r78 framework)')
    args = ap.parse_args()
    assert args.tag and all(c.isalnum() or c == '-' for c in args.tag), 'tag must be [a-z0-9-]'
    product = Path('/var/tmp/saidroid-next-api29-product-perf-' + args.tag)
    component = Path('/var/tmp/saidroid-next-api29-component-perf-' + args.tag)
    assert not product.exists() and not component.exists(), 'refuse to overwrite an existing build'

    jni_contract_gate()
    framework = args.framework or FRAMEWORK

    if args.from_product is not None:
        assert str(args.from_product).startswith('/var/tmp/saidroid-next-')
        shutil.copytree(args.from_product, product)
        (product / 'libsdwindow.so').rename(product / 'libsdwindow.so.before-perf')
        build_native_library(product)
    else:
        subprocess.run([sys.executable, str(REPO / 'scripts/runtime/build-product.py'),
                        str(INPUTS), str(product)], check=True)
    jni_contract_gate(product / 'libsdwindow.so')
    manifest = json.loads((product / 'manifest.json').read_text())
    manifest.setdefault('perf', {})
    manifest['perf'] = {
        'feature': 'SAILDROID_PERF per-frame sampling (environment gated)',
        'base_product': str(args.from_product) if args.from_product else 'rebuilt from worktree',
        'framework': str(framework),
        'worktree': worktree_state(),
        'libsdwindow.so': sha256(product / 'libsdwindow.so'),
        'sources': {str(f.relative_to(REPO)): sha256(f) for f in [
            REPO / 'native/window/sdwindow.c',
            REPO / 'native/window/sdcontrol.c',
            REPO / 'native/window/sdactivate.c',
            REPO / 'scripts/device/SdSurfaceStore.java']},
    }
    manifest['files']['libsdwindow.so'] = sha256(product / 'libsdwindow.so')
    (product / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('PERF_PRODUCT=' + str(product))
    print('LIBSD_WINDOW_SHA256=' + manifest['perf']['libsdwindow.so'])
    if args.skip_package:
        return

    subprocess.run([sys.executable, str(REPO / 'scripts/runtime/package-component.py'),
                    str(INPUTS), str(framework), str(CORE), str(product), str(MANAGER),
                    str(NATIVE), str(LINKER), str(component),
                    '--binder-device', '/home/art/runtime/binder/binder'], check=True)
    print('PERF_COMPONENT=' + str(component))


if __name__ == '__main__':
    main()
