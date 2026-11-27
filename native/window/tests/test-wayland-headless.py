#!/usr/bin/env python3
"""Headless Weston Wayland compositor + libsdwindow.so JNI direct-SHM & cached jmethodID test."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile
import time


REPO = Path(__file__).resolve().parents[3]

VM_RUNTIME_JAVA = r'''
package dalvik.system;
public class VMRuntime {
    private static final VMRuntime runtime = new VMRuntime();
    public static VMRuntime getRuntime() { return runtime; }
    public boolean is64Bit() { return true; }
    public Object newUnpaddedArray(Class<?> type, int count) {
        return java.lang.reflect.Array.newInstance(type, count);
    }
}
'''

CLOSE_GUARD_JAVA = r'''
package dalvik.system;
public final class CloseGuard {
    private static final CloseGuard NOOP = new CloseGuard();
    public static CloseGuard get() { return NOOP; }
    public void open(String closer) {}
    public void close() {}
    public void warnIfOpen() {}
}
'''

HANDLER_SHIM_JAVA = r'''
package android.os;
public class Handler {
    public Handler() {}
    public Handler(Looper looper) {}
    public boolean sendMessage(Message msg) { return true; }
    public boolean post(Runnable r) { if (r != null) r.run(); return true; }
    public boolean postDelayed(Runnable r, long delay) { return true; }
    public void removeCallbacks(Runnable r) {}
}
'''

MESSAGE_SHIM_JAVA = r'''
package android.os;
public final class Message {
    public static Message obtain(Handler h, Runnable r) { return new Message(); }
    public void setAsynchronous(boolean async) {}
}
'''

BUILD_SHIM_JAVA = r'''
package android.os;
public class Build {
    public static class VERSION {
        public static final int SDK_INT = 28;
    }
}
'''

EGL14_SHIM_JAVA = r'''
package android.opengl;
public class EGL14 {
    private static native EGLSurface _eglCreateWindowSurface(EGLDisplay d, EGLConfig c, Object w, int[] a, int o);
    private static native EGLSurface _eglCreateWindowSurfaceTexture(EGLDisplay d, EGLConfig c, Object w, int[] a, int o);
}
'''

PROBE_JAVA = r'''
import android.graphics.Canvas;
import android.graphics.Rect;
import android.os.Handler;
import android.os.MessageQueue;
import android.view.DisplayEventReceiver;
import android.view.Surface;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.util.HashSet;
import java.util.Set;

public final class WaylandHeadlessProbe {
    static void require(boolean ok, String msg) {
        if (!ok) throw new AssertionError(msg);
    }

    public static void main(String[] args) throws Throwable {
        System.load(args[0]);

        Field mainField = SdWindowHost.class.getDeclaredField("main");
        mainField.setAccessible(true);
        mainField.set(null, new Handler());

        Method nativeInstall = SdWindowHost.class.getDeclaredMethod("nativeInstall");
        nativeInstall.setAccessible(true);
        nativeInstall.invoke(null);

        // Verify DisplayEventReceiver & Surface JNI registrations dispatch through cached jmethodIDs.
        Method dispInit = DisplayEventReceiver.class.getDeclaredMethod(
            "nativeInit", WeakReference.class, MessageQueue.class, int.class);
        Method dispSchedule = DisplayEventReceiver.class.getDeclaredMethod("nativeScheduleVsync", long.class);
        Method dispDispose = DisplayEventReceiver.class.getDeclaredMethod("nativeDispose", long.class);
        dispInit.setAccessible(true);
        dispSchedule.setAccessible(true);
        dispDispose.setAccessible(true);

        Method surfValid = Surface.class.getDeclaredMethod("nativeIsValid", long.class);
        Method surfBehind = Surface.class.getDeclaredMethod("nativeIsConsumerRunningBehind", long.class);
        Method surfWidth = Surface.class.getDeclaredMethod("nativeGetWidth", long.class);
        Method surfHeight = Surface.class.getDeclaredMethod("nativeGetHeight", long.class);
        surfValid.setAccessible(true);
        surfBehind.setAccessible(true);
        surfWidth.setAccessible(true);
        surfHeight.setAccessible(true);

        require(!((Boolean) surfValid.invoke(null, 999999L)), "Unallocated surface id should not be valid");
        for (Method m : new Method[]{surfBehind, surfWidth, surfHeight}) {
            try {
                m.invoke(null, 999999L);
                throw new AssertionError("Expected IllegalArgumentException from " + m.getName());
            } catch (java.lang.reflect.InvocationTargetException expected) {
                require(expected.getCause() instanceof IllegalArgumentException,
                        "Unexpected exception from " + m.getName() + ": " + expected.getCause());
            }
        }

        Method nativeStart = SdWindowHost.class.getDeclaredMethod(
            "nativeStart", String.class, String.class, int.class, int.class);
        Method nativeDirectAcquire = SdWindowHost.class.getDeclaredMethod("nativeDirectAcquire");
        Method nativeDirectCommit = SdWindowHost.class.getDeclaredMethod("nativeDirectCommit");
        Method nativeRequestFrame = SdWindowHost.class.getDeclaredMethod("nativeRequestFrame");
        Method nativeStop = SdWindowHost.class.getDeclaredMethod("nativeStop");
        Method nativeClientHeight = SdWindowHost.class.getDeclaredMethod("nativeClientHeight");
        nativeStart.setAccessible(true);
        nativeDirectAcquire.setAccessible(true);
        nativeDirectCommit.setAccessible(true);
        nativeRequestFrame.setAccessible(true);
        nativeStop.setAccessible(true);
        nativeClientHeight.setAccessible(true);

        int w = 320, h = 480;
        boolean started = (Boolean) nativeStart.invoke(null, "HeadlessProbe", "org.saildroid.probe", w, h);
        require(started, "SdWindowHost.nativeStart failed against headless Weston");
        require(((Integer) nativeClientHeight.invoke(null)) > 0, "nativeClientHeight must be positive");

        // Drive 12 direct-SHM frames and assert DirectByteBuffer GlobalRef caching (<= 3 distinct objects).
        Set<Integer> bufferIdentities = new HashSet<Integer>();
        int committed = 0;
        for (int frame = 0; frame < 15 && committed < 10; frame++) {
            ByteBuffer direct = null;
            for (int spin = 0; spin < 40 && direct == null; spin++) {
                direct = (ByteBuffer) nativeDirectAcquire.invoke(null);
                if (direct == null) Thread.sleep(10L);
            }
            if (direct == null) continue;
            require(direct.isDirect(), "Acquired SHM buffer must be a DirectByteBuffer");
            require(direct.capacity() >= w * h * 4, "Unexpected SHM capacity: " + direct.capacity());
            bufferIdentities.add(System.identityHashCode(direct));

            direct.clear();
            direct.putInt(0, 0xFF112233 + frame);
            boolean ok = (Boolean) nativeDirectCommit.invoke(null);
            require(ok, "nativeDirectCommit returned false");
            nativeRequestFrame.invoke(null);
            committed++;
            Thread.sleep(16L);
        }
        require(committed >= 6, "Too few frames committed to headless Weston: " + committed);
        require(bufferIdentities.size() >= 1 && bufferIdentities.size() <= 3,
                "DirectByteBuffer GlobalRefs were not cached per triple-buffer slot: count=" + bufferIdentities.size());

        nativeStop.invoke(null);
        Thread.sleep(80L);
        System.out.println("WAYLAND_HEADLESS=PASS|committed=" + committed + "|cached_buffers=" + bufferIdentities.size());
    }
}
'''


def build_window_so(out_dir: Path, jni_include: Path) -> Path:
    wayland_flags = subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'wayland-client', 'libpng'], text=True
    ).split()
    xdg_xml = '/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml'
    subprocess.run(['wayland-scanner', 'client-header', xdg_xml, str(out_dir / 'xdg-shell-client-protocol.h')], check=True)
    subprocess.run(['wayland-scanner', 'private-code', xdg_xml, str(out_dir / 'xdg-shell-protocol.c')], check=True)
    surf_xml = str(REPO / 'native/window/surface-extension.xml')
    subprocess.run(['wayland-scanner', 'client-header', surf_xml, str(out_dir / 'surface-extension-client-protocol.h')], check=True)
    subprocess.run(['wayland-scanner', 'private-code', surf_xml, str(out_dir / 'surface-extension-protocol.c')], check=True)
    target = out_dir / 'libsdwindow.so'
    subprocess.run([
        'gcc', '-shared', '-fPIC', '-O2', '-Wall',
        '-o', str(target),
        str(REPO / 'native/window/sdwindow.c'),
        str(REPO / 'native/window/native-display-events.c'),
        str(REPO / 'native/hwui/sd-hwui-host.c'),
        str(REPO / 'native/hwui/sd-hwui-background.c'),
        str(REPO / 'native/window/sdcontrol.c'),
        str(REPO / 'native/window/sdactivate.c'),
        str(out_dir / 'xdg-shell-protocol.c'),
        str(out_dir / 'surface-extension-protocol.c'),
        f'-I{out_dir}', f'-I{jni_include}', f'-I{jni_include / "linux"}',
        *wayland_flags, '-pthread', '-ldl',
    ], check=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--classes', type=Path, required=True)
    parser.add_argument('--jni-include', type=Path, required=True)
    parser.add_argument('--window-so', type=Path, default=None)
    args = parser.parse_args()

    weston = shutil.which('weston')
    if not weston:
        raise SystemExit('ERROR: weston is required')

    java_home = args.jni_include.resolve().parent
    javac = java_home / 'bin/javac'
    java = java_home / 'bin/java'

    with tempfile.TemporaryDirectory(prefix='sd-wl-headless-') as tmp:
        work = Path(tmp)
        os.chmod(work, 0o700)
        runtime_dir = work / 'xdg'
        runtime_dir.mkdir(mode=0o700)
        perf_file = work / 'sdperf.log'

        window_so = args.window_so if (args.window_so and args.window_so.is_file()) else build_window_so(work, args.jni_include)

        src_dir = work / 'src'
        probe_out = work / 'out'
        (src_dir / 'dalvik/system').mkdir(parents=True)
        (src_dir / 'android/os').mkdir(parents=True)
        (src_dir / 'android/opengl').mkdir(parents=True)
        probe_out.mkdir()
        java_files = []
        for rel, content in [
            ('dalvik/system/VMRuntime.java', VM_RUNTIME_JAVA),
            ('dalvik/system/CloseGuard.java', CLOSE_GUARD_JAVA),
            ('android/os/Handler.java', HANDLER_SHIM_JAVA),
            ('android/os/Message.java', MESSAGE_SHIM_JAVA),
            ('android/os/Build.java', BUILD_SHIM_JAVA),
            ('android/opengl/EGL14.java', EGL14_SHIM_JAVA),
            ('WaylandHeadlessProbe.java', PROBE_JAVA),
        ]:
            target = src_dir / rel
            target.write_text(content, encoding='utf-8')
            java_files.append(str(target))
        subprocess.run([
            str(javac), '-nowarn', '--release', '11',
            '-cp', f'{args.classes}:{args.framework}',
            '-d', str(probe_out),
            *java_files,
        ], check=True)

        socket_name = 'wayland-sdtest'
        env = dict(
            os.environ,
            XDG_RUNTIME_DIR=str(runtime_dir),
            WAYLAND_DISPLAY=socket_name,
            SAILDROID_DIRECT_SHM='1',
            SAILDROID_PERF='1',
            SAILDROID_PERF_FILE=str(perf_file),
        )
        env.pop('SAILDROID_HWUI', None)

        compositor = subprocess.Popen(
            [
                weston,
                '--backend=headless',
                '--renderer=pixman',
                f'--socket={socket_name}',
                '--idle-time=0',
                '--no-config',
                '--width=320',
                '--height=480',
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            socket_path = runtime_dir / socket_name
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if compositor.poll() is not None:
                    err = compositor.stderr.read() if compositor.stderr else ''
                    raise RuntimeError(f'weston exited early ({compositor.returncode}): {err}')
                if socket_path.exists():
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError('Timed out waiting for headless Weston Wayland socket')

            run = subprocess.run(
                [
                    str(java),
                    '-cp', f'{probe_out}:{args.classes}:{args.framework}',
                    'WaylandHeadlessProbe',
                    str(window_so),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if run.returncode != 0:
                raise RuntimeError(f'WaylandHeadlessProbe failed:\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}')
            assert 'WAYLAND_HEADLESS=PASS|' in run.stdout, run.stdout
            perf_text = perf_file.read_text(encoding='utf-8') if perf_file.is_file() else ''
            assert 'SDPERF=meta|api=5|' in perf_text, f'Missing SDPERF meta line in {perf_text!r}'
            print(run.stdout.strip())
        finally:
            if compositor.poll() is None:
                compositor.terminate()
                try:
                    compositor.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait(timeout=2)


if __name__ == '__main__':
    main()
