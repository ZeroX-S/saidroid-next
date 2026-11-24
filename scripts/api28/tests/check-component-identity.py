#!/usr/bin/env python3
"""Check production native component validation with Java nested class names."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jni-include', type=Path, required=True)
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    source = repository / 'native/host/host-manager.cpp'
    assert 'if (!valid_package(a) || !valid_component(b) ||' in source.read_text(encoding='utf-8')
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0'], text=True).split()
    with tempfile.TemporaryDirectory(prefix='saildroid-component-identity-') as temporary:
        executable = Path(temporary) / 'probe'
        subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-ffunction-sections',
                        '-fdata-sections', '-Wl,--gc-sections', '-I' + str(arguments.jni_include),
                        '-I' + str(arguments.jni_include.parent), '-o', str(executable),
                        str(repository / 'native/host/tests/component-identity.cpp'), *flags, '-ldl', '-pthread'],
                       check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    main()
