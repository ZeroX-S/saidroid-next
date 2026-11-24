#!/usr/bin/env python3
"""Install one perf component bundle and repoint /home/art/api29-root at it.

Run inside the MeeGo Build VM, *after* scripts/devlock.sh acquire: the deploy
helper itself refuses while any owned ART process is alive.

    python3 scripts/perf/deploy-perf-release-vm.py perf1

Installs /home/art/releases/api29-<tag> and records the previous target so
scripts/perf/restore-baseline-vm.py can put r63 back.
"""
from pathlib import Path
import json, subprocess, sys

REPO = Path('/media/psf/Home/WorkSpace/saidroid-next')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: deploy-perf-release-vm.py <tag>')
    tag = sys.argv[1]
    component = Path('/var/tmp/saidroid-next-api29-component-perf-' + tag)
    assert (component / 'component.tar.gz').is_file(), 'build the release first'
    run = '20261026-' + tag
    subprocess.run([sys.executable, str(REPO / 'scripts/runtime/deploy-component.py'),
                    str(component), run], check=True)
    print('PERF_RELEASE_INSTALLED=api29-' + run)


if __name__ == '__main__':
    main()
