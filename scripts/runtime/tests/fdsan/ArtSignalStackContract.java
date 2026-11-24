/** Checks actual ART-created signal stacks and kernel mappings, without replacing them. */
public final class ArtSignalStackContract {
    private static native int exerciseNativeThreads();
    public static void run() {
        System.load(System.getProperty("saidroid.test.signal-stack.helper"));
        int checks=exerciseNativeThreads();
        if(checks!=64*5) throw new AssertionError("Guarded stack lifecycle checks: "+checks);
        System.out.println("ART_SIGNAL_STACK_CONTRACT=PASS|threads=64|checks="+checks
                +"|minimum=262144|guards=2|detach=unmapped");
    }
}
