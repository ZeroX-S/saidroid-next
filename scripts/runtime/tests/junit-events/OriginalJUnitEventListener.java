/** Only this listener is added to the APK loader; no JUnit class is replaced. */
public final class OriginalJUnitEventListener extends org.junit.runner.notification.RunListener {
    public int started, finished, failures, assumptions, ignored;
    public void testStarted(org.junit.runner.Description description) { started++; }
    public void testFinished(org.junit.runner.Description description) { finished++; }
    public void testFailure(org.junit.runner.notification.Failure failure) { failures++; }
    public void testAssumptionFailure(org.junit.runner.notification.Failure failure) {
        assumptions++;
        System.err.println("ORIGINAL_ASSUMPTION|" + failure.getDescription().getDisplayName());
    }
    public void testIgnored(org.junit.runner.Description description) {
        ignored++;
        System.err.println("ORIGINAL_IGNORED|" + description.getDisplayName());
    }
}
