import android.os.*;
import java.lang.reflect.*;
import java.util.IdentityHashMap;
import java.util.Map;

/** Sailfish power queries and MCE-owned CPU/display wake locks. */
public final class SdPower implements InvocationHandler {
    private static final SdPower instance=new SdPower();
    private final Binder binder=new Binder();private final IPowerManager service;
    private final Map<IBinder, WakeLock> wakeLocks = new IdentityHashMap<IBinder, WakeLock>();
    private SdAppPermissions permissions;
    private long serial;
    private long renewalMillis = 5000;
    private Thread renewalThread;
    private static final class WakeLock {
        final String session;
        final boolean screen;
        WakeLock(String session, boolean screen) {
            this.session = session;
            this.screen = screen;
        }
    }
    private SdPower(){service=(IPowerManager)Proxy.newProxyInstance(IPowerManager.class.getClassLoader(),new Class<?>[]{IPowerManager.class},this);binder.attachInterface(service,"android.os.IPowerManager");}
    public static IBinder binder(){return instance.binder;}
    public static boolean interactive(){String state=SdHostState.string("get_display_status");if(state.equals("on")||state.equals("dim")||state.equals("power up"))return true;if(state.equals("off")||state.equals("lpm_on")||state.equals("lpm_off")||state.equals("power down"))return false;throw new IllegalStateException("Unknown MCE display state: "+state);}
    public static boolean powerSave(){return SdHostState.bool("get_psm_state");}
    private void requireWakeLockPermission() throws Exception {
        if (permissions == null) permissions = new SdAppPermissions(SdApkPackage.APK, SdApkPackage.NAME);
        if (!permissions.holds("android.permission.WAKE_LOCK")) throw new SecurityException("Wake lock permission required");
    }
    private void requireAttribution(WorkSource source) {
        if (source != null && !source.isEmpty()) {
            if (!permissions.holds("android.permission.UPDATE_DEVICE_STATS")) throw new SecurityException("Wake lock attribution permission required");
            throw new UnsupportedOperationException("Host wake lock attribution unavailable");
        }
    }
    private static boolean supportedLevel(int level) {
        return level == PowerManager.PARTIAL_WAKE_LOCK || level == PowerManager.SCREEN_BRIGHT_WAKE_LOCK
                || level == PowerManager.FULL_WAKE_LOCK;
    }
    private void acquire(IBinder token, int flags, String tag, String owner, WorkSource source) throws Exception {
        requireWakeLockPermission();
        if (token == null || tag == null) throw new IllegalArgumentException("Wake lock token and tag required");
        if (!SdApkPackage.NAME.equals(owner)) throw new SecurityException("Wake lock package differs");
        requireAttribution(source);
        int level = flags & PowerManager.WAKE_LOCK_LEVEL_MASK;
        if (!supportedLevel(level) || (flags & (PowerManager.ACQUIRE_CAUSES_WAKEUP | PowerManager.ON_AFTER_RELEASE)) != 0) {
            throw new UnsupportedOperationException("Host wake lock level or display transition unavailable");
        }
        boolean screen = level != PowerManager.PARTIAL_WAKE_LOCK;
        WakeLock previous = wakeLocks.get(token);
        if (previous != null) {
            if (previous.screen != screen) throw new IllegalArgumentException("Held wake lock level differs");
            return;
        }
        WakeLock lock = new WakeLock("saildroid-" + android.os.Process.myPid() + "-" + (++serial), screen);
        int period = org.saildroid.host.HostApi.acquireWakeLock(lock.session, screen, false);
        wakeLocks.put(token, lock);
        renewalMillis = Math.min(renewalMillis, period * 500L);
        if (renewalThread == null) {
            renewalThread = new Thread(new Runnable() {
                public void run() {
                    for (;;) synchronized (SdPower.this) {
                        try {
                            while (wakeLocks.isEmpty()) SdPower.this.wait();
                            SdPower.this.wait(renewalMillis);
                            for (WakeLock held : wakeLocks.values()) {
                                try {
                                    int period = org.saildroid.host.HostApi.acquireWakeLock(held.session, held.screen, true);
                                    renewalMillis = Math.min(renewalMillis, period * 500L);
                                } catch (RuntimeException failure) {
                                    System.err.println("SDPOWER=wake_lock_renew_failed|type=" + failure.getClass().getName());
                                }
                            }
                        } catch (InterruptedException interrupted) {}
                    }
                }
            }, "SailDroid-wake-locks");
            renewalThread.setDaemon(true);
            renewalThread.start();
        }
        notifyAll();
        System.err.println("SDPOWER=wake_lock_acquired|level=" + level + "|screen=" + screen + "|owners=" + wakeLocks.size() + "|backend=mce");
    }
    private void release(IBinder token) throws Exception {
        requireWakeLockPermission();
        if (token == null) throw new IllegalArgumentException("Wake lock token required");
        WakeLock lock = wakeLocks.get(token);
        if (lock == null) return;
        boolean cancelScreen = lock.screen;
        for (WakeLock other : wakeLocks.values()) if (other != lock && other.screen) cancelScreen = false;
        org.saildroid.host.HostApi.releaseWakeLock(lock.session, cancelScreen);
        wakeLocks.remove(token);
        if (wakeLocks.isEmpty()) renewalMillis = 5000;
        notifyAll();
        System.err.println("SDPOWER=wake_lock_released|owners=" + wakeLocks.size() + "|backend=mce");
    }
    @Override public synchronized Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String name=method.getName();if(name.equals("asBinder"))return binder;if(name.equals("toString"))return "Sailfish display and power state";if(name.equals("hashCode"))return System.identityHashCode(proxy);if(name.equals("equals"))return proxy==args[0];
        if(name.equals("isInteractive"))return interactive();
        if(name.equals("isPowerSaveMode"))return powerSave();
        if(name.equals("getPowerSaveState"))return new PowerSaveState.Builder().setGlobalBatterySaverEnabled(powerSave()).setBatterySaverEnabled(false).build();
        if(name.equals("isWakeLockLevelSupported"))return supportedLevel((Integer) args[0]);
        if(name.equals("acquireWakeLock")){acquire((IBinder)args[0],(Integer)args[1],(String)args[2],(String)args[3],(WorkSource)args[4]);return null;}
        if(name.equals("acquireWakeLockWithUid")){
            int uid=(Integer)args[4];if(uid!=-1&&uid!=android.os.Process.myUid())throw new SecurityException("Wake lock UID differs");
            acquire((IBinder)args[0],(Integer)args[1],(String)args[2],(String)args[3],null);return null;
        }
        if(name.equals("releaseWakeLock")){release((IBinder)args[0]);return null;}
        if(name.equals("updateWakeLockWorkSource")){
            requireWakeLockPermission();requireAttribution((WorkSource)args[1]);
            if(!wakeLocks.containsKey((IBinder)args[0]))throw new IllegalArgumentException("Unknown wake lock token");return null;
        }
        if(name.equals("isDeviceIdleMode")||name.equals("isLightDeviceIdleMode"))return false; // This runtime owns no Android Doze policy engine.
        throw SdRuntimeDiagnostics.unsupported("Host power service",method);
    }
}
