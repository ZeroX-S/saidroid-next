/* SdServices —— 把系统服务换成进程内实现。
 *
 * 单进程运行时没有 system_server，也没有 binder servicemanager。
 * 框架里所有 ServiceManager.getService("xxx") 都会拿不到（甚至在 /dev/binder 上
 * 卡住或 abort）。这里做两件事：
 *
 *   1. 把 ServiceManager.sServiceManager 换成本地实现，它只查一张名字->binder 的表，
 *      查不到就返回 null —— 绝不碰 /dev/binder。
 *   2. 把我们自己的服务桩注册进去：package / window / display / mount。
 *      这些桩都是 Binder 子类，本地调用时 IMountService.Stub.asInterface() 会直接
 *      返回桩本身，不会走一次 IPC。
 *
 * 另外仍然把几个已经缓存过的单例直接注入一遍（兜底）：有些框架代码在第一次访问时
 * 就把 ServiceManager 的结果存到静态字段里了。
 */
import android.os.IBinder;

import java.lang.reflect.Field;

public final class SdServices {

    private SdServices() {
    }

    private static boolean installed = false;
    private static SdActivityManagerService activityManager;

    public static String installAll() throws Exception {
        if (!installed) {
            installServiceManager();
            activityManager = new SdActivityManagerService();
            installed = true;
        }
        activityManager.installFrameworkCache();
        register("activity", activityManager.asBinder());
        register("package", SdPackageManagerService.binder());
        register("window", SdWindowManager.binder());
        register("input", SdInputManager.binder());
        register("input_method", SdInputMethods.binder());
        register("textservices", SdTextServices.binder());
        register("appwidget", SdAppWidgets.binder());
        register("display", SdDisplayShim.binder());
        register("mount", SdStorageManager.binder());
        register("user", SdUsers.binder());
        register("content", SdContentService.binder());
        register("connectivity", SdConnectivity.binder());
        register("netstats", SdNetworkStats.binder());
        register("wifi", SdWifi.binder());
        register("trust", SdKeyguard.binder());
        register("notification", SdNotificationPolicy.binder());
        register("audio", SdAudio.binder());
        register("power", SdPower.binder());
        register("thermalservice", SdThermal.binder());
        register("deviceidle", SdDeviceIdle.binder());
        register("batterystats", SdBattery.stats());
        register("batteryproperties", SdBattery.properties());

        StringBuilder sb = new StringBuilder("服务表: ");
        sb.append("activity/package/window/display/mount");

        // 兜底注入（这些静态字段可能在服务表生效前就被赋值成 null 了）
        sb.append(" | ").append(SdDisplayShim.install());
        sb.append(" | ").append(SdDisplayShim.installWindowManager());
        sb.append(" | ").append(SdDisplayShim.installPackageManager());
        return sb.toString();
    }

    public static SdActivityManagerService activityManager(){if(!installed)throw new IllegalStateException("Services not installed");return activityManager;}

    static void notifyTimeZoneChanged(String identifier) throws Exception {
        if (!installed) return;
        android.content.Intent intent = new android.content.Intent(android.content.Intent.ACTION_TIMEZONE_CHANGED);
        intent.putExtra("time-zone", identifier);
        activityManager.deliverBroadcast(intent, null, 0, null, null, null,
                android.os.Process.myUid() / 100000, false);
    }

    public static void bindApplication(android.content.pm.ApplicationInfo info) {
        if (!installed) throw new IllegalStateException("Services are not installed");
        android.content.pm.ApplicationInfo current=new android.content.pm.ApplicationInfo(info);current.processName=SdApkPackage.processName();activityManager.bindApplication(current);
    }

    public static void setActivityResumed(boolean resumed) {
        if (!installed) throw new IllegalStateException("Services are not installed");
        activityManager.setActivityResumed(resumed);
    }

    public static void registerActivity(IBinder token, android.content.pm.ActivityInfo info,
                                        android.content.Intent intent, int displayId) {
        if (!installed) throw new IllegalStateException("Services are not installed");
        activityManager.registerActivity(token, info, intent, displayId);
    }

    public static android.app.ActivityManager.TaskDescription getActivityTaskDescription(IBinder token) {
        if (!installed) throw new IllegalStateException("Services are not installed");
        return activityManager.getActivityTaskDescription(token);
    }

    private static void installServiceManager() throws Exception {
        Class<?> sm = Class.forName("android.os.ServiceManager");
        Field f = sm.getDeclaredField("sServiceManager");
        f.setAccessible(true);
        f.set(null, SdServiceManagerStub.service());
    }

    private static void register(String name, IBinder binder) {
        SdServiceManagerStub.put(name, binder);
        try {
            Class<?> sm = Class.forName("android.os.ServiceManager");
            Field c = sm.getDeclaredField("sCache");
            c.setAccessible(true);
            Object cache = c.get(null);
            if (cache instanceof java.util.HashMap) {
                @SuppressWarnings("unchecked")
                java.util.HashMap<String, IBinder> m = (java.util.HashMap<String, IBinder>) cache;
                m.put(name, binder);
            }
        } catch (Throwable ignored) {
            /* 缓存塞不进也没关系，走 sServiceManager 一样能查到 */
        }
    }
}
