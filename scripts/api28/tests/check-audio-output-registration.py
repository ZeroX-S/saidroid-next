#!/usr/bin/env python3
"""Verify the real native audio table and callbacks through a host JNI fixture."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    repository = Path(__file__).resolve().parents[3]
    parser.add_argument('--source', type=Path, default=repository / 'native/host/host-audio.cpp')
    parser.add_argument('--jni-include', type=Path, required=True)
    arguments = parser.parse_args()
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0', 'libpulse'], text=True).split()
    with tempfile.TemporaryDirectory(prefix='saildroid-audio-registration-') as temporary:
        executable = Path(temporary) / 'probe'
        subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(arguments.jni_include), '-I' + str(arguments.jni_include / 'linux'),
                        '-o', str(executable), str(arguments.source),
                        str(repository / 'native/host/tests/audio-output-registration.cpp'),
                        *flags, '-pthread'], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    main()
