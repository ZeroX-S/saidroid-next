import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;

/** Serial commands and cancellable timers for one SIP account. */
final class SdSipScheduler {
    private final ScheduledThreadPoolExecutor executor;
    private final Map<Runnable, ScheduledFuture<?>> periodic = new IdentityHashMap<Runnable, ScheduledFuture<?>>();

    SdSipScheduler() {
        executor = new ScheduledThreadPoolExecutor(1, new ThreadFactory() {
            public Thread newThread(Runnable task) {
                Thread thread = new Thread(task, "SailDroid-SIP");
                thread.setDaemon(true);
                return thread;
            }
        });
        executor.setRemoveOnCancelPolicy(true);
    }

    void execute(Runnable task) {
        executor.execute(task);
    }

    ScheduledFuture<?> after(long milliseconds, Runnable task) {
        return executor.schedule(task, milliseconds, TimeUnit.MILLISECONDS);
    }

    synchronized void set(int milliseconds, Runnable task) {
        if (milliseconds <= 0) throw new IllegalArgumentException("Positive SIP timer period required");
        cancel(task);
        periodic.put(task, executor.scheduleWithFixedDelay(task, milliseconds, milliseconds, TimeUnit.MILLISECONDS));
    }

    synchronized void cancel(Runnable task) {
        ScheduledFuture<?> future = periodic.remove(task);
        if (future != null) future.cancel(false);
    }

    synchronized void close() {
        for (ScheduledFuture<?> future : periodic.values()) future.cancel(false);
        periodic.clear();
        executor.shutdownNow();
    }
}
