/** Internal listener self-check, deliberately includes one failure. */
public final class EventAccountingFixture {
    @org.junit.Test public void passing() {}
    @org.junit.Test public void failing() { throw new AssertionError("Deliberate listener negative control"); }
    @org.junit.Test @org.junit.Ignore public void ignored() { throw new AssertionError("Ignored method executed"); }
    @org.junit.Test public void assumption() throws Throwable {
        try {
            Class.forName("org.junit.Assume").getMethod("assumeTrue", boolean.class).invoke(null, false);
        } catch (java.lang.reflect.InvocationTargetException expected) {
            throw expected.getCause();
        }
    }
}
