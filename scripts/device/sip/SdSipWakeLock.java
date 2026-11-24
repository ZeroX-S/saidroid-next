import android.os.SystemClock;
import java.util.HashSet;
import java.util.concurrent.ScheduledFuture;

/** MCE CPU keepalive while SIP signaling or call media is active. */
final class SdSipWakeLock {
    private final SdSipScheduler scheduler;
    private final HashSet<Object> holders = new HashSet<Object>();
    private final String session = "saildroid-sip-" + android.os.Process.myPid();
    private long deadline;
    private boolean held;
    private ScheduledFuture<?> renewal;

    SdSipWakeLock(SdSipScheduler scheduler) { this.scheduler = scheduler; }

    synchronized void acquire(long milliseconds) {
        deadline = Math.max(deadline, SystemClock.elapsedRealtime() + milliseconds);
        update();
    }

    synchronized void acquire(Object owner) { holders.add(owner); update(); }
    synchronized void release(Object owner) { holders.remove(owner); update(); }

    private synchronized void update() {
        if (renewal != null) { renewal.cancel(false); renewal = null; }
        boolean needed = !holders.isEmpty() || deadline > SystemClock.elapsedRealtime();
        try {
            if (needed) {
                int period = org.saildroid.host.HostApi.acquireWakeLock(session, false, held);
                held = true;
                renewal = scheduler.after(Math.max(100, Math.min(period * 500L,
                        holders.isEmpty() ? deadline - SystemClock.elapsedRealtime() : period * 500L)),
                        new Runnable() { public void run() { update(); } });
            } else if (held) {
                org.saildroid.host.HostApi.releaseWakeLock(session, false);
                held = false;
            }
        } catch (RuntimeException unavailable) {
            System.err.println("SDSIP=cpu_keepalive_unavailable|type=" + unavailable.getClass().getName());
        }
    }

    synchronized void close() { holders.clear(); deadline = 0; update(); }
}
