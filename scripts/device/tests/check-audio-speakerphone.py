#!/usr/bin/env python3
"""Exercise API28 speakerphone queries against the compiled production proxy."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


VM_RUNTIME = r'''
package dalvik.system;
public class VMRuntime {
    private static final VMRuntime runtime = new VMRuntime();
    public static VMRuntime getRuntime() { return runtime; }
    public Object newUnpaddedArray(Class<?> type, int count) {
        return java.lang.reflect.Array.newInstance(type, count);
    }
}
'''


PROBE = r'''
import android.media.AudioManager;
import android.media.IAudioService;
import android.os.IBinder;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.concurrent.FutureTask;
import sun.misc.Unsafe;

public final class AudioSpeakerphoneProbe {
    interface ForeignQuery { boolean isSpeakerphoneOn(); }
    interface ArgumentQuery { boolean isSpeakerphoneOn(int value); }
    interface WrongReturnQuery { int isSpeakerphoneOn(); }
    static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    static void reject(InvocationHandler handler, Object proxy, Method method, Object[] arguments) throws Throwable {
        try {
            handler.invoke(proxy, method, arguments);
            throw new AssertionError("Unrelated method accepted " + method);
        } catch (UnsupportedOperationException expected) {}
    }
    public static void main(String[] arguments) throws Throwable {
        IBinder binder = SdAudio.binder();
        final IAudioService service = IAudioService.Stub.asInterface(binder);
        require(service.asBinder() == binder, "Production Binder identity changed");
        // Allocate only the public client. Its query and setter dispatch execute
        // the real framework bytecode against the production local Binder.
        Field unsafeField = Unsafe.class.getDeclaredField("theUnsafe");
        unsafeField.setAccessible(true);
        Unsafe unsafe = (Unsafe) unsafeField.get(null);
        final AudioManager manager = (AudioManager) unsafe.allocateInstance(AudioManager.class);
        Field serviceField = AudioManager.class.getDeclaredField("sService");
        serviceField.setAccessible(true);
        serviceField.set(null, service);
        if (arguments.length != 0 && arguments[0].equals("before")) {
            try {
                manager.isSpeakerphoneOn();
                throw new AssertionError("Baseline exception did not reproduce");
            } catch (UnsupportedOperationException expected) {
                require(expected.getMessage().contains("isSpeakerphoneOn"), "Wrong baseline exception");
            }
            System.out.println("AUDIO_SPEAKERPHONE=baseline|failure=UnsupportedOperationException");
            return;
        }
        require(!manager.isSpeakerphoneOn(), "Unapplied communication override enabled");
        require(!service.isSpeakerphoneOn(), "Binder communication override enabled");
        for (boolean value : new boolean[]{true, false}) {
            try {
                manager.setSpeakerphoneOn(value);
                throw new AssertionError("Unavailable transition accepted");
            } catch (UnsupportedOperationException expected) {}
            require(!manager.isSpeakerphoneOn(), "Rejected setter changed state");
        }
        require(manager.getMode() == AudioManager.MODE_NORMAL, "Existing applied mode changed");
        require(service.getStreamMinVolume(AudioManager.STREAM_MUSIC) == 0, "Existing minimum volume changed");
        require(service.getStreamMaxVolume(AudioManager.STREAM_MUSIC) == 100, "Existing maximum volume changed");
        InvocationHandler handler = Proxy.getInvocationHandler(service);
        reject(handler, service, ForeignQuery.class.getMethod("isSpeakerphoneOn"), null);
        reject(handler, service, ArgumentQuery.class.getMethod("isSpeakerphoneOn", int.class), new Object[]{0});
        reject(handler, service, WrongReturnQuery.class.getMethod("isSpeakerphoneOn"), null);
        FutureTask<Void> worker = new FutureTask<Void>(() -> {
            for (int index = 0; index < 100; index++) {
                require(!manager.isSpeakerphoneOn(), "Background public query changed");
                require(!service.isSpeakerphoneOn(), "Background Binder query changed");
            }
            return null;
        });
        Thread thread = new Thread(worker, "audio-account-initialization");
        thread.start();
        worker.get();
        thread.join();
        System.out.println("AUDIO_SPEAKERPHONE=passed|public_api=28|background_queries=200|communication_override=false");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', required=True, type=Path)
    parser.add_argument('--classes', required=True, type=Path)
    parser.add_argument('--before', action='store_true')
    arguments = parser.parse_args()
    spec = importlib.util.spec_from_file_location('text_fixture', Path(__file__).with_name('check-text-services.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory(prefix='saildroid-speakerphone-') as temporary:
        root = Path(temporary)
        sources = []
        diagnostics = 'public class SdRuntimeDiagnostics { public static UnsupportedOperationException unsupported(String owner, java.lang.reflect.Method method) { return new UnsupportedOperationException(owner + " " + method); } }'
        for name, code in [('android/os/Binder.java', fixture.BINDER),
                           ('dalvik/system/VMRuntime.java', VM_RUNTIME),
                           ('SdRuntimeDiagnostics.java', diagnostics), ('AudioSpeakerphoneProbe.java', PROBE)]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        classes = root / 'classes'
        classes.mkdir()
        classpath = os.pathsep.join(map(str, [arguments.classes, arguments.framework]))
        subprocess.run(['javac', '-nowarn', '-encoding', 'UTF-8', '-cp', classpath,
                        '-d', str(classes), *map(str, sources)], check=True)
        command = ['java', '-cp', os.pathsep.join(map(str, [classes, arguments.classes, arguments.framework])),
                   'AudioSpeakerphoneProbe']
        subprocess.run(command + (['before'] if arguments.before else []), check=True)


if __name__ == '__main__':
    main()
