/** Own boundary/lifetime checks; does not replace or alter original CTS tests. */
import android.system.StructTimeval;
import dalvik.system.CloseGuard;
import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.util.Random;

public final class RuntimeUtilityContract {
    private static int checks;
    private static void require(boolean v, String reason) {
        if (!v) throw new AssertionError(reason);
        checks++;
    }
    private static void timeval(long millis) {
        StructTimeval value = StructTimeval.fromMillis(millis);
        require(value.tv_sec == Math.floorDiv(millis, 1000), "Actual floor seconds for " + millis);
        require(value.tv_usec == Math.floorMod(millis, 1000) * 1000, "Actual normalized microseconds for " + millis);
        require(value.toMillis() == millis, "Full long roundtrip for " + millis);
        StructTimeval other = StructTimeval.fromMillis(millis);
        require(value.equals(other) && other.equals(value) && value.hashCode() == other.hashCode(), "Value equality/hash agreement");
        require(!value.equals(null) && !value.equals(Long.valueOf(millis)), "Null/type equality");
    }
    public static void main(String[] args) throws Exception {
        long[] edges = {0, 1, -1, 23, -23, 999, -999, 1000, -1000, 2000, -2000,
                2003, -2003, Long.MIN_VALUE, Long.MIN_VALUE + 1, Long.MAX_VALUE - 1, Long.MAX_VALUE};
        for (long value : edges) timeval(value);
        Random rng = new Random(201L);
        for (int i = 0; i < 10000; i++) timeval(rng.nextLong());
        Constructor<StructTimeval> constructor = StructTimeval.class.getDeclaredConstructor(long.class, long.class);
        constructor.setAccessible(true);
        for (long micros : new long[]{-1, 1000000, Long.MIN_VALUE, Long.MAX_VALUE}) {
            try { constructor.newInstance(0L, micros); throw new AssertionError("Invalid timeval accepted"); }
            catch (InvocationTargetException expected) { require(expected.getCause() instanceof IllegalArgumentException, "Real constructor range rejection"); }
        }
        require(constructor.newInstance(-1L, 0L).tv_usec == 0 && constructor.newInstance(0L, 999999L).tv_usec == 999999, "Valid constructor boundaries");
        final String tag = "own-runtime201-close";
        final int[] reports = {0}, opens = {0}, closes = {0};
        boolean prior = CloseGuard.isEnabled();
        CloseGuard.Reporter reporter = CloseGuard.getReporter();
        CloseGuard.Tracker tracker = CloseGuard.getTracker();
        try {
            CloseGuard.setReporter(new CloseGuard.Reporter() { public void report(String message, Throwable site) {
                if (site != null && site.getMessage().contains(tag)) reports[0]++;
            }});
            CloseGuard.setTracker(new CloseGuard.Tracker() {
                public void open(Throwable site) { if (site != null && site.getMessage().contains(tag)) opens[0]++; }
                public void close(Throwable site) { if (site != null && site.getMessage().contains(tag)) closes[0]++; }
            });
            CloseGuard.setEnabled(false);
            CloseGuard first = CloseGuard.get(), second = CloseGuard.get();
            require(first != second, "Guards created while disabled must have independent lifetimes");
            CloseGuard.setEnabled(true);
            first.open(tag + "-first"); second.open(tag + "-second");
            first.close(); second.warnIfOpen();
            require(opens[0] == 2 && closes[0] == 1 && reports[0] == 1, "Disabled-created guards capture enabled opens independently");
            second.close();
            CloseGuard third = CloseGuard.get(); third.open(tag + "-third");
            CloseGuard.setEnabled(false); third.warnIfOpen();
            require(reports[0] == 2, "A captured open must still report after tracking is disabled");
            third.close(); third.warnIfOpen();
            require(reports[0] == 2 && opens[0] == 3 && closes[0] == 3, "Closed guards must not report and real tracker close events remain paired");
        } finally {
            CloseGuard.setEnabled(prior); CloseGuard.setReporter(reporter); CloseGuard.setTracker(tracker);
        }
        System.out.println("RUNTIME_UTILITY_CONTRACT=PASS|checks=" + checks + "|long_timeval_samples=10017|negative_whole_seconds=true|guard_lifetime=true|global_test_state_restored=true");
    }
}
