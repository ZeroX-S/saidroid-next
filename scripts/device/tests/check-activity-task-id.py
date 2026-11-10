#!/usr/bin/env python3
"""Exercise API28 Activity task IDs for registered and virtual Activities."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


PROBE = r'''
import android.app.Activity;
import android.app.IActivityManager;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.ApplicationInfo;
import android.os.Binder;
import java.lang.reflect.Field;
import java.util.concurrent.FutureTask;

public class ActivityTaskIdProbe {
    static Activity activity(Binder token) throws Exception {
        Class<?> type = Class.forName("sun.misc.Unsafe");
        Field field = type.getDeclaredField("theUnsafe"); field.setAccessible(true);
        Object memory = field.get(null);
        Activity activity = (Activity) type.getMethod("allocateInstance", Class.class).invoke(memory, Activity.class);
        Field identity = Activity.class.getDeclaredField("mToken"); identity.setAccessible(true); identity.set(activity, token);
        return activity;
    }
    public static void main(String[] arguments) throws Exception {
        SdActivityManagerService backend = new SdActivityManagerService();
        ApplicationInfo owner = new ApplicationInfo(); owner.packageName = "com.tencent.mm"; owner.processName = owner.packageName;
        backend.bindApplication(owner); backend.installFrameworkCache();
        IActivityManager service = IActivityManager.Stub.asInterface(backend.asBinder());
        Activity virtual = activity(null);
        if (arguments.length != 0) {
            try { virtual.getTaskId(); throw new AssertionError("Baseline failure missing"); }
            catch (IllegalArgumentException expected) {}
            System.out.println("ACTIVITY_TASK_ID=baseline|failure=IllegalArgumentException"); return;
        }
        Binder token = new Binder();
        Activity hosted = activity(token);
        if (virtual.getTaskId() != -1 || hosted.getTaskId() != -1) throw new AssertionError("Unregistered Activity has a task");
        ActivityInfo info = new ActivityInfo(); info.packageName = owner.packageName; info.name = "com.tencent.mm.ui.vas.VASCommonActivity";
        backend.registerActivity(token, info, new Intent("fixture.launch"), 0);
        if (hosted.getTaskId() != 1 || service.getTaskForActivity(token, false) != 1) throw new AssertionError("Registered task identity missing");
        try { service.getActivityDisplayId(new Binder()); throw new AssertionError("Unknown display owner accepted"); }
        catch (IllegalArgumentException expected) {}
        try { backend.registerActivity(token, info, new Intent("fixture.launch"), 0); throw new AssertionError("Duplicate token accepted"); }
        catch (IllegalStateException expected) {}
        FutureTask<Void> worker = new FutureTask<Void>(() -> {
            for (int index = 0; index < 100; index++) {
                if (virtual.getTaskId() != -1 || hosted.getTaskId() != 1) throw new AssertionError("Background task query changed");
            }
            return null;
        });
        Thread thread = new Thread(worker, "wechat-virtual-activity"); thread.start(); worker.get(); thread.join();
        service.activityDestroyed(token);
        if (hosted.getTaskId() != -1) throw new AssertionError("Destroyed Activity retained task");
        System.out.println("ACTIVITY_TASK_ID=passed|public_api=28|unregistered=-1|registered=1|background_queries=200|lifecycle_guards=true");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', required=True, type=Path)
    parser.add_argument('--classes', required=True, type=Path, action='append')
    parser.add_argument('--before', action='store_true')
    arguments = parser.parse_args()
    spec = importlib.util.spec_from_file_location('text_fixture', Path(__file__).with_name('check-text-services.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory(prefix='saildroid-activity-task-id-') as temporary:
        root = Path(temporary)
        definitions = [
            ('android/os/SystemProperties.java', 'package android.os; public class SystemProperties { public static boolean getBoolean(String key, boolean fallback) { return fallback; } public static int getInt(String key, int fallback) { return fallback; } public static String get(String key) { return ""; } }'),
            ('android/app/IActivityManager.java', 'package android.app; import android.os.*; public interface IActivityManager extends IInterface { int getTaskForActivity(IBinder token, boolean root) throws RemoteException; int getActivityDisplayId(IBinder token) throws RemoteException; void activityDestroyed(IBinder token) throws RemoteException; abstract class Stub { public static IActivityManager asInterface(IBinder binder) { return (IActivityManager) binder.queryLocalInterface("android.app.IActivityManager"); } } }'),
            ('android/os/Binder.java', fixture.BINDER),
            ('android/os/Process.java', 'package android.os; public class Process { public static final int SYSTEM_UID = 1000; public static int myUid() { return 100000; } public static int myPid() { return 123; } }'),
            ('SdRuntimeDiagnostics.java', 'public class SdRuntimeDiagnostics { public static UnsupportedOperationException unsupported(String owner, java.lang.reflect.Method method) { return new UnsupportedOperationException(owner + " " + method); } }'),
            ('ActivityTaskIdProbe.java', PROBE),
        ]
        sources = []
        for name, code in definitions:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        classes = root / 'classes'
        classes.mkdir()
        classpath = os.pathsep.join(map(str, [*arguments.classes, arguments.framework]))
        subprocess.run(['javac', '--release', '8', '-nowarn', '-encoding', 'UTF-8', '-cp',
                        classpath, '-d', str(classes), *map(str, sources)], check=True)
        subprocess.run(['java', '-cp', os.pathsep.join([str(classes), classpath]),
                        'ActivityTaskIdProbe', *(['before'] if arguments.before else [])], check=True)


if __name__ == '__main__':
    main()
