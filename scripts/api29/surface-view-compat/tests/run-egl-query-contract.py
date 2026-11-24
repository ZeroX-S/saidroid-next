import os
from pathlib import Path
import subprocess
import tempfile


tests = Path(__file__).resolve().parent
source = tests.parent / 'source/api29-egl-host.c'
with tempfile.TemporaryDirectory(prefix='saildroid-egl-query-') as temporary:
    output = Path(temporary)
    common = ['gcc', '-O2', '-Wall', '-Wextra', '-Werror']
    subprocess.run(common + ['-shared', '-fPIC', str(tests / 'egl-query-driver.c'),
                              '-o', str(output / 'libEGL.so.1')], check=True)
    subprocess.run(common + [str(tests / 'egl-query-contract.c'), str(source),
                              '-Wl,--wrap=malloc', '-ldl', '-pthread',
                              '-o', str(output / 'contract')], check=True)
    environment = dict(os.environ, LD_LIBRARY_PATH=str(output))
    subprocess.run([str(output / 'contract')], env=environment, check=True)
