#!/usr/bin/env python3
"""Exercise the actual API28 ActivityManager's package-scoped broadcast routing."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


PROCESS = """
package android.os;
public final class Process {
    public static int myPid() { return 123; }
    public static int myUid() { return 100000; }
}
"""

ACTIVITY_MANAGER = """
package android.app;
import android.content.IIntentReceiver;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Bundle;
import android.os.IInterface;
import android.os.RemoteException;
public interface IActivityManager extends IInterface {
    Intent registerReceiver(IApplicationThread caller, String name, IIntentReceiver receiver,
            IntentFilter filter, String permission, int user, int flags) throws RemoteException;
    void unregisterReceiver(IIntentReceiver receiver) throws RemoteException;
    int broadcastIntent(IApplicationThread caller, Intent intent, String type,
            IIntentReceiver resultTo, int result, String data, Bundle extras,
            String[] permissions, int appOp, Bundle options, boolean ordered,
            boolean sticky, int user) throws RemoteException;
}
"""

PERMISSIONS = """
public final class SdAppPermissions {
    public SdAppPermissions(String path, String name) {}
    public boolean holds(String name) {
        return "org.saildroid.OWNED".equals(name);
    }
}
"""

KERNEL = """
public final class SdKernelServices {
    public static boolean connected;
    public static boolean enabled() { return connected; }
}
"""

REMOTE = """
import android.content.Intent;
import android.os.Bundle;
public final class SdRemoteServices {
    public static SdActivityManagerService target;
    public static int calls;
    public static void broadcast(Intent intent, String type, int result, String data,
            Bundle extras, String[] permissions, int user) throws Exception {
        calls++;
        target.deliverBroadcast(intent, type, result, data, extras, permissions, user, true);
    }
}
"""

PROBE = """
import android.app.ActivityManager;
import android.app.IActivityManager;
import android.content.ComponentName;
import android.content.IIntentReceiver;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ApplicationInfo;
import android.os.Binder;
import android.os.IBinder;
import java.lang.reflect.Proxy;

public final class ForeignBroadcastProbe {
    private static final String PACKAGE = "org.saildroid.test";
    private static final String ACTION = PACKAGE + ".PING";
    private static int cases;

    private static void require(boolean condition, String detail) {
        if (!condition) throw new AssertionError(detail);
        cases++;
    }

    private static SdActivityManagerService manager() {
        ApplicationInfo app = new ApplicationInfo();
        app.packageName = PACKAGE;
        app.processName = PACKAGE;
        app.sourceDir = "/fixture/application.apk";
        SdActivityManagerService manager = new SdActivityManagerService();
        manager.bindApplication(app);
        return manager;
    }

    private static IActivityManager service(SdActivityManagerService manager) {
        return (IActivityManager) manager.asBinder().queryLocalInterface("android.app.IActivityManager");
    }

    private static int send(IActivityManager manager, Intent intent, String[] permissions, int user)
            throws Exception {
        return manager.broadcastIntent(null, intent, null, null, 0, null, null,
                permissions, -1, null, false, false, user);
    }

    private static IIntentReceiver receiver(final int[] count) {
        final Binder token = new Binder();
        return (IIntentReceiver) Proxy.newProxyInstance(IIntentReceiver.class.getClassLoader(),
                new Class<?>[]{IIntentReceiver.class}, (proxy, method, arguments) -> {
            if ("asBinder".equals(method.getName())) return token;
            if ("performReceive".equals(method.getName())) {
                count[0]++;
                ((Intent) arguments[0]).setAction("receiver.changed.copy");
                return null;
            }
            throw new AssertionError(method.getName());
        });
    }

    private static void foreignUser(IActivityManager manager, Intent intent) throws Exception {
        try {
            send(manager, intent, null, 2);
            throw new AssertionError("Foreign user accepted");
        } catch (SecurityException expected) { cases++; }
    }

    public static void main(String[] arguments) throws Exception {
        SdActivityManagerService local = manager();
        IActivityManager api = service(local);
        int[] localCount = {0};
        IIntentReceiver receiver = receiver(localCount);
        api.registerReceiver(null, PACKAGE, receiver, new IntentFilter(ACTION), null, 1, 0);
        api.registerReceiver(null, PACKAGE, receiver, new IntentFilter(ACTION), null, 1, 0);
        Intent foreign = new Intent(ACTION).setPackage("org.saildroid.absent");
        require(send(api, foreign, null, 1) == ActivityManager.BROADCAST_SUCCESS,
                "Foreign package send failed");
        require(localCount[0] == 0, "Foreign broadcast reached local receivers");
        Intent own = new Intent(ACTION).setPackage(PACKAGE);
        send(api, own, null, 1);
        require(localCount[0] == 1, "Same-package delivery or receiver deduplication failed");
        require(ACTION.equals(own.getAction()), "Receiver changed sender Intent");
        send(api, new Intent(ACTION), null, 1);
        require(localCount[0] == 2, "Unscoped delivery failed");
        send(api, own, new String[]{"org.saildroid.DENIED"}, 1);
        require(localCount[0] == 2, "Permission guard failed");
        send(api, own, new String[]{"org.saildroid.OWNED"}, 1);
        require(localCount[0] == 3, "Granted receiver delivery failed");
        foreignUser(api, foreign);
        foreignUser(api, own);
        try {
            api.broadcastIntent(null, foreign, null, null, 0, null, null,
                    null, -1, null, true, false, 1);
            throw new AssertionError("Ordered foreign broadcast accepted");
        } catch (UnsupportedOperationException expected) { cases++; }
        try {
            send(api, new Intent(ACTION).setComponent(new ComponentName(PACKAGE, PACKAGE + ".Receiver")),
                    null, 1);
            throw new AssertionError("Unsupported explicit receiver delivery accepted");
        } catch (UnsupportedOperationException expected) { cases++; }
        SdRemoteServices.target = manager();
        int[] remoteCount = {0};
        IIntentReceiver remoteReceiver = receiver(remoteCount);
        service(SdRemoteServices.target).registerReceiver(null, PACKAGE, remoteReceiver,
                new IntentFilter(ACTION), null, 1, 0);
        SdKernelServices.connected = true;
        send(api, foreign, null, 1);
        require(localCount[0] == 3 && remoteCount[0] == 0 && SdRemoteServices.calls == 1,
                "Foreign broadcast changed remote-process routing");
        send(api, own, null, 1);
        require(localCount[0] == 4 && remoteCount[0] == 1 && SdRemoteServices.calls == 2,
                "Same-package remote dispatch failed");
        send(api, new Intent(ACTION), null, 1);
        require(localCount[0] == 5 && remoteCount[0] == 2, "Unscoped remote dispatch failed");
        api.unregisterReceiver(receiver);
        send(api, own, null, 1);
        require(localCount[0] == 5 && remoteCount[0] == 3, "Unregistration or remote dispatch failed");
        service(SdRemoteServices.target).unregisterReceiver(remoteReceiver);
        send(api, own, null, 1);
        require(localCount[0] == 5 && remoteCount[0] == 3, "Absent receivers caused delivery");
        System.out.println("FOREIGN_BROADCAST_REGRESSION=PASS|cases=" + cases);
    }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--classes", type=Path, action="append", required=True)
    parser.add_argument("--source", type=Path,
                        default=Path(__file__).resolve().parents[1] / "SdActivityManagerService.java")
    arguments = parser.parse_args()
    binder_test = Path(__file__).with_name("check-input-method-finish.py")
    spec = importlib.util.spec_from_file_location("input_finish_test", binder_test)
    existing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(existing)
    with tempfile.TemporaryDirectory(prefix="saildroid-foreign-broadcast-") as temporary:
        work = Path(temporary)
        classes = work / "classes"
        classes.mkdir()
        retained = os.pathsep.join(map(str, [arguments.framework, *arguments.classes]))
        subprocess.run(["javac", "--release", "8", "-encoding", "UTF-8", "-nowarn",
                        "-sourcepath", "", "-cp", retained, "-d", str(classes),
                        str(arguments.source)], check=True)
        sources = {
            "android/app/IActivityManager.java": ACTIVITY_MANAGER,
            "android/os/Binder.java": existing.BINDER_STUB,
            "android/os/Process.java": PROCESS,
            "SdAppPermissions.java": PERMISSIONS,
            "SdKernelServices.java": KERNEL,
            "SdRemoteServices.java": REMOTE,
            "ForeignBroadcastProbe.java": PROBE,
        }
        paths = []
        for name, contents in sources.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8", newline="\n")
            paths.append(str(path))
        classpath = str(classes) + os.pathsep + retained
        subprocess.run(["javac", "--release", "8", "-encoding", "UTF-8", "-nowarn",
                        "-sourcepath", "", "-cp", classpath, "-d", str(classes), *paths], check=True)
        subprocess.run(["java", "-cp", classpath, "ForeignBroadcastProbe"], check=True)


if __name__ == "__main__":
    main()
