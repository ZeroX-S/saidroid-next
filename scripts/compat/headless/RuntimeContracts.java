package org.saildroid.compat;

import android.app.Activity;
import android.app.ActivityThread;
import android.app.IActivityManager;
import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.ApplicationInfo;
import android.os.BadParcelableException;
import android.os.Binder;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Parcel;
import android.os.Parcelable;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.concurrent.FutureTask;

/** Boot-owned contracts against the actual packaged framework and runtime. */
public final class RuntimeContracts {
    private static final String PACKAGE = "org.saildroid.compat";
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static Object call(Class<?> type, Object target, String name, Class<?>[] parameters,
                               Object... arguments) throws Throwable {
        try { return type.getMethod(name, parameters).invoke(target, arguments); }
        catch (InvocationTargetException failure) { throw failure.getCause(); }
    }
    private static void field(Object target, String name, Object value) throws Exception {
        Field member = target.getClass().getDeclaredField(name);
        member.setAccessible(true);
        member.set(target, value);
    }
    private static Object allocate(Class<?> type) throws Exception {
        Class<?> unsafe = Class.forName("sun.misc.Unsafe");
        Field member = unsafe.getDeclaredField("theUnsafe");
        member.setAccessible(true);
        return unsafe.getMethod("allocateInstance", Class.class).invoke(member.get(null), type);
    }
    private static IActivityManager activityManager() throws Throwable {
        Class<?> type = Class.forName("SdActivityManagerService");
        Object backend = type.getConstructor().newInstance();
        ApplicationInfo owner = new ApplicationInfo();
        owner.packageName = PACKAGE; owner.processName = PACKAGE;
        owner.uid = android.os.Process.myUid();
        call(type, backend, "bindApplication", new Class<?>[]{ApplicationInfo.class}, owner);
        call(type, backend, "installFrameworkCache", new Class<?>[0]);
        return IActivityManager.Stub.asInterface((IBinder) call(type, backend, "asBinder", new Class<?>[0]));
    }
    private static void taskIds() throws Throwable {
        IActivityManager manager = activityManager();
        Object backend = java.lang.reflect.Proxy.getInvocationHandler(manager);
        Activity virtual = (Activity) allocate(Activity.class);
        Activity hosted = (Activity) allocate(Activity.class);
        Binder token = new Binder();
        Field member = Activity.class.getDeclaredField("mToken");
        member.setAccessible(true); member.set(hosted, token);
        check(virtual.getTaskId() == -1 && hosted.getTaskId() == -1, "Unregistered Activity task differs");
        ActivityInfo info = new ActivityInfo(); info.packageName = PACKAGE; info.name = PACKAGE + ".ProbeActivity";
        call(backend.getClass(), backend, "registerActivity",
                new Class<?>[]{IBinder.class, ActivityInfo.class, Intent.class, int.class},
                token, info, new Intent("fixture.launch"), 0);
        check(hosted.getTaskId() == 1, "Registered Activity task missing");
        try {
            call(backend.getClass(), backend, "registerActivity",
                    new Class<?>[]{IBinder.class, ActivityInfo.class, Intent.class, int.class},
                    token, info, new Intent("fixture.launch"), 0);
            throw new AssertionError("Duplicate token accepted");
        } catch (IllegalStateException expected) {}
        FutureTask<Void> queries = new FutureTask<Void>(() -> {
            for (int index = 0; index < 100; index++) {
                check(virtual.getTaskId() == -1 && hosted.getTaskId() == 1, "Concurrent task query differs");
            }
            return null;
        });
        Thread worker = new Thread(queries, "compat-task-query"); worker.start(); queries.get(); worker.join();
        call(manager.getClass(), manager, "activityDestroyed", new Class<?>[]{IBinder.class}, token);
        check(hosted.getTaskId() == -1, "Destroyed Activity retained task");
    }
    private static void taskRouting() throws Throwable {
        IActivityManager manager = activityManager();
        for (boolean nonRoot : new boolean[]{false, true}) {
            try {
                call(manager.getClass(), manager, "moveActivityTaskToBack",
                        new Class<?>[]{IBinder.class, boolean.class}, new Binder(), nonRoot);
                throw new AssertionError("Unknown Activity token accepted");
            } catch (IllegalArgumentException expected) {}
        }
    }
    private static void bitmapJni() throws Throwable {
        String diagnostic = (String) call(Class.forName("SdBridge"), null,
                "checkGraphicsInit", new Class<?>[0]);
        int end = diagnostic.indexOf(" reinit=");
        check(end > 0, "Bitmap JNI diagnostic missing");
        String bitmap = diagnostic.substring(0, end);
        check(!bitmap.contains("[EXC]") && !bitmap.contains("ctor=(nil)") &&
                !bitmap.contains("ctor=0x0"), "Bitmap constructor lookup failed " + bitmap);
    }
    private static void receiverJni() throws Throwable {
        System.setProperty("saidroid.package", PACKAGE);
        System.setProperty("saidroid.apk", "/var/tmp/saildroid-compat/contracts.apk");
        System.setProperty("saidroid.data", "/home/art/data/compat");
        Class<?> endpointType = Class.forName("SdServiceEndpoint");
        int transaction = endpointType.getField("MANIFEST_RECEIVER").getInt(null);
        check(transaction == 9, "Receiver endpoint transaction differs");
        java.lang.reflect.Constructor<?> constructor = endpointType.getDeclaredConstructor();
        constructor.setAccessible(true);
        Object endpoint = constructor.newInstance();
        Method dispatch = endpointType.getDeclaredMethod("onTransact",
                int.class, Parcel.class, Parcel.class, int.class);
        dispatch.setAccessible(true);
        Parcel data = Parcel.obtain(), reply = Parcel.obtain();
        try {
            data.writeInterfaceToken((String) endpointType.getField("DESCRIPTOR").get(null));
            data.writeString("org.saildroid.other");
            data.setDataPosition(0);
            try {
                dispatch.invoke(endpoint, transaction, data, reply, 0);
                throw new AssertionError("Receiver endpoint accepted another package");
            } catch (InvocationTargetException failure) {
                check(failure.getCause() instanceof SecurityException &&
                        "Receiver caller package differs".equals(failure.getCause().getMessage()),
                        "Receiver caller validation failed " + failure.getCause());
            }
        } finally { data.recycle(); reply.recycle(); }
        try {
            call(Class.forName("org.saildroid.host.HostApi"), null, "startReceiverProcess",
                    new Class<?>[]{String.class, String.class, String.class},
                    null, PACKAGE + ".ProbeReceiver", PACKAGE + ":receiver");
            throw new AssertionError("Receiver JNI accepted a missing package");
        } catch (IllegalStateException expected) {
            check("Missing API argument".equals(expected.getMessage()), "Receiver JNI dispatch differs");
        }
        System.setProperty("saidroid.receiver", PACKAGE + ".ProbeReceiver");
        System.setProperty("saidroid.process", PACKAGE + ":receiver");
        Class<?> metadata = Class.forName("SdApkPackage");
        check((PACKAGE + ":receiver").equals(call(metadata, null, "processName", new Class<?>[0])),
                "Declared receiver process missing");
        System.setProperty("saidroid.process", PACKAGE + ":undeclared");
        try {
            call(metadata, null, "processName", new Class<?>[0]);
            throw new AssertionError("Undeclared receiver process accepted");
        } catch (SecurityException expected) {}
    }
    private static void installWindow(boolean start) throws Throwable {
        Class<?> window = Class.forName("SdWindowHost");
        call(window, null, "install", new Class<?>[]{String.class}, System.getenv("ANDROID_ROOT") + "/lib/libsdwindow.so");
        if (start) {
            call(window, null, "start", new Class<?>[]{String.class, String.class}, "Compatibility fixture", PACKAGE);
            Class<?> display = Class.forName("SdDisplayShim");
            int width = display.getField("WIDTH").getInt(null), height = display.getField("HEIGHT").getInt(null);
            int[] pixels = new int[width * height]; Arrays.fill(pixels, 0xff224466);
            call(window, null, "present", new Class<?>[]{int[].class}, (Object) pixels);
        }
    }
    private static void stopWindow() throws Throwable {
        call(Class.forName("SdWindowHost"), null, "stop", new Class<?>[0]);
    }
    private static Object entry(ClassLoader loader) throws Exception {
        Class<?> type = Class.forName("SdActivityHost$Entry");
        java.lang.reflect.Constructor<?> constructor = type.getDeclaredConstructor(); constructor.setAccessible(true);
        Object entry = constructor.newInstance();
        Class<?> activity = Class.forName(PACKAGE + ".ProbeActivity", true, loader);
        field(entry, "activity", activity.getConstructor().newInstance()); field(entry, "token", new Binder());
        ActivityInfo info = new ActivityInfo(); info.packageName = PACKAGE; info.name = activity.getName();
        field(entry, "info", info); field(entry, "stopped", true);
        Field stack = Class.forName("SdActivityHost").getDeclaredField("stack"); stack.setAccessible(true);
        ((ArrayList<Object>) stack.get(null)).add(entry);
        return entry;
    }
    private static Intent parcel(Intent intent) {
        Parcel data = Parcel.obtain();
        try { intent.writeToParcel(data, 0); data.setDataPosition(0); return Intent.CREATOR.createFromParcel(data); }
        finally { data.recycle(); }
    }
    private static void intentLoader(ClassLoader loader) throws Throwable {
        System.setProperty("saidroid.package", PACKAGE);
        System.setProperty("saidroid.apk", "/var/tmp/saildroid-compat/contracts.apk");
        System.setProperty("saidroid.data", "/home/art/data/compat");
        Class<?> services = Class.forName("SdServices");
        call(services, null, "installAll", new Class<?>[0]);
        java.lang.reflect.Constructor<ActivityThread> constructor = ActivityThread.class.getDeclaredConstructor();
        constructor.setAccessible(true);
        ActivityThread thread = constructor.newInstance();
        field(thread, "mInstrumentation", new android.app.Instrumentation());
        Field currentThread = ActivityThread.class.getDeclaredField("sCurrentActivityThread");
        currentThread.setAccessible(true);
        currentThread.set(null, thread);
        installWindow(true);
        try {
            Object current = entry(loader);
            Class<?> payload = Class.forName(PACKAGE + ".Payload", true, loader);
            Parcelable value = (Parcelable) payload.getConstructor(String.class).newInstance("app-owned-value");
            Intent original = new Intent().setComponent(new ComponentName(PACKAGE, PACKAGE + ".ProbeActivity"));
            original.putExtra("payload", value);
            try { parcel(original).getParcelableExtra("payload"); throw new AssertionError("Wrong-loader failure absent"); }
            catch (BadParcelableException expected) {}
            Method launch = Class.forName("SdActivityHost").getDeclaredMethod("launch", Intent.class);
            launch.setAccessible(true);
            try { launch.invoke(null, parcel(original)); }
            catch (InvocationTargetException failure) { throw failure.getCause(); }
            Field activity = current.getClass().getDeclaredField("activity"); activity.setAccessible(true);
            Object receiver = activity.get(current);
            check("app-owned-value".equals(receiver.getClass().getField("received").get(receiver)),
                    "Production onNewIntent failed to deliver the application Parcelable");
        } finally { stopWindow(); }
    }
    public static void run(String group, ClassLoader loader) throws Throwable {
        check(android.os.Process.myUid() != android.os.Process.SYSTEM_UID && android.os.Process.myUid() != 0,
                "Contracts require an ordinary UID distinct from Android system UID");
        check((Boolean) call(Class.forName("SdBridge"), null, "configurePrivateBinder",
                new Class<?>[]{String.class}, "/home/art/runtime/binder/binder"),
                "Private test Binder setup failed");
        if (Looper.myLooper() == null) Looper.prepareMainLooper();
        switch (group) {
            case "api28-public-members":
            case "sip-profile":
            case "rtp-jni":
                call(loader.loadClass("org.saildroid.compat.PublicApiContracts"), null,
                        "run", new Class<?>[]{String.class}, group);
                return;
            case "activity-task": taskIds(); return;
            case "activity-routing": taskRouting(); return;
            case "bitmap-jni": bitmapJni(); return;
            case "receiver-jni": receiverJni(); return;
            case "window-jni": installWindow(false); return;
            case "intent-loader": intentLoader(loader); return;
            default: throw new IllegalArgumentException("Unknown contract group");
        }
    }
}
