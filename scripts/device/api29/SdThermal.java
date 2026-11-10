import android.os.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.function.Supplier;

/** Read-only DSME thermal severity adapter; does not override host thermal policy. */
public final class SdThermal implements InvocationHandler {
    private static final SdThermal instance = new SdThermal(org.saildroid.host.HostApi::thermalState);
    private final Supplier<String> state;
    private final Binder binder = new Binder();
    private final IThermalService service;
    private final Map<IBinder, IThermalStatusListener> listeners = new HashMap<>();
    private Thread watcher;

    SdThermal(Supplier<String> source) {
        state = Objects.requireNonNull(source);
        service = (IThermalService) Proxy.newProxyInstance(IThermalService.class.getClassLoader(),
                new Class<?>[]{IThermalService.class}, this);
        binder.attachInterface(service, "android.os.IThermalService");
    }
    public static IBinder binder() { return instance.binder; }

    // DSME has fewer severity bands than Android. Low means cold, not overheating.
    // Warning/alert/fatal map conservatively to moderate/severe/shutdown severity.
    static int severity(String value) {
        if ("normal".equals(value) || "low-temp-warning".equals(value)) return Temperature.THROTTLING_NONE;
        if ("warning".equals(value)) return Temperature.THROTTLING_MODERATE;
        if ("alert".equals(value)) return Temperature.THROTTLING_SEVERE;
        if ("fatal".equals(value)) return Temperature.THROTTLING_SHUTDOWN;
        throw new IllegalStateException("Unknown DSME thermal state: " + value);
    }
    private int current() { return severity(state.get()); }

    private boolean register(IThermalStatusListener listener) throws RemoteException {
        Objects.requireNonNull(listener, "listener");
        int initial = current(); // Do not register when the real backend is unavailable.
        synchronized (listeners) {
            if (listeners.containsKey(listener.asBinder())) return false;
            listeners.put(listener.asBinder(), listener);
        }
        try { listener.onStatusChange(initial); }
        catch (RemoteException | RuntimeException failure) {
            unregister(listener);
            throw failure;
        }
        synchronized (listeners) {
            if (!listeners.isEmpty() && watcher == null) {
                watcher = new Thread(() -> watch(initial), "SailDroid-thermal-status");
                watcher.setDaemon(true);
                watcher.start();
            }
        }
        return true;
    }
    private boolean unregister(IThermalStatusListener listener) {
        Objects.requireNonNull(listener, "listener");
        synchronized (listeners) {
            boolean removed = listeners.remove(listener.asBinder()) != null;
            if (listeners.isEmpty() && watcher != null) {
                watcher.interrupt();
                watcher = null;
            }
            return removed;
        }
    }
    private void watch(int previous) {
        Thread own = Thread.currentThread();
        try {
            while (true) {
                Thread.sleep(2000);
                synchronized (listeners) { if (watcher != own || listeners.isEmpty()) return; }
                int value;
                try { value = current(); }
                catch (RuntimeException failure) {
                    System.err.println("SDTHERMAL=unavailable|reason=" + failure);
                    continue; // No fabricated normal-state callback on query failure.
                }
                if (value == previous) continue;
                previous = value;
                List<IThermalStatusListener> snapshot;
                synchronized (listeners) { snapshot = new ArrayList<>(listeners.values()); }
                for (IThermalStatusListener listener : snapshot) {
                    synchronized (listeners) {
                        if (watcher != own || !listeners.containsKey(listener.asBinder())) continue;
                    }
                    try { listener.onStatusChange(value); }
                    catch (RemoteException | RuntimeException failure) { unregister(listener); }
                }
            }
        } catch (InterruptedException stopped) {
            Thread.currentThread().interrupt();
        } finally {
            synchronized (listeners) { if (watcher == own) watcher = null; }
        }
    }
    @Override public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        String name = method.getName();
        if (name.equals("asBinder")) return binder;
        if (name.equals("toString")) return "Sailfish DSME thermal status";
        if (name.equals("hashCode")) return System.identityHashCode(proxy);
        if (name.equals("equals")) return proxy == args[0];
        if (name.equals("getCurrentThermalStatus")) return current();
        if (name.equals("registerThermalStatusListener")) return register((IThermalStatusListener) args[0]);
        if (name.equals("unregisterThermalStatusListener")) return unregister((IThermalStatusListener) args[0]);
        // No sensor/cooling inventory is claimed by the status-only backend.
        throw SdRuntimeDiagnostics.unsupported("Host thermal service", method);
    }
}
