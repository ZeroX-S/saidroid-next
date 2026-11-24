#!/usr/bin/env python3
"""Cross-compile hot native paths for AArch64 and verify under qemu-aarch64-static."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[1]


def extract_nv21_helpers() -> str:
    source = (REPO / 'native/media/droid-camera/camera-host.cpp').read_text(encoding='utf-8')
    match = re.search(
        r'(static inline unsigned char clamp_u8\(.*?static void convert_nv21_to_rgba\(.*?\n \}\n)',
        source,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError('Failed to extract convert_nv21_to_rgba from camera-host.cpp')
    return match.group(1)


AARCH64_HARNESS_TEMPLATE = r'''
#include <algorithm>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include "native/webview/qt-helper/include/webview-geometry.h"
#include "native/host/audio-connection.hpp"

#if !defined(__aarch64__)
#error "Expected AArch64 target architecture"
#endif

struct Nv21Holder {
__NV21_HELPERS__
};

static void reference_nv21_to_rgba(
    const unsigned char *src, int src_w, int src_h,
    unsigned char *dst_base, int dst_stride, int rows, int cols,
    int angle, bool mirrored) {
    const unsigned char *uv_plane = src + size_t(src_w) * src_h;
    int full_w = (angle % 180) ? src_h : src_w;
    for (int y = 0; y < rows; ++y) {
        for (int x = 0; x < cols; ++x) {
            int dx = mirrored ? (full_w - 1 - x) : x;
            int sx = dx, sy = y;
            if (angle == 90) { sx = y; sy = src_h - 1 - dx; }
            else if (angle == 180) { sx = src_w - 1 - dx; sy = src_h - 1 - y; }
            else if (angle == 270) { sx = src_w - 1 - y; sy = dx; }
            int yy = int(src[size_t(sy) * src_w + sx]) - 16;
            const unsigned char *uv = uv_plane + size_t(sy >> 1) * src_w + (sx & ~1);
            int v = int(uv[0]) - 128;
            int u = int(uv[1]) - 128;
            int r = (298 * yy + 409 * v + 128) >> 8;
            int g = (298 * yy - 100 * u - 208 * v + 128) >> 8;
            int b = (298 * yy + 516 * u + 128) >> 8;
            unsigned char *out = dst_base + (size_t(y) * dst_stride + x) * 4;
            out[0] = static_cast<unsigned char>(std::clamp(r, 0, 255));
            out[1] = static_cast<unsigned char>(std::clamp(g, 0, 255));
            out[2] = static_cast<unsigned char>(std::clamp(b, 0, 255));
            out[3] = 255;
        }
    }
}

int main() {
    // 1. Camera NV21 -> RGBA bit-exactness across all rotations, mirror modes, and padded strides.
    const int src_w = 64, src_h = 48;
    std::vector<unsigned char> nv21(size_t(src_w) * src_h * 3 / 2);
    for (size_t i = 0; i < nv21.size(); ++i) {
        nv21[i] = static_cast<unsigned char>((i * 73 + 19) & 0xFF);
    }
    const int angles[] = {0, 90, 180, 270};
    for (int angle : angles) {
        for (bool mirror : {false, true}) {
            int out_w = (angle % 180) ? src_h : src_w;
            int out_h = (angle % 180) ? src_w : src_h;
            int stride = out_w + 7;
            int rows = out_h - 2;
            int cols = out_w - 3;
            std::vector<unsigned char> expected(size_t(stride) * out_h * 4, 0x5A);
            std::vector<unsigned char> actual(size_t(stride) * out_h * 4, 0x5A);
            reference_nv21_to_rgba(nv21.data(), src_w, src_h, expected.data(), stride, rows, cols, angle, mirror);
            Nv21Holder::convert_nv21_to_rgba(nv21.data(), src_w, src_h, actual.data(), stride, rows, cols, angle, mirror);
            assert(expected == actual);
        }
    }

    // 2. WebView touch coordinate mapping on AArch64 FP64.
    assert(std::abs(sd_webview_coordinate(540.0, 1080, 720) - 360.0) < 1e-9);
    assert(sd_webview_coordinate(123.5, 0, 900) == 123.5);
    assert(sd_webview_coordinate(-25.0, 100, 200) == -50.0);

    // 3. Audio endpoint & port routing classification on AArch64.
    assert(sd_audio_connection::port_device("output-wired_headset", false) == 4u);
    assert(sd_audio_connection::port_device("input-wired_headset", true) == 0x80000010u);
    assert(sd_audio_connection::endpoint_device("bluez5", "a2dp_sink", "a2dp_sink", false) == 0x80u);
    assert(sd_audio_connection::endpoint_device("usb", "", "", false) == 0x4000u);
    assert(sd_audio_connection::device_matches(0x4000u, 0x4000u));

    std::printf("AARCH64_CONTRACTS=PASS|arch=aarch64|nv21_modes=8|webview_coord=ok|audio_routes=ok\n");
    return 0;
}
'''


def main() -> None:
    cxx = shutil.which('aarch64-linux-gnu-g++')
    qemu = shutil.which('qemu-aarch64-static') or shutil.which('qemu-aarch64')
    readelf = shutil.which('aarch64-linux-gnu-readelf') or shutil.which('readelf')
    if not cxx or not qemu:
        raise SystemExit('ERROR: aarch64-linux-gnu-g++ and qemu-aarch64-static are required')

    nv21_code = extract_nv21_helpers()
    source_code = AARCH64_HARNESS_TEMPLATE.replace('__NV21_HELPERS__', nv21_code)

    with tempfile.TemporaryDirectory(prefix='sd-aarch64-test-') as tmp:
        work = Path(tmp)
        cpp_path = work / 'aarch64-contracts.cpp'
        bin_path = work / 'aarch64-contracts'
        cpp_path.write_text(source_code, encoding='utf-8')
        subprocess.run([
            cxx, '-std=c++17', '-O2', '-Wall', '-Wextra', '-static',
            f'-I{REPO}',
            str(cpp_path),
            '-o', str(bin_path),
        ], check=True)
        if readelf:
            hdr = subprocess.check_output([readelf, '-h', str(bin_path)], text=True)
            assert 'AArch64' in hdr, hdr
        out = subprocess.check_output([qemu, str(bin_path)], text=True, timeout=15)
        assert 'AARCH64_CONTRACTS=PASS|' in out, out
        print(out.strip())


if __name__ == '__main__':
    main()
