import dalvik.system.BlockGuard;
import dalvik.system.VMDebug;
import java.lang.ref.WeakReference;

/** Independent policy ordering, exception and actual collector contract. */
public final class RuntimeGcPolicyContract {
    private static int checks;
    private static void require(boolean ok, String what) {
        ++checks;
        if (!ok) throw new AssertionError(what);
    }
    private static long collections() {
        return Long.parseLong(VMDebug.getRuntimeStat("art.gc.gc-count"));
    }
    private static final class Policy implements BlockGuard.Policy {
        int calls;
        Thread owner = Thread.currentThread();
        RuntimeException denied;
        public void onWriteToDisk() {}
        public void onReadFromDisk() {}
        public void onNetwork() {}
        public void onUnbufferedIO() {}
        public int getPolicyMask() { return 0; }
        public void onExplicitGc() {
            require(Thread.currentThread() == owner, "Policy must run on the caller thread");
            ++calls;
            if (denied != null) throw denied;
        }
    }
    private static WeakReference<Object> abandoned() {
        return new WeakReference<Object>(new byte[256 * 1024]);
    }
    public static void main(String[] args) throws Exception {
        BlockGuard.Policy saved = BlockGuard.getThreadPolicy();
        Policy main = new Policy();
        try {
            BlockGuard.setThreadPolicy(main);
            long initial = collections();
            for (int i = 0; i < 5; ++i) {
                WeakReference<Object> reference = abandoned();
                long before = collections();
                Runtime.getRuntime().gc();
                require(collections() > before, "Original ART collector must actually run");
                require(main.calls == i + 1, "Exactly one explicit GC policy notification");
                require(reference.get() == null, "Real GC must clear an unreachable object");
            }
            final Throwable[] workerFailure = new Throwable[1];
            Thread worker = new Thread(new Runnable() {
                public void run() {
                    BlockGuard.Policy prior = BlockGuard.getThreadPolicy();
                    Policy own = new Policy();
                    try {
                        BlockGuard.setThreadPolicy(own);
                        long before = collections();
                        Runtime.getRuntime().gc();
                        require(own.calls == 1, "Worker must use its own thread policy");
                        require(collections() > before, "Worker still invokes the real collector");
                    } catch (Throwable failure) { workerFailure[0] = failure; }
                    finally { BlockGuard.setThreadPolicy(prior); }
                }
            });
            worker.start(); worker.join();
            if (workerFailure[0] != null) throw new AssertionError(workerFailure[0]);
            require(main.calls == 5, "Worker GC must not notify main thread policy");
            main.denied = new IllegalStateException("contract-denied-explicit-gc");
            long beforeDenied = collections();
            try {
                Runtime.getRuntime().gc();
                throw new AssertionError("Policy exception must propagate");
            } catch (IllegalStateException expected) {
                require(expected == main.denied, "Preserve original policy exception identity");
            }
            require(main.calls == 6, "Denied request invokes policy once");
            require(collections() == beforeDenied, "A denied request must not invoke the collector");
            main.denied = null;
            Runtime.getRuntime().gc();
            require(main.calls == 7, "A later allowed GC still works");
            require(collections() > beforeDenied, "Actual collector works after policy rejection");
            System.out.println("RUNTIME_GC_POLICY_CONTRACT=PASS|checks=" + checks
                    + "|real_gc_delta=" + (collections() - initial)
                    + "|main_callbacks=" + main.calls + "|thread_isolation=true|denial_before_gc=true");
        } finally {
            BlockGuard.setThreadPolicy(saved);
        }
    }
}
