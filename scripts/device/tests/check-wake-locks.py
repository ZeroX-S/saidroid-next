#!/usr/bin/env python3
"""Exercise API28 wake-lock ownership through the production power proxy."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


HANDLER = r'''
package android.os;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Timer;
import java.util.TimerTask;
public class Handler {
    private final Timer timer = new Timer(true);
    private final Map<Runnable, TimerTask> pending = new IdentityHashMap<Runnable, TimerTask>();
    public synchronized boolean postDelayed(final Runnable task, long delay) {
        TimerTask scheduled = new TimerTask() { public void run() { task.run(); } };
        pending.put(task, scheduled);
        timer.schedule(scheduled, delay);
        return true;
    }
    public synchronized void removeCallbacks(Runnable task) {
        TimerTask scheduled = pending.remove(task);
        if (scheduled != null) scheduled.cancel();
    }
    public void close() { timer.cancel(); }
}
'''

HOST = r'''
package org.saildroid.host;
import java.util.HashMap;
import java.util.Map;
public class HostApi {
    private static final Map<String, Boolean> leases = new HashMap<String, Boolean>();
    public static boolean failAcquire, failRelease;
    public static int starts, renewals;
    public static boolean screenPaused;
    public static synchronized int acquireWakeLock(String session, boolean screen, boolean renewing) {
        if (failAcquire) { failAcquire = false; throw new IllegalStateException("Injected acquisition failure"); }
        if (renewing) {
            if (!leases.containsKey(session)) throw new AssertionError("Released lease renewed");
            renewals++;
        } else {
            if (leases.containsKey(session)) throw new AssertionError("Duplicate native lease");
            starts++;
            leases.put(session, screen);
        }
        if (screen) screenPaused = true;
        return 1;
    }
    public static synchronized void releaseWakeLock(String session, boolean cancelScreen) {
        if (failRelease) { failRelease = false; throw new IllegalStateException("Injected release failure"); }
        if (leases.remove(session) == null) throw new AssertionError("Unknown native lease released");
        if (cancelScreen) {
            if (leases.containsValue(true)) throw new AssertionError("Another screen owner was cancelled");
            screenPaused = false;
        }
    }
    public static synchronized int owners() { return leases.size(); }
}
'''

PROBE = r'''
import android.content.Context;
import android.os.*;
import org.saildroid.host.HostApi;
import java.util.concurrent.FutureTask;

public final class WakeLocksProbe {
    static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    public static void main(String[] arguments) throws Exception {
        IPowerManager service = IPowerManager.Stub.asInterface(SdPower.binder());
        Handler handler = new Handler();
        PowerManager manager = new PowerManager(new Context(), service, handler);
        try {
            PowerManager.WakeLock first = manager.newWakeLock(PowerManager.FULL_WAKE_LOCK, "NetSceneInit Lock");
            if (arguments.length != 0 && arguments[0].equals("before")) {
                try { first.acquire(); throw new AssertionError("Baseline failure missing"); }
                catch (UnsupportedOperationException expected) {}
                require(HostApi.owners() == 0, "Baseline acquired a native lease");
                System.out.println("WAKE_LOCKS=baseline|failure=UnsupportedOperationException");
                return;
            }
            require(manager.isWakeLockLevelSupported(PowerManager.FULL_WAKE_LOCK), "Full lock capability missing");
            require(manager.isWakeLockLevelSupported(PowerManager.PARTIAL_WAKE_LOCK), "CPU lock capability missing");
            require(!manager.isWakeLockLevelSupported(PowerManager.PROXIMITY_SCREEN_OFF_WAKE_LOCK), "Proximity capability advertised");
            first.acquire(); first.acquire();
            require(first.isHeld() && HostApi.owners() == 1 && HostApi.screenPaused, "Reference-counted acquisition failed");
            first.release();
            require(first.isHeld() && HostApi.owners() == 1, "Reference-counted release ended lease early");
            PowerManager.WakeLock second = manager.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK, "Second display owner");
            PowerManager.WakeLock cpu = manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "CPU owner");
            second.acquire(); cpu.acquire();
            first.release();
            require(HostApi.owners() == 2 && HostApi.screenPaused, "Second display owner lost its pause");
            second.release();
            require(HostApi.owners() == 1 && !HostApi.screenPaused, "Last display release failed");
            int oldRenewals = HostApi.renewals;
            Thread.sleep(800);
            require(HostApi.renewals > oldRenewals, "Held CPU lease was not renewed");
            cpu.release();
            require(HostApi.owners() == 0, "CPU release leaked lease");
            PowerManager.WakeLock timed = manager.newWakeLock(PowerManager.FULL_WAKE_LOCK, "Timed display owner");
            timed.acquire(100);
            Thread.sleep(250);
            require(!timed.isHeld() && HostApi.owners() == 0 && !HostApi.screenPaused, "Timed release failed");
            PowerManager.WakeLock plain = manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Non-reference owner");
            plain.setReferenceCounted(false); plain.acquire(); plain.acquire(); plain.release();
            require(!plain.isHeld() && HostApi.owners() == 0, "Non-reference-counted lease leaked");
            Binder token = new Binder();
            HostApi.failAcquire = true;
            try { service.acquireWakeLock(token, 1, "failure", "com.tencent.mm", null, null); throw new AssertionError("Failure hidden"); }
            catch (IllegalStateException expected) {}
            require(HostApi.owners() == 0, "Failed acquisition registered owner");
            service.acquireWakeLock(token, 1, "retry", "com.tencent.mm", null, null);
            HostApi.failRelease = true;
            try { service.releaseWakeLock(token, 0); throw new AssertionError("Release failure hidden"); }
            catch (IllegalStateException expected) {}
            require(HostApi.owners() == 1, "Failed release lost owner state");
            service.releaseWakeLock(token, 0); service.releaseWakeLock(token, 0);
            try { service.acquireWakeLock(new Binder(), 1, "foreign", "foreign.package", null, null); throw new AssertionError("Foreign package accepted"); }
            catch (SecurityException expected) {}
            System.setProperty("saildroid.test.wake-denied", "true");
            try { service.acquireWakeLock(new Binder(), 1, "denied", "com.tencent.mm", null, null); throw new AssertionError("Denied permission accepted"); }
            catch (SecurityException expected) {}
            System.clearProperty("saildroid.test.wake-denied");
            try { service.acquireWakeLockWithUid(new Binder(), 1, "foreign UID", "com.tencent.mm", 123); throw new AssertionError("Foreign UID accepted"); }
            catch (SecurityException expected) {}
            try { service.acquireWakeLock(new Binder(), 1, "attributed", "com.tencent.mm", new WorkSource(123), null); throw new AssertionError("Attribution accepted"); }
            catch (SecurityException expected) {}
            WorkSource chained = new WorkSource();
            chained.createWorkChain().addNode(123, "Background worker");
            try { service.acquireWakeLock(new Binder(), 1, "chained", "com.tencent.mm", chained, null); throw new AssertionError("Chained attribution accepted"); }
            catch (SecurityException expected) {}
            System.setProperty("saildroid.test.stats-granted", "true");
            try { service.acquireWakeLock(new Binder(), 1, "privileged chain", "com.tencent.mm", chained, null); throw new AssertionError("Unimplemented attribution accepted"); }
            catch (UnsupportedOperationException expected) {}
            System.clearProperty("saildroid.test.stats-granted");
            try { manager.newWakeLock(PowerManager.FULL_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP, "wake display").acquire(); throw new AssertionError("Unsupported transition accepted"); }
            catch (UnsupportedOperationException expected) {}
            FutureTask<Void> worker = new FutureTask<Void>(() -> {
                for (int index = 0; index < 100; index++) {
                    PowerManager.WakeLock lock = manager.newWakeLock(PowerManager.FULL_WAKE_LOCK, "Background initialization");
                    lock.acquire(); lock.release();
                }
                return null;
            });
            Thread thread = new Thread(worker, "wake-lock-account-initialization");
            thread.start(); worker.get(); thread.join();
            require(HostApi.owners() == 0 && !HostApi.screenPaused, "Background operations leaked owners");
            require(manager.isInteractive() && !manager.isPowerSaveMode(), "Existing state query changed");
            System.out.println("WAKE_LOCKS=passed|public_api=28|background_operations=200|timed_release=true|retry_consistency=true");
        } finally { handler.close(); }
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
    with tempfile.TemporaryDirectory(prefix='saildroid-wake-locks-') as temporary:
        root = Path(temporary)
        sources = []
        definitions = [
            ('android/os/Binder.java', fixture.BINDER), ('android/os/Handler.java', HANDLER),
            ('android/os/Process.java', 'package android.os; public class Process { public static int myUid() { return 100000; } public static int myPid() { return 42; } }'),
            ('android/os/Trace.java', 'package android.os; public class Trace { public static void asyncTraceBegin(long tag, String name, int cookie) {} public static void asyncTraceEnd(long tag, String name, int cookie) {} }'),
            ('dalvik/system/VMRuntime.java', 'package dalvik.system; public class VMRuntime { private static final VMRuntime runtime = new VMRuntime(); public static VMRuntime getRuntime() { return runtime; } public Object newUnpaddedArray(Class<?> type, int count) { return java.lang.reflect.Array.newInstance(type, count); } }'),
            ('android/content/Context.java', 'package android.content; public class Context { public String getOpPackageName() { return "com.tencent.mm"; } }'),
            ('SdApkPackage.java', 'public class SdApkPackage { public static final String APK = "fixture.apk", NAME = "com.tencent.mm"; }'),
            ('SdAppPermissions.java', 'public class SdAppPermissions { public SdAppPermissions(String apk, String owner) {} public boolean holds(String name) { return (name.equals("android.permission.WAKE_LOCK") && !Boolean.getBoolean("saildroid.test.wake-denied")) || (name.equals("android.permission.UPDATE_DEVICE_STATS") && Boolean.getBoolean("saildroid.test.stats-granted")); } }'),
            ('SdHostState.java', 'public class SdHostState { public static String string(String name) { return "on"; } public static boolean bool(String name) { return false; } }'),
            ('SdRuntimeDiagnostics.java', 'public class SdRuntimeDiagnostics { public static UnsupportedOperationException unsupported(String owner, java.lang.reflect.Method method) { return new UnsupportedOperationException(owner + " " + method); } }'),
            ('org/saildroid/host/HostApi.java', HOST), ('WakeLocksProbe.java', PROBE)]
        for name, code in definitions:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        classes = root / 'classes'
        classes.mkdir()
        subprocess.run(['javac', '--release', '8', '-nowarn', '-encoding', 'UTF-8', '-cp',
                        os.pathsep.join(map(str, [arguments.classes, arguments.framework])),
                        '-d', str(classes), *map(str, sources)], check=True)
        command = ['java', '-cp', os.pathsep.join(map(str, [classes, arguments.classes, arguments.framework])), 'WakeLocksProbe']
        subprocess.run(command + (['before'] if arguments.before else []), check=True)


if __name__ == '__main__':
    main()
