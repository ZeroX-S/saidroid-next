#!/usr/bin/env python3
"""End-to-end WebView double-buffered SHM frame transport & pipe fallback test."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[3]

SHIMS_JAVA = {
    'android/os/Process.java': r'''
package android.os;
public class Process {
    public static int myUid() { return Integer.getInteger("sd.test.uid", 1000); }
    public static int myPid() { return (int) (ProcessHandle.current().pid() & 0x7fffffff); }
}
''',
    'android/os/Looper.java': r'''
package android.os;
public final class Looper {
    private static final Looper MAIN = new Looper();
    public static Looper getMainLooper() { return MAIN; }
}
''',
    'android/os/Handler.java': r'''
package android.os;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
public class Handler {
    private static final ExecutorService UI = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "sd-test-ui");
        t.setDaemon(true);
        return t;
    });
    public Handler(Looper looper) {}
    public boolean post(Runnable r) { UI.execute(r); return true; }
}
''',
    'android/graphics/Bitmap.java': r'''
package android.graphics;
import java.io.OutputStream;
import java.nio.Buffer;
import java.nio.ByteBuffer;
public final class Bitmap {
    public enum Config { ARGB_8888 }
    public enum CompressFormat { PNG }
    private final int width, height;
    private final byte[] store;
    private boolean recycled;
    private Bitmap(int w, int h) { this.width = w; this.height = h; this.store = new byte[w * h * 4]; }
    public static Bitmap createBitmap(int w, int h, Config cfg) { return new Bitmap(w, h); }
    public int getWidth() { return width; }
    public int getHeight() { return height; }
    public void recycle() { recycled = true; }
    public boolean isRecycled() { return recycled; }
    public void copyPixelsFromBuffer(Buffer src) {
        ByteBuffer bb = (ByteBuffer) src;
        ByteBuffer view = bb.duplicate();
        view.get(store, 0, width * height * 4);
    }
    public byte[] rawBytes() { return store.clone(); }
    public boolean compress(CompressFormat fmt, int q, OutputStream out) { return true; }
}
''',
}

HELPER_CPP = r'''
#include "native/host/third_party/json.hpp"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

using Json = nlohmann::json;
static constexpr size_t kMaxFrameBytes = 2160ULL * 4096ULL * 4ULL;

static bool write_all(int fd, const void *buf, size_t len) {
    const auto *p = static_cast<const unsigned char *>(buf);
    while (len > 0) {
        ssize_t n = ::write(fd, p, len);
        if (n <= 0) return false;
        p += n;
        len -= size_t(n);
    }
    return true;
}

static bool read_all(int fd, void *buf, size_t len) {
    auto *p = static_cast<unsigned char *>(buf);
    while (len > 0) {
        ssize_t n = ::read(fd, p, len);
        if (n <= 0) return false;
        p += n;
        len -= size_t(n);
    }
    return true;
}

static void send_packet(const Json &obj, const unsigned char *payload = nullptr, size_t payload_len = 0) {
    std::string text = obj.dump();
    uint32_t len = uint32_t(text.size());
    unsigned char hdr[4] = {
        static_cast<unsigned char>(len >> 24), static_cast<unsigned char>(len >> 16),
        static_cast<unsigned char>(len >> 8), static_cast<unsigned char>(len)
    };
    if (!write_all(STDOUT_FILENO, hdr, 4) || !write_all(STDOUT_FILENO, text.data(), text.size()))
        std::exit(20);
    if (payload && payload_len > 0 && !write_all(STDOUT_FILENO, payload, payload_len))
        std::exit(21);
}

static Json read_command() {
    unsigned char hdr[4];
    if (!read_all(STDIN_FILENO, hdr, 4)) std::exit(0);
    uint32_t len = (uint32_t(hdr[0]) << 24) | (uint32_t(hdr[1]) << 16) |
                   (uint32_t(hdr[2]) << 8) | uint32_t(hdr[3]);
    std::string body(len, '\0');
    if (!read_all(STDIN_FILENO, body.data(), len)) std::exit(0);
    return Json::parse(body);
}

static void fill_pattern(unsigned char *dst, int w, int h, int seq) {
    for (int i = 0; i < w * h; ++i) {
        dst[i * 4 + 0] = static_cast<unsigned char>((i + seq * 17) & 0xFF);
        dst[i * 4 + 1] = static_cast<unsigned char>((i * 3 + seq * 31) & 0xFF);
        dst[i * 4 + 2] = static_cast<unsigned char>((i * 7 + seq * 13) & 0xFF);
        dst[i * 4 + 3] = 0xFF;
    }
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    int w = std::atoi(argv[1]);
    int h = std::atoi(argv[2]);
    size_t frame_bytes = size_t(w) * size_t(h) * 4u;

    unsigned char *shm_base = nullptr;
    size_t expected_shm = kMaxFrameBytes * 2u;
    if (const char *shm_path = std::getenv("SAILDROID_WEBVIEW_SHM_PATH")) {
        int fd = ::open(shm_path, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
        struct stat st{};
        if (fd >= 0 && ::fstat(fd, &st) == 0 && S_ISREG(st.st_mode) &&
            st.st_uid == ::getuid() && (st.st_mode & 077) == 0 && size_t(st.st_size) >= expected_shm) {
            void *mapped = ::mmap(nullptr, expected_shm, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
            if (mapped != MAP_FAILED) shm_base = static_cast<unsigned char *>(mapped);
        }
        if (fd >= 0) ::close(fd);
    }

    send_packet({{"event", "ready"}, {"protocol", 1}, {"shm", shm_base != nullptr}});

    std::vector<unsigned char> scratch(frame_bytes);
    for (int seq = 1; seq <= 3; ++seq) {
        fill_pattern(scratch.data(), w, h, seq);
        if (shm_base) {
            int slot = seq & 1;
            std::memcpy(shm_base + size_t(slot) * kMaxFrameBytes, scratch.data(), frame_bytes);
            send_packet({
                {"event", "frame"}, {"seq", seq}, {"width", w}, {"height", h},
                {"bytes", frame_bytes}, {"format", "shm_rgba8888"}, {"slot", slot}
            });
        } else {
            send_packet({
                {"event", "frame"}, {"seq", seq}, {"width", w}, {"height", h},
                {"bytes", frame_bytes}, {"format", "rgba8888"}
            }, scratch.data(), frame_bytes);
        }
        for (;;) {
            Json cmd = read_command();
            if (cmd.value("op", "") == "frame_ack" && cmd.value("seq", 0) == seq) break;
        }
    }
    for (;;) {
        Json cmd = read_command();
        if (cmd.value("op", "") == "quit") break;
    }
    if (shm_base) ::munmap(shm_base, expected_shm);
    return 0;
}
'''

PROBE_JAVA = r'''
import android.graphics.Bitmap;
import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

public final class WebViewShmProbe {
    static void require(boolean ok, String msg) {
        if (!ok) throw new AssertionError(msg);
    }

    static void verifyPattern(byte[] actual, int w, int h, int seq) {
        require(actual.length == w * h * 4, "Unexpected pixel array size: " + actual.length);
        for (int i = 0; i < w * h; i++) {
            int r = actual[i * 4] & 0xFF;
            int g = actual[i * 4 + 1] & 0xFF;
            int b = actual[i * 4 + 2] & 0xFF;
            int a = actual[i * 4 + 3] & 0xFF;
            if (r != ((i + seq * 17) & 0xFF) ||
                g != ((i * 3 + seq * 31) & 0xFF) ||
                b != ((i * 7 + seq * 13) & 0xFF) ||
                a != 0xFF) {
                throw new AssertionError("Pixel mismatch at pixel=" + i + " seq=" + seq);
            }
        }
    }

    public static void main(String[] args) throws Throwable {
        File dir = new File(args[0]);
        boolean expectShm = Boolean.parseBoolean(args[1]);
        int w = 96, h = 64;

        AtomicBoolean readyShm = new AtomicBoolean(false);
        AtomicReference<String> failure = new AtomicReference<String>();
        CountDownLatch framesDone = new CountDownLatch(3);

        SdWebEngine engine = new SdWebEngine(dir, w, h, new SdWebEngine.Listener() {
            @Override
            public void event(JSONObject ev) {
                if ("ready".equals(ev.optString("event"))) {
                    readyShm.set(ev.optBoolean("shm", false));
                }
            }

            @Override
            public void frame(Bitmap bitmap, long sequence) {
                try {
                    verifyPattern(bitmap.rawBytes(), w, h, (int) sequence);
                    framesDone.countDown();
                } catch (Throwable t) {
                    failure.compareAndSet(null, t.toString());
                    while (framesDone.getCount() > 0) framesDone.countDown();
                }
            }

            @Override
            public void failed(String reason) {
                failure.compareAndSet(null, "failed:" + reason);
                while (framesDone.getCount() > 0) framesDone.countDown();
            }
        });

        require(framesDone.await(10, TimeUnit.SECONDS), "Timed out waiting for 3 WebView frames");
        if (failure.get() != null) throw new AssertionError(failure.get());
        require(readyShm.get() == expectShm, "Expected shm=" + expectShm + " but got " + readyShm.get());

        engine.send(new JSONObject().put("op", "quit"));
        engine.close();

        File hostDir = new File(dir, "webview-host");
        File[] leftovers = hostDir.listFiles((d, name) -> name.startsWith("webview-shm-"));
        require(leftovers == null || leftovers.length == 0, "Leftover WebView SHM file after close()");
        System.out.println("WEBVIEW_SHM_CASE=PASS|shm=" + expectShm);
    }
}
'''


def resolve_jdk() -> Path:
    if os.environ.get('JAVA_HOME'):
        return Path(os.environ['JAVA_HOME'])
    javac = shutil.which('javac')
    if not javac:
        raise SystemExit('ERROR: javac not found')
    return Path(javac).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-jar', type=Path, required=True)
    args = parser.parse_args()

    jdk = resolve_jdk()
    javac = jdk / 'bin/javac'
    java = jdk / 'bin/java'
    uid = os.getuid()

    with tempfile.TemporaryDirectory(prefix='sd-webview-shm-') as tmp:
        work = Path(tmp)
        helper_cpp = work / 'mock-webview-helper.cpp'
        helper_bin = work / 'mock-webview-helper'
        helper_cpp.write_text(HELPER_CPP, encoding='utf-8')
        subprocess.run([
            'g++', '-std=c++17', '-O2', '-Wall', '-Wextra',
            f'-I{REPO}',
            str(helper_cpp),
            '-o', str(helper_bin),
        ], check=True)
        os.chmod(helper_bin, 0o755)

        src = work / 'src'
        out = work / 'classes'
        out.mkdir()
        java_files = []
        for rel, content in SHIMS_JAVA.items():
            target = src / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
            java_files.append(str(target))
        probe_file = src / 'WebViewShmProbe.java'
        probe_file.write_text(PROBE_JAVA, encoding='utf-8')
        java_files.append(str(probe_file))
        java_files.append(str(REPO / 'scripts/device/SdWebEngine.java'))

        subprocess.run([
            str(javac), '-nowarn', '--release', '11',
            '-cp', str(args.android_jar),
            '-d', str(out),
            *java_files,
        ], check=True)

        # Case 1: Double-buffered SHM zero-pipe-copy path (slots 1, 0, 1).
        shm_dir = work / 'run-shm'
        shm_dir.mkdir()
        env_shm = dict(os.environ, SAILDROID_WEBVIEW_HELPER=str(helper_bin))
        env_shm.pop('SAILDROID_NO_WEBVIEW_SHM', None)
        res_shm = subprocess.run([
            str(java), f'-Dsd.test.uid={uid}',
            '-cp', f'{out}:{args.android_jar}',
            'WebViewShmProbe', str(shm_dir), 'true',
        ], env=env_shm, capture_output=True, text=True, timeout=20)
        if res_shm.returncode != 0:
            raise RuntimeError(f'SHM mode failed:\nSTDOUT:\n{res_shm.stdout}\nSTDERR:\n{res_shm.stderr}')
        assert 'WEBVIEW_SHM_CASE=PASS|shm=true' in res_shm.stdout, res_shm.stdout

        # Case 2: Pipe rgba8888 fallback when SAILDROID_NO_WEBVIEW_SHM=1.
        pipe_dir = work / 'run-pipe'
        pipe_dir.mkdir()
        env_pipe = dict(os.environ, SAILDROID_WEBVIEW_HELPER=str(helper_bin), SAILDROID_NO_WEBVIEW_SHM='1')
        res_pipe = subprocess.run([
            str(java), f'-Dsd.test.uid={uid}',
            '-cp', f'{out}:{args.android_jar}',
            'WebViewShmProbe', str(pipe_dir), 'false',
        ], env=env_pipe, capture_output=True, text=True, timeout=20)
        if res_pipe.returncode != 0:
            raise RuntimeError(f'Pipe fallback mode failed:\nSTDOUT:\n{res_pipe.stdout}\nSTDERR:\n{res_pipe.stderr}')
        assert 'WEBVIEW_SHM_CASE=PASS|shm=false' in res_pipe.stdout, res_pipe.stdout

        print('WEBVIEW_SHM=PASS|modes=shm_rgba8888,rgba8888_fallback|frames_verified=6')


if __name__ == '__main__':
    main()
