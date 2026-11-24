/** Original, unmodified official EventLog write/read cases on the real VM.
 * Component diagnostic only: no Android instrumentation/Tradefed claim. */
public final class EventLogVmRunner {
    private static native void install(String liblog);
    public static void main(String[]args)throws Exception {
        System.load(args[0]);install(args[1]);
        final java.util.Set<String> selected=new java.util.HashSet<String>(java.util.Arrays.asList(
            "testWriteEvent","testWriteEventWithOversizeValueLimitElision","testOversizeStringMayBeTruncated",
            "testWriteNullEvent","testReadDataWhenNone","testReadEvents"));
        org.junit.runners.BlockJUnit4ClassRunner runner=new org.junit.runners.BlockJUnit4ClassRunner(Class.forName("android.util.cts.EventLogTest"));
        runner.filter(new org.junit.runner.manipulation.Filter(){
            public boolean shouldRun(org.junit.runner.Description d){return d.isSuite()||selected.contains(d.getMethodName());}
            public String describe(){return "Actual EventLog storage/encoding methods; tag resource lookup not in this VM probe";}
        });
        org.junit.runner.Result result=new org.junit.runner.JUnitCore().run(runner);
        for(org.junit.runner.notification.Failure f:result.getFailures())System.err.println(f.getTrace());
        if(result.getRunCount()!=6||!result.wasSuccessful())throw new AssertionError("Official component cases "+result.getRunCount()+" failures "+result.getFailureCount());
        System.out.println("EVENTLOG_ORIGINAL_VM=PASS|cases=6|scope=component-diagnostic|original_assertions=unchanged");
    }
}
