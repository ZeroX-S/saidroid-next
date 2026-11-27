#!/usr/bin/env python3
"""Calibrate the cover census against screenshots with known truth.

Every row carries an expected value measured by hand from the screenshot, so a
threshold change that breaks a previously correct count fails loudly instead of
silently shifting the I3 criterion.

  python3 calibrate-census.py            # table + PASS/FAIL per image
  python3 calibrate-census.py --require  # exit 1 on any mismatch
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cover_census  # noqa: E402  PIL, independent implementation
import sd_covers  # noqa: E402  stdlib, runs on the phone

REPO = HERE.parents[2]
ROWS = [
    # image, expected covers, expected blank, why
    ('build/screens/int-home-covers2.png', 1, False, 'Home, manager cover only'),
    ('build/codex-api29/screens/two-cards-r23.png', 2, False, 'Home, QQ + lifecycle card'),
    ('build/codex-api29/screens/multi-shell-r18.png', 3, False, 'Home, three covers'),
    ('build/screens/int-home-manager2.png', 0, False, 'app drawer (icons, no cards)'),
    ('build/codex-api29/screens/r49-manager-exec-one-cover.png', 1, False, 'Home, manager cover'),
    ('build/codex-api29/screens/r47-actual-drawer.png', 0, False, 'app drawer'),
    ('build/codex-api29/screens/r45-user-duplicate-cover.png', 0, False, 'QQ login page'),
    ('build/codex-api29/screens/r45-qq-delivery.png', 0, False, 'QQ LoginActivity'),
    ('build/screens/int-calib-01.png', 0, True, 'flat white frame (blank host window)'),
    ('build/screens/int-calib-03.png', 0, True, 'white frame + screenshot toast'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--require', action='store_true')
    args = parser.parse_args()
    failures = 0
    print('%-58s %-6s %-6s %-6s %-6s %-6s %s'
          % ('image', 'want', 'dev', 'pil', 'blank%', 'blankP', 'why'))
    for name, want_covers, want_blank, why in ROWS:
        path = REPO / name
        if not path.exists():
            print('%-58s MISSING' % name)
            failures += 1
            continue
        covers, _, stats = sd_covers.analyze(path)
        reference = cover_census.census(path)
        ok = (covers == want_covers and reference['cover_count'] == want_covers
              and bool(stats['blank']) == want_blank
              and bool(reference['blank']) == want_blank)
        failures += 0 if ok else 1
        print('%-58s %-6d %-6d %-6d %-6s %-6s %s%s'
              % (name.split('/')[-1], want_covers, covers, reference['cover_count'],
                 stats['blank'], reference['blank'], why, '' if ok else '   <-- MISMATCH'))
    print('CALIBRATION=%s|images=%d|mismatches=%d'
          % ('PASS' if not failures else 'FAIL', len(ROWS), failures))
    return 0 if not failures or not args.require else 1


if __name__ == '__main__':
    sys.exit(main())
