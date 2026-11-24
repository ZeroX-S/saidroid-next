#!/usr/bin/env python3
"""Pure-stdlib Sailfish Home cover census and window-frame checks.

This module deliberately has no third-party dependency: the phone has no PIL
and the integration matrix must count covers on the phone itself. The
independent PIL implementation lives in cover_census.py and is used by
run-matrix.py as a cross-check of the same screenshots.

Sailfish Home grid measured from real 1080x2160 captures:
  cover card 473x749 px, columns x = 48, 561, rows y = 117 + 794*n.
A cell is occupied when both vertical borders and both horizontal borders
show a sharp step against the smooth Ambience wallpaper AND that step must run
along the whole cell edge. Empty cells measure step <= 6 and coverage <= 0.02;
a real card measures step >= 170 with coverage 1.00; the app drawer reaches
step <= 47 with coverage <= 0.40, so both thresholds sit far from every
measured class.
"""
import struct
import zlib
from pathlib import Path

CARD_W, CARD_H = 473, 749
COLUMN_X = (48, 561)
ROW_Y = (117, 117 + 794)
EDGE_THRESHOLD = 10.0    # mean step across the border, RGB levels
EDGE_PIXEL = 25.0        # a single row/pixel counts as "on the border"
COVERAGE_THRESHOLD = 0.8  # the border must span the whole cell edge
# Status bar + screenshot toast band, navigation bar: excluded from content checks.
TOP_BAND = 120
BOTTOM_BAND = 64
EDGE_SEARCH = 6


def png_rows(path):
    """Decode a non-interlaced 8-bit RGBA PNG into a list of bytearrays."""
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG: %s' % path)
    position = 8
    idat = []
    width = height = None
    while position < len(data):
        length = struct.unpack('>I', data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        chunk = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b'IHDR':
            width, height, bitdepth, colortype, _, _, interlace = struct.unpack(
                '>IIBBBBB', chunk)
            if bitdepth != 8 or colortype not in (2, 6) or interlace != 0:
                raise ValueError('unsupported PNG format (%d/%d/%d)'
                                 % (bitdepth, colortype, interlace))
        elif kind == b'IDAT':
            idat.append(chunk)
        elif kind == b'IEND':
            break
    if width is None:
        raise ValueError('missing IHDR: %s' % path)
    raw = zlib.decompress(b''.join(idat))
    channels = 4 if colortype == 6 else 3
    stride = width * channels
    previous = bytearray(stride)
    rows = []
    offset = 0
    for _ in range(height):
        filt = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        if filt == 0:
            pass
        elif filt == 1:
            for i in range(4, stride):
                line[i] = (line[i] + line[i - 4]) & 255
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 255
        elif filt == 3:
            for i in range(stride):
                left = line[i - 4] if i >= 4 else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 255
        elif filt == 4:
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                b = previous[i]
                c = previous[i - 4] if i >= 4 else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                predictor = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + predictor) & 255
        else:
            raise ValueError('unknown PNG filter %d' % filt)
        rows.append(line)
        previous = line
    if channels == 3:
        rgba = []
        for line in rows:
            out = bytearray(width * 4)
            for i in range(width):
                out[4 * i] = line[3 * i]
                out[4 * i + 1] = line[3 * i + 1]
                out[4 * i + 2] = line[3 * i + 2]
                out[4 * i + 3] = 255
            rgba.append(out)
        rows = rgba
    return width, height, rows


def px(rows, x, y):
    line = rows[y]
    offset = x * 4
    return line[offset], line[offset + 1], line[offset + 2]


def _vertical_border(rows, x, y0, y1):
    """Step magnitude and coverage of the best vertical border near x.

    A real cover border is a sharp step for the whole cell height; drawer
    icons also make steps but only over short icon edges, so coverage is what
    separates a card from the app grid.
    """
    best_step, best_coverage = 0.0, 0.0
    for dx in range(-EDGE_SEARCH, EDGE_SEARCH + 1):
        total = hits = count = 0
        for y in range(y0, y1, 3):
            a = px(rows, x + dx - 1, y)
            b = px(rows, x + dx + 1, y)
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


def _horizontal_border(rows, y, x0, x1):
    """Step magnitude and coverage of the best horizontal border near y."""
    best_step, best_coverage = 0.0, 0.0
    for dy in range(-EDGE_SEARCH, EDGE_SEARCH + 1):
        total = hits = count = 0
        for x in range(x0, x1, 3):
            a = px(rows, x, y + dy - 1)
            b = px(rows, x, y + dy + 1)
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


def _census_rows(rows, width, height):
    """Cover census over already-decoded rows: (count, cells)."""
    if (width, height) != (1080, 2160):
        raise ValueError('unexpected screenshot size %s' % ((width, height),))
    count = 0
    cells = {}
    for row, y in enumerate(ROW_Y):
        if y + CARD_H > height - 40:
            continue
        for column, x in enumerate(COLUMN_X):
            borders = {
                'left': _vertical_border(rows, x, y + 40, y + CARD_H - 40),
                'right': _vertical_border(rows, x + CARD_W, y + 40, y + CARD_H - 40),
                'top': _horizontal_border(rows, y, x + 40, x + CARD_W - 40),
                'bottom': _horizontal_border(rows, y + CARD_H, x + 40, x + CARD_W - 40),
            }
            # A card border runs the whole cell edge (coverage 1.00 measured);
            # drawer icon edges only reach 0.40, app frames 0.00.
            occupied = (min(step for step, _ in borders.values()) >= EDGE_THRESHOLD
                        and min(coverage for _, coverage in borders.values())
                        >= COVERAGE_THRESHOLD)
            cells['r%dc%d' % (row, column)] = dict(
                occupied=occupied,
                **{name: {'step': round(step, 1), 'coverage': round(coverage, 2)}
                   for name, (step, coverage) in borders.items()})
            count += 1 if occupied else 0
    return count, cells


def _region_stats(rows, width, y0, y1):
    """Flat-colour / content density over one horizontal band."""
    samples = white = black = edges = 0
    buckets = {}
    for y in range(y0, y1, 12):
        for x in range(0, width - 12, 12):
            r, g, b = px(rows, x, y)
            samples += 1
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if luma >= 250:
                white += 1
            if luma <= 8:
                black += 1
            r2, g2, b2 = px(rows, x + 8, y)
            if abs(r - r2) + abs(g - g2) + abs(b - b2) > 60:
                edges += 1
            key = (r >> 6, g >> 6, b >> 6)
            buckets[key] = buckets.get(key, 0) + 1
    if not samples:
        return {'dominant': 1.0, 'white': 1.0, 'black': 0.0, 'edges': 0.0}
    return {'dominant': max(buckets.values()) / float(samples),
            'white': white / float(samples),
            'black': black / float(samples),
            'edges': edges / float(samples)}


def _stats_rows(rows, width, height):
    """Window-frame check: blank (all-black/all-white) and content density.

    A blank host window is a single flat colour (the r58 black-window bug).
    Real application UI always contains edges (text, buttons, images).

    The status bar (clock, battery) and the "screenshot taken" notification
    toast live in the top band, and the navigation bar in the bottom band;
    both are excluded for the content check so a black window with a normal
    status bar is still detected as blank.
    """
    top = _region_stats(rows, width, TOP_BAND, height - BOTTOM_BAND)
    full = _region_stats(rows, width, 0, height)
    blank = ((top['dominant'] >= 0.985 and (top['white'] >= 0.95 or top['black'] >= 0.95))
             or (full['dominant'] >= 0.985
                 and (full['white'] >= 0.95 or full['black'] >= 0.95)))
    low_content = ((top['white'] >= 0.90 or top['black'] >= 0.90)
                   and top['edges'] < 0.004)
    return {'blank': blank,
            'dominant_fraction': round(full['dominant'], 4),
            'white_fraction': round(full['white'], 3),
            'black_fraction': round(full['black'], 3),
            'edge_fraction': round(full['edges'], 4),
            'content_dominant_fraction': round(top['dominant'], 4),
            'content_white_fraction': round(top['white'], 3),
            'content_black_fraction': round(top['black'], 3),
            'content_edge_fraction': round(top['edges'], 4),
            'low_content': low_content}


def frame_diff(path_a, path_b, top_skip=200, threshold=24):
    """Fraction of differing samples between two frames of the same size.

    The status-bar band is skipped because the clock and the "screenshot taken"
    banner change between any two captures; the application content is below.
    """
    width_a, height_a, rows_a = png_rows(path_a)
    width_b, height_b, rows_b = png_rows(path_b)
    if (width_a, height_a) != (width_b, height_b):
        raise ValueError('frame sizes differ: %s %s' % ((width_a, height_a),
                                                       (width_b, height_b)))
    samples = different = 0
    for y in range(top_skip, height_a, 8):
        for x in range(0, width_a, 8):
            a = px(rows_a, x, y)
            b = px(rows_b, x, y)
            samples += 1
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) > threshold:
                different += 1
    return different / float(samples)


def cover_count(path):
    """Count Sailfish Home cover cards; a non-Home screen yields 0."""
    width, height, rows = png_rows(path)
    return _census_rows(rows, width, height)


def frame_stats(path):
    """Blank/all-white window check for one screenshot."""
    width, height, rows = png_rows(path)
    return _stats_rows(rows, width, height)


def analyze(path):
    """One decode for both the cover census and the frame check."""
    width, height, rows = png_rows(path)
    count, cells = _census_rows(rows, width, height)
    return count, cells, _stats_rows(rows, width, height)

# --------------------------------------------------------------------------
# Icon localisation: find an app icon inside a drawer frame.
# Pure stdlib (the phone has no PIL) and geometry-free: no hardcoded cell
# coordinates, so installing another app can never make a tap land on wallpaper.
# --------------------------------------------------------------------------
def png_px(rows, x, y):
    offset = x * 4
    line = rows[y]
    return line[offset], line[offset + 1], line[offset + 2], line[offset + 3]


def _icon_points(icon_path, size, samples=6):
    """Sample the opaque part of an icon at `samples` x `samples` positions."""
    width, height, rows = png_rows(str(icon_path))
    side = min(width, height)
    ox = (width - side) // 2
    oy = (height - side) // 2
    points = []
    for cy in range(samples):
        for cx in range(samples):
            u = (cx + 0.5) / samples
            v = (cy + 0.5) / samples
            r, g, b, a = png_px(rows, ox + int(u * side), oy + int(v * side))
            if a >= 200:
                points.append((u, v, r, g, b))
    return points


def _match_at(rows, left, top, size, points):
    total = 0
    for u, v, r, g, b in points:
        fr, fg, fb, _ = png_px(rows, left + int(u * size), top + int(v * size))
        total += abs(fr - r) + abs(fg - g) + abs(fb - b)
    return 1.0 - total / (len(points) * 3 * 255.0)


def _scan(rows, width, height, size, points, step, left=None, top=None,
          span=None):
    best = None
    if left is None:
        xs = range(0, width - size, step)
        ys = range(0, height - size, step)
    else:
        xs = range(max(0, left - span), min(width - size, left + span) + 1, step)
        ys = range(max(0, top - span), min(height - size, top + span) + 1, step)
    for y in ys:
        for x in xs:
            score = _match_at(rows, x, y, size, points)
            if best is None or score > best[0]:
                best = (score, x, y)
    return best


def find_icon(frame_path, icon_path, sizes=(128, 140, 152), samples=6, step=24):
    """Best match of an icon inside a frame: {'x','y','size','score','cx','cy'}."""
    width, height, rows = png_rows(str(frame_path))
    best = None
    for size in sizes:
        coarse = _icon_points(icon_path, size, samples=4)
        hit = _scan(rows, width, height, size, coarse, step)
        if hit is None:
            continue
        points = _icon_points(icon_path, size, samples=samples)
        refined = _scan(rows, width, height, size, points, 4, hit[1], hit[2],
                        span=step)
        if refined and (best is None or refined[0] > best['score']):
            score, x, y = refined
            best = {'x': x, 'y': y, 'size': size, 'score': score,
                    'cx': x + size // 2, 'cy': y + size // 2}
    return best


def find_icon_center(frame_path, icon_path, threshold=0.86):
    """Return (centre_x, centre_y, match) when the icon is confidently present."""
    match = find_icon(frame_path, icon_path)
    if match is None or match['score'] < threshold:
        return None
    return match['cx'], match['cy'], match
