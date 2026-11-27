#!/usr/bin/env python3
"""Offline control-flow test for drawer/Home navigation (no device needed).

Feeds recorded device frames into ``open_drawer`` / ``ensure_home`` so the
decision logic that used to produce false PASSes (Home vs drawer vs dock peek)
is exercised without a phone.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FRAMES = REPO / 'build/evidence/int-perf3-i1/frames'
FIXTURE_ICON = REPO / 'build/codex-api29/fixtures/qq-icon.png'

DRAWER = FRAMES / 'drawer-precondition.png'
HOME_ONE = FRAMES / 'home-cold-before-1.png'
PEEK = FRAMES / 'drawer-cold.png'


def load_matrix():
    spec = importlib.util.spec_from_file_location('im', HERE / 'integration-matrix.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeMatrix:
    """Returns the scripted frames from ``shot`` and records their names."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.names = []
        self.shot_dir = Path('/tmp/nav-logic')

    def shot(self, name, expect=None):
        self.names.append(name)
        path = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        return {'path': str(path), 'covers': cover_count(path), 'cells': [],
                'blank': False, 'low_content': False}


def cover_count(path):
    import sd_covers
    return sd_covers.analyze(path)[0]


def main():
    failures = []
    module = load_matrix()
    module.tap = lambda x, y: TOUCHED.append(('tap', x, y))
    module.swipe = lambda x1, y1, x2, y2, ms=400, steps=24: TOUCHED.append(
        ('swipe', x1, y1, x2, y2))
    module.top = lambda: 0
    module.time.sleep = lambda seconds: None
    module.app_icon_path = lambda package: str(FIXTURE_ICON)

    def run(frames, expect, extra=()):
        matrix = FakeMatrix(frames)
        try:
            result = module.ensure_home(matrix, expect, 'test') if expect is not None \
                else module.open_drawer(matrix, 'test')
            return matrix, result, None
        except module.Failed as error:
            return matrix, None, str(error)

    global TOUCHED
    # 1. drawer frame first: one gesture, icon found at the calibrated place
    TOUCHED = []
    matrix, entry, error = run([DRAWER], None)
    if error or 'icon' not in (entry or {}):
        failures.append('drawer-first: %s' % (error or entry))
    else:
        if abs(entry['icon']['cy'] - 1724) > 8:
            failures.append('drawer-first: cy=%s' % entry['icon']['cy'])
        if len(TOUCHED) != 1:
            failures.append('drawer-first: gestures=%d' % len(TOUCHED))

    # 2. a dock peek frame is not a drawer: retry, then accept the real drawer
    TOUCHED = []
    matrix, entry, error = run([PEEK, DRAWER], None)
    if error or 'icon' not in (entry or {}):
        failures.append('peek-retry: %s' % (error or entry))
    elif len(TOUCHED) != 2:
        failures.append('peek-retry: gestures=%d' % len(TOUCHED))

    # 3. nothing but non-drawer frames must fail loudly, after every gesture
    #    (open_drawer tries 5 gestures before giving up)
    TOUCHED = []
    matrix, entry, error = run([PEEK, PEEK, PEEK], None)
    if not error or 'icon not found' not in error:
        failures.append('drawer-fail: %s' % (error or entry))
    if len(TOUCHED) != 5:
        failures.append('drawer-fail: gestures=%d' % len(TOUCHED))

    # 4. ensure_home(1) must reject a drawer frame and accept the Home frame
    TOUCHED = []
    matrix, entry, error = run([DRAWER, HOME_ONE], 1)
    if error or entry['covers'] != 1:
        failures.append('home-from-drawer: %s' % (error or entry))
    elif entry.get('in_drawer'):
        failures.append('home-from-drawer: accepted a drawer frame')

    # 5. ensure_home(1) on an endless drawer must fail, never "0 == 0"
    TOUCHED = []
    matrix, entry, error = run([DRAWER, DRAWER, DRAWER, DRAWER, DRAWER], 1)
    if not error or 'could not reach Home' not in error:
        failures.append('home-fail: %s' % (error or entry))

    if failures:
        for failure in failures:
            print('NAV_LOGIC=FAIL|%s' % failure)
        return 1
    print('NAV_LOGIC=PASS|cases=5')
    return 0


TOUCHED = []

if __name__ == '__main__':
    sys.path.insert(0, str(HERE))
    sys.exit(main())
