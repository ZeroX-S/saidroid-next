#!/usr/bin/env python3
"""Build the API29 product from the current sources (perf instrumentation included).

Run inside the MeeGo Build VM:
    python3 scripts/perf/build-perf-product-vm.py /var/tmp/saidroid-next-api29-product-perf1

The product build is the repository's own script (scripts/runtime/build-product.py);
this wrapper only fixes the isolated output directory and then packages one
component bundle for deploy-component.py.
"""
from pathlib import Path
import subprocess, sys, json

repo = Path('/media/psf/Home/WorkSpace/saidroid-next')
inputs = repo / 'build/codex-api29/inputs'

def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: build-perf-product-vm.py <new product dir>')
    out = Path(sys.argv[1])
    assert str(out).startswith('/var/tmp/saidroid-next-'), 'keep outputs under /var/tmp'
    assert not out.exists(), 'refuse to overwrite an existing build'
    subprocess.run([sys.executable, str(repo / 'scripts/runtime/build-product.py'), str(inputs), str(out)], check=True)
    print('PRODUCT', out)

if __name__ == '__main__':
    main()
