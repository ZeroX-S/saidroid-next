#!/usr/bin/env python3
"""Check API28 public channel queries and the retained API29 argument layout."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


CONTEXT = r'''
package android.content;
public class Context {
    public String getPackageName() { return "com.tencent.mm"; }
    public String getOpPackageName() { return "com.tencent.mm"; }
    public int getUserId() { return 1; }
}
'''

SERVICES = r'''
package android.os;
public class ServiceManager {
    public static IBinder notification;
    public static IBinder getService(String name) { return notification; }
}
'''

PACKAGE = r'''
import android.content.pm.ApplicationInfo;
public class SdApkPackage {
    public static final String NAME = "com.tencent.mm";
    public static ApplicationInfo applicationInfo() {
        ApplicationInfo info = new ApplicationInfo();
        info.dataDir = System.getProperty("saildroid.test.data");
        return info;
    }
}
'''

DIAGNOSTICS = r'''
public class SdRuntimeDiagnostics {
    public static UnsupportedOperationException unsupported(String owner, java.lang.reflect.Method method) {
        return new UnsupportedOperationException(owner + " " + method);
    }
}
'''

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
import android.app.INotificationManager;
import android.app.NotificationManager;
import android.content.Context;
import android.content.pm.ParceledListSlice;
import android.os.Handler;
import android.os.ServiceManager;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.util.concurrent.FutureTask;

public class NotificationChannelArgumentsProbe {
    interface Api29 {
        Object getNotificationChannel(String pkg, int user, String targetPkg, String id);
        Object getNotificationChannels(String pkg, String targetPkg, int user);
    }
    static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    public static void main(String[] arguments) throws Throwable {
        ServiceManager.notification = SdNotificationPolicy.binder();
        INotificationManager service = INotificationManager.Stub.asInterface(ServiceManager.notification);
        Constructor<NotificationManager> constructor = NotificationManager.class.getDeclaredConstructor(Context.class, Handler.class);
        constructor.setAccessible(true);
        final NotificationManager manager = constructor.newInstance(new Context(), null);
        if (arguments.length != 0 && arguments[0].equals("before")) {
            try {
                manager.getNotificationChannel("missing");
                throw new AssertionError("API28 channel argument failure did not reproduce");
            } catch (ClassCastException expected) {
                System.out.println("NOTIFICATION_CHANNEL_ARGUMENTS=baseline|query=ClassCastException");
            }
            try {
                manager.getNotificationChannels();
                throw new AssertionError("API28 channel list argument failure did not reproduce");
            } catch (ArrayIndexOutOfBoundsException expected) {
                System.out.println("NOTIFICATION_CHANNEL_ARGUMENTS=baseline|list=ArrayIndexOutOfBoundsException");
            }
            return;
        }
        require(manager.getNotificationChannel("missing") == null, "Missing channel query failed");
        require(manager.getNotificationChannels().isEmpty(), "API28 list arguments failed");
        require(manager.getNotificationChannelGroup("missing") == null, "Missing group query changed");
        require(manager.getNotificationChannelGroups().isEmpty(), "Group list changed");
        require(!manager.areNotificationsEnabled(), "Existing delivery policy changed");
        try {
            service.getNotificationChannel("foreign.package", "missing");
            throw new AssertionError("Foreign package query accepted");
        } catch (SecurityException expected) {}
        try {
            service.getNotificationChannelForPackage("com.tencent.mm", 0, "missing", false);
            throw new AssertionError("Foreign UID query accepted");
        } catch (SecurityException expected) {}
        InvocationHandler handler = Proxy.getInvocationHandler(service);
        require(handler.invoke(service, Api29.class.getMethod("getNotificationChannel", String.class, int.class, String.class, String.class),
                new Object[]{"com.tencent.mm", 1, "com.tencent.mm", "missing"}) == null, "API29 channel arguments changed");
        ParceledListSlice<?> list = (ParceledListSlice<?>) handler.invoke(service,
                Api29.class.getMethod("getNotificationChannels", String.class, String.class, int.class),
                new Object[]{"com.tencent.mm", "com.tencent.mm", 1});
        require(list.getList().isEmpty(), "API29 list arguments changed");
        try {
            handler.invoke(service, Api29.class.getMethod("getNotificationChannel", String.class, int.class, String.class, String.class),
                    new Object[]{"com.tencent.mm", 2, "com.tencent.mm", "missing"});
            throw new AssertionError("Foreign API29 user accepted");
        } catch (SecurityException expected) {}
        try {
            handler.invoke(service, Api29.class.getMethod("getNotificationChannels", String.class, String.class, int.class),
                    new Object[]{"com.tencent.mm", "foreign.package", 1});
            throw new AssertionError("Foreign API29 target package accepted");
        } catch (SecurityException expected) {}
        FutureTask<Void> worker = new FutureTask<Void>(() -> {
            for (int i = 0; i < 100; i++) {
                require(manager.getNotificationChannel("missing") == null, "Background channel query failed");
                require(manager.getNotificationChannels().isEmpty(), "Background list query failed");
            }
            return null;
        });
        Thread thread = new Thread(worker, "notification-account-initialization");
        thread.start();
        worker.get();
        thread.join();
        System.out.println("NOTIFICATION_CHANNEL_ARGUMENTS=passed|public_api=28|legacy_layout=29|background_queries=200");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', required=True, type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--before', action='store_true')
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    source = arguments.source or repository / 'scripts/device/SdNotificationPolicy.java'
    spec = importlib.util.spec_from_file_location('text_fixture', Path(__file__).with_name('check-text-services.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory(prefix='saildroid-notification-arguments-') as temporary:
        root = Path(temporary)
        sources = []
        for name, code in [('android/os/Binder.java', fixture.BINDER), ('android/os/ServiceManager.java', SERVICES),
                           ('dalvik/system/VMRuntime.java', VM_RUNTIME),
                           ('android/os/Process.java', 'package android.os; public class Process { public static int myUid() { return 100000; } }'),
                           ('android/content/Context.java', CONTEXT), ('SdApkPackage.java', PACKAGE),
                           ('SdRuntimeDiagnostics.java', DIAGNOSTICS), ('NotificationChannelArgumentsProbe.java', PROBE)]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        policy = root / 'SdNotificationPolicy.java'
        policy.write_bytes(source.read_bytes())
        classes = root / 'classes'
        classes.mkdir()
        subprocess.run(['javac', '--release', '8', '-nowarn', '-encoding', 'UTF-8', '-cp', str(arguments.framework),
                        '-d', str(classes), *map(str, sources), str(policy)], check=True)
        command = ['java', '-Dsaildroid.test.data=' + str(root / 'data'), '-cp',
                   os.pathsep.join(map(str, [classes, arguments.framework])), 'NotificationChannelArgumentsProbe']
        subprocess.run(command + (['before'] if arguments.before else []), check=True)


if __name__ == '__main__':
    main()
