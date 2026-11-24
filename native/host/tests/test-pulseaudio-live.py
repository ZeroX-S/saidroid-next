#!/usr/bin/env python3
"""Live PulseAudio daemon + libsdhostapi.so + HostApi/SdAudio event-driven route test."""
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
    public Object newUnpaddedArray(Class<?> type, int count) {
        return java.lang.reflect.Array.newInstance(type, count);
    }
}
'''

SYSTEM_CLOCK_JAVA = r'''
package android.os;
public final class SystemClock {
    public static long uptimeMillis() { return System.nanoTime() / 1_000_000L; }
    public static long elapsedRealtime() { return uptimeMillis(); }
}
'''

PROBE_JAVA = r'''
import android.media.AudioSystem;
import java.lang.reflect.Method;
import java.util.ArrayList;
import org.json.JSONArray;
import org.json.JSONObject;
import org.saildroid.host.HostApi;

public final class PulseAudioLiveProbe {
    static void require(boolean ok, String msg) {
        if (!ok) throw new AssertionError(msg);
    }

    public static void main(String[] args) throws Throwable {
        String pactl = args[0];
        String initial = HostApi.audioSnapshot();
        JSONObject snap0 = new JSONObject(initial);
        JSONArray outputs0 = snap0.getJSONArray("outputs");
        require(outputs0.length() >= 1, "Expected initial PulseAudio output sink: " + initial);
        boolean foundPrimary = false;
        for (int i = 0; i < outputs0.length(); i++) {
            JSONObject row = outputs0.getJSONObject(i);
            if ("sd_primary".equals(row.getString("name")) && row.getBoolean("default")) {
                require(row.getInt("rate") == 48000, "Unexpected primary rate: " + row);
                foundPrimary = true;
            }
        }
        require(foundPrimary, "Default sd_primary sink missing from snapshot: " + initial);

        // Repeated cached snapshot queries must execute in-memory without reconnecting.
        long t0 = System.nanoTime();
        for (int i = 0; i < 200; i++) {
            String cached = HostApi.audioSnapshot();
            require(cached.length() == initial.length(), "Cached snapshot changed unexpectedly");
        }
        long avgUs = (System.nanoTime() - t0) / 200L / 1000L;
        require(avgUs < 500, "Cached audioSnapshot too slow: " + avgUs + " us/call");

        // Install SdAudio native bindings onto AudioTrack + AudioSystem + AudioPortEventHandler.
        Method nativeInstall = SdAudio.class.getDeclaredMethod("nativeInstall", Class.class);
        nativeInstall.setAccessible(true);
        Class<?> audioTrack = Class.forName("android.media.AudioTrack", false, SdAudio.class.getClassLoader());
        nativeInstall.invoke(null, audioTrack);

        require(AudioSystem.getPrimaryOutputSamplingRate() == 48000, "Primary sampling rate mismatch");
        require(AudioSystem.getPrimaryOutputFrameCount() == 0, "Primary frame count mismatch");
        // 0x4000 == DEVICE_OUT_USB_DEVICE; initially absent.
        require(AudioSystem.getDeviceConnectionState(0x4000, "") == 0, "USB sink should not be connected yet");

        @SuppressWarnings({"rawtypes", "unchecked"})
        ArrayList ports = new ArrayList();
        int[] portGen = new int[1];
        require(AudioSystem.listAudioPorts(ports, portGen) == 0, "listAudioPorts failed");
        require(ports.size() >= 1 && portGen[0] != 0, "Expected at least one audio port");

        long gen0 = HostApi.awaitAudioRouteChange(0L, 1L);
        require(gen0 >= 1L, "Initial generation must be >= 1");
        long sameGen = HostApi.awaitAudioRouteChange(gen0, 30L);
        require(sameGen == gen0, "Idle awaitAudioRouteChange should retain generation");

        // Trigger a dynamic sink hotplug via pactl while awaiting route change.
        Thread hotplug = new Thread(() -> {
            try {
                Thread.sleep(60L);
                Process p = new ProcessBuilder(
                    pactl, "load-module", "module-null-sink",
                    "sink_name=sd_usb_headset",
                    "rate=44100",
                    "sink_properties=device.bus=usb"
                ).inheritIO().start();
                if (p.waitFor() != 0) throw new RuntimeException("pactl load-module failed");
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        });
        long waitStart = System.nanoTime();
        hotplug.start();
        long gen1 = HostApi.awaitAudioRouteChange(gen0, 3000L);
        long wakeMs = (System.nanoTime() - waitStart) / 1_000_000L;
        hotplug.join();

        require(gen1 > gen0, "awaitAudioRouteChange did not advance on sink hotplug");
        require(wakeMs < 1500L, "Event wakeup took too long: " + wakeMs + " ms");

        JSONObject snap1 = new JSONObject(HostApi.audioSnapshot());
        JSONArray outputs1 = snap1.getJSONArray("outputs");
        boolean foundUsb = false;
        for (int i = 0; i < outputs1.length(); i++) {
            if ("sd_usb_headset".equals(outputs1.getJSONObject(i).getString("name"))) {
                foundUsb = true;
            }
        }
        require(foundUsb, "Hotplugged sd_usb_headset missing from updated snapshot: " + snap1);
        require(AudioSystem.getDeviceConnectionState(0x4000, "") == 1,
                "Hotplugged USB sink not reflected in getDeviceConnectionState");

        System.out.println("PULSEAUDIO_LIVE=PASS|cached_avg_us=" + avgUs + "|wake_ms=" + wakeMs + "|gen=" + gen1);
    }
}
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--classes', type=Path, required=True)
    parser.add_argument('--jni-include', type=Path, required=True)
    parser.add_argument('--hostapi-so', type=Path, default=None)
    args = parser.parse_args()

    pulseaudio = shutil.which('pulseaudio')
    pactl = shutil.which('pactl')
    if not pulseaudio or not pactl:
        raise SystemExit('ERROR: pulseaudio and pactl are required')

    java_home = args.jni_include.resolve().parent
    javac = java_home / 'bin/javac'
    java = java_home / 'bin/java'

    with tempfile.TemporaryDirectory(prefix='sd-pa-live-') as tmp:
        work = Path(tmp)
        os.chmod(work, 0o700)
        android_root = work / 'root'
        (android_root / 'lib').mkdir(parents=True)
        pa_runtime = work / 'pa-runtime'
        pa_state = work / 'pa-state'
        pa_home = work / 'home'
        for d in (pa_runtime, pa_state, pa_home):
            d.mkdir(mode=0o700)

        target_so = android_root / 'lib/libsdhostapi.so'
        if args.hostapi_so and args.hostapi_so.is_file():
            shutil.copy2(args.hostapi_so, target_so)
        else:
            gio_flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0'], text=True).split()
            pulse_flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libpulse'], text=True).split()
            subprocess.run([
                'g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-fPIC', '-shared',
                '-o', str(target_so),
                str(REPO / 'native/host/host-api.cpp'),
                str(REPO / 'native/host/host-audio.cpp'),
                str(REPO / 'native/host/host-audio-record.cpp'),
                str(REPO / 'native/host/host-network.cpp'),
                f'-I{args.jni_include}', f'-I{args.jni_include / "linux"}',
                *gio_flags, *pulse_flags, '-pthread',
            ], check=True)

        pa_socket = pa_runtime / 'native'
        pa_script = work / 'default.pa'
        pa_script.write_text(
            f'load-module module-native-protocol-unix auth-anonymous=1 socket={pa_socket}\n'
            'load-module module-null-sink sink_name=sd_primary rate=48000 channels=2 '
            'sink_properties=device.description="PrimarySink"\n'
            'set-default-sink sd_primary\n',
            encoding='utf-8',
        )

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'text_fixture', REPO / 'scripts/device/tests/check-text-services.py'
        )
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)

        probe_src = work / 'src'
        probe_out = work / 'out'
        (probe_src / 'dalvik/system').mkdir(parents=True)
        (probe_src / 'android/os').mkdir(parents=True)
        probe_out.mkdir()
        (probe_src / 'dalvik/system/VMRuntime.java').write_text(VM_RUNTIME_JAVA, encoding='utf-8')
        (probe_src / 'android/os/Binder.java').write_text(fixture.BINDER, encoding='utf-8')
        (probe_src / 'android/os/SystemClock.java').write_text(SYSTEM_CLOCK_JAVA, encoding='utf-8')
        (probe_src / 'PulseAudioLiveProbe.java').write_text(PROBE_JAVA, encoding='utf-8')
        subprocess.run([
            str(javac), '-nowarn', '--release', '11',
            '-cp', f'{args.classes}:{args.framework}',
            '-d', str(probe_out),
            str(probe_src / 'dalvik/system/VMRuntime.java'),
            str(probe_src / 'android/os/Binder.java'),
            str(probe_src / 'android/os/SystemClock.java'),
            str(probe_src / 'PulseAudioLiveProbe.java'),
        ], check=True)

        env = dict(
            os.environ,
            HOME=str(pa_home),
            XDG_RUNTIME_DIR=str(work),
            PULSE_RUNTIME_PATH=str(pa_runtime),
            PULSE_STATE_PATH=str(pa_state),
            PULSE_SERVER=f'unix:{pa_socket}',
            ANDROID_ROOT=str(android_root),
        )
        daemon = subprocess.Popen(
            [
                pulseaudio,
                '--daemonize=no',
                '--disallow-exit',
                '--exit-idle-time=-1',
                '--log-target=stderr',
                '--log-level=error',
                '-n',
                f'--file={pa_script}',
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if daemon.poll() is not None:
                    err = daemon.stderr.read() if daemon.stderr else ''
                    raise RuntimeError(f'pulseaudio exited early ({daemon.returncode}): {err}')
                if pa_socket.exists():
                    info = subprocess.run([pactl, 'info'], env=env, capture_output=True, text=True)
                    if info.returncode == 0:
                        break
                time.sleep(0.05)
            else:
                raise TimeoutError('Timed out waiting for isolated PulseAudio server')

            run = subprocess.run(
                [
                    str(java),
                    '-cp', f'{probe_out}:{args.classes}:{args.framework}',
                    'PulseAudioLiveProbe',
                    pactl,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if run.returncode != 0:
                raise RuntimeError(f'PulseAudioLiveProbe failed:\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}')
            assert 'PULSEAUDIO_LIVE=PASS|' in run.stdout, run.stdout
            print(run.stdout.strip())
        finally:
            if daemon.poll() is None:
                daemon.terminate()
                try:
                    daemon.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait(timeout=2)


if __name__ == '__main__':
    main()
