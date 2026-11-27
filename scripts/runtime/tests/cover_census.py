#!/usr/bin/env python3
"""Count Sailfish Home covers on a 1080x2160 screenshot, and detect blank windows.

Sailfish draws each background application as a rounded card ("cover") on a
fixed Home grid. Lipstick exposes no queryable cover model over D-Bus: its
Qt model methods (rowCount/windowId) are listed by introspection but are not
dispatchable (verified on the phone: `UnknownMethod`), so the composited Home
frame is the only real observation. This module scores the four card borders
of every grid cell: a card is a sharp, long, straight edge against the
smooth Ambience wallpaper; an empty cell has no such step.

Grid measured from real 1080x2160 phone captures:
  card 473x749 px, columns x = 48, 561; rows y = 117 + 794*n.
Only 2 rows fit on a screen; row 2 is clipped at the bottom and not counted.

A cell is occupied when BOTH vertical borders and BOTH horizontal borders
show a step >= EDGE_THRESHOLD. Empty cells measured <= 6; a card measured
>= 170, so the threshold is far from the noise floor.

`blank` reports the "black window" check for application screenshots:
a frame is blank when almost every pixel is one colour (all black/white).

Usage:
  cover_census.py shot.png [shot2.png ...] [--json OUT] [--explain]
Exit code is 0; callers read the printed COVER_CENSUS / BLANK lines.
"""
import argparse
import json
import sys

from PIL import Image

WIDTH, HEIGHT = 1080, 2160
CARD_W, CARD_H = 473, 749
COLUMN_X = (48, 561)
ROW_Y = (117, 117 + 794)
EDGE_THRESHOLD = 10.0    # mean RGB step across the border
EDGE_PIXEL = 25.0        # one row/column counts as "on the border"
COVERAGE_THRESHOLD = 0.8  # the border must span the whole cell edge
EDGE_SEARCH = 6          # tolerate a few px of compositor scaling/rounding
BLANK_UNIFORM_FRACTION = 0.985
BLACK_LUMA = 8.0
WHITE_LUMA = 250.0


def _vertical_border(px, x, y0, y1):
    """Step magnitude and coverage of the best vertical border near x."""
    best_step, best_coverage = 0.0, 0.0
    for dx in range(-EDGE_SEARCH, EDGE_SEARCH + 1):
        total = hits = count = 0
        for y in range(y0, y1, 3):
            a = px[x + dx - 1, y]
            b = px[x + dx + 1, y]
            step = abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
            total += step
            count += 1
            if step / 3.0 > EDGE_PIXEL:
                hits += 1
        if count:
            step = total / count / 3.0
            coverage = hits / float(count)
            if coverage > best_coverage or (coverage == best_coverage and step > best_step):
                best_step, best_coverage = step, coverage
    return best_step, best_coverage


def _horizontal_border(px, y, x0, x1):
    """Step magnitude and coverage of the best horizontal border near y."""
    best_step, best_coverage = 0.0, 0.0
    for dy in range(-EDGE_SEARCH, EDGE_SEARCH + 1):
        total = hits = count = 0
        for x in range(x0, x1, 3):
            a = px[x, y + dy - 1]
            b = px[x, y + dy + 1]
            step = abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
            total += step
            count += 1
            if step / 3.0 > EDGE_PIXEL:
                hits += 1
        if count:
            step = total / count / 3.0
            coverage = hits / float(count)
            if coverage > best_coverage or (coverage == best_coverage and step > best_step):
                best_step, best_coverage = step, coverage
    return best_step, best_coverage


def cell_borders(px, x, y):
    return {
        'left': _vertical_border(px, x, y + 40, y + CARD_H - 40),
        'right': _vertical_border(px, x + CARD_W, y + 40, y + CARD_H - 40),
        'top': _horizontal_border(px, y, x + 40, x + CARD_W - 40),
        'bottom': _horizontal_border(px, y + CARD_H, x + 40, x + CARD_W - 40),
    }


def occupied(borders):
    """A card border spans the whole cell edge; drawer icon edges do not."""
    return (min(step for step, _ in borders.values()) >= EDGE_THRESHOLD
            and min(coverage for _, coverage in borders.values()) >= COVERAGE_THRESHOLD)


def blank_report(image):
    """Blank (all-black/all-white) window check, matching sd_covers.frame_stats.

    The status bar and the screenshot toast live in the top band; a real
    "black window" bug still shows a normal status bar, so the content band is
    checked separately from the full frame.
    """
    small = image.resize((180, 360))
    px = small.load()
    width, height = small.size
    # Probe: 2160 px tall; status bar/toast band 120 px, navigation bar 64 px.
    top_band = 20
    bottom_band = 10

    def region(y0, y1):
        samples = white = black = edges = 0
        buckets = {}
        for y in range(y0, y1 - 12, 4):
            for x in range(0, width - 12, 4):
                r, g, b = px[x, y]
                samples += 1
                luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
                if luma >= 250:
                    white += 1
                if luma <= 8:
                    black += 1
                r2, g2, b2 = px[x + 8, y]
                if abs(r - r2) + abs(g - g2) + abs(b - b2) > 60:
                    edges += 1
                key = (r >> 6, g >> 6, b >> 6)
                buckets[key] = buckets.get(key, 0) + 1
        if not samples:
            return 1.0, 1.0, 0.0, 0.0
        return (max(buckets.values()) / float(samples), white / float(samples),
                black / float(samples), edges / float(samples))

    dominant, white_fraction, black_fraction, edge_fraction = region(0, height)
    c_dominant, c_white, c_black, c_edges = region(top_band, height - bottom_band)
    blank = ((c_dominant >= 0.985 and (c_white >= 0.95 or c_black >= 0.95))
             or (dominant >= 0.985 and (white_fraction >= 0.95 or black_fraction >= 0.95)))
    return {'blank': blank,
            'dominant_fraction': round(dominant, 4),
            'white_fraction': round(white_fraction, 3),
            'black_fraction': round(black_fraction, 3),
            'edge_fraction': round(edge_fraction, 4),
            'content_dominant_fraction': round(c_dominant, 4),
            'content_white_fraction': round(c_white, 3),
            'content_black_fraction': round(c_black, 3),
            'content_edge_fraction': round(c_edges, 4),
            'low_content': (c_white >= 0.90 or c_black >= 0.90) and c_edges < 0.004}


def census(path, explain=False):
    image = Image.open(path).convert('RGB')
    if image.size != (WIDTH, HEIGHT):
        raise SystemExit('%s: unexpected screenshot size %s' % (path, image.size))
    px = image.load()
    cells = []
    for row, y in enumerate(ROW_Y):
        if y + CARD_H > HEIGHT - 40:
            continue
        for column, x in enumerate(COLUMN_X):
            borders = cell_borders(px, x, y)
            cells.append({'cell': 'r%dc%d' % (row, column), 'row': row,
                          'column': column, 'x': x, 'y': y,
                          'borders': {k: {'step': round(s, 1), 'coverage': round(c, 2)}
                                      for k, (s, c) in borders.items()},
                          'occupied': occupied(borders)})
    if explain:
        for cell in cells:
            print('%s x=%d y=%d occupied=%s %s' % (
                cell['cell'], cell['x'], cell['y'], cell['occupied'], cell['borders']))
    blank = blank_report(image)
    return {'image': str(path),
            'cover_count': sum(1 for cell in cells if cell['occupied']),
            'cells': cells,
            'blank': blank['blank'],
            'blank_detail': blank}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('images', nargs='+')
    parser.add_argument('--json', default=None)
    parser.add_argument('--explain', action='store_true')
    args = parser.parse_args()
    results = [census(path, args.explain) for path in args.images]
    for item in results:
        print('COVER_CENSUS=%d|image=%s' % (item['cover_count'], item['image']))
        print('BLANK_CHECK=%s|image=%s|dominant=%s|white=%s|black=%s|edges=%s' % (
            'blank' if item['blank'] else 'content',
            item['image'], item['blank_detail']['dominant_fraction'],
            item['blank_detail']['white_fraction'], item['blank_detail']['black_fraction'],
            item['blank_detail']['edge_fraction']))
    if args.json:
        with open(args.json, 'w') as stream:
            json.dump(results, stream, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())
