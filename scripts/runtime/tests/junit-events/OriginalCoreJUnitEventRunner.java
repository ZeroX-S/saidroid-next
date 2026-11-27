/** VM diagnostic driver using the original APK's JUnit and actual callbacks. */
public final class OriginalCoreJUnitEventRunner {
    public static void main(String[] args) throws Exception {
        int sdk = Integer.parseInt(args[2]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if (dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion() != sdk)
            throw new AssertionError("Original target SDK was not bound");
        ClassLoader loader = new dalvik.system.PathClassLoader(
                args[0] + java.io.File.pathSeparator + args[3], Object.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?> test = Class.forName(args[1], true, loader);
        Class<?> junit = Class.forName("org.junit.runner.JUnitCore", true, loader);
        Class<?> listenerType = Class.forName("OriginalJUnitEventListener", true, loader);
        Object listener = listenerType.newInstance();
        Object core = junit.newInstance();
        junit.getMethod("addListener", Class.forName(
                "org.junit.runner.notification.RunListener", true, loader)).invoke(core, listener);
        Object result = junit.getMethod("run", Class[].class).invoke(
                core, new Object[]{new Class<?>[]{test}});
        Class<?> type = result.getClass();
        int count = (Integer) type.getMethod("getRunCount").invoke(result);
        int failures = (Integer) type.getMethod("getFailureCount").invoke(result);
        int ignored = (Integer) type.getMethod("getIgnoreCount").invoke(result);
        int starts = listenerType.getField("started").getInt(listener);
        int finishes = listenerType.getField("finished").getInt(listener);
        int callbackFailures = listenerType.getField("failures").getInt(listener);
        int assumptions = listenerType.getField("assumptions").getInt(listener);
        int callbackIgnored = listenerType.getField("ignored").getInt(listener);
        if (starts != count || finishes != count || callbackFailures != failures
                || callbackIgnored != ignored || failures + assumptions > count)
            throw new AssertionError("Actual JUnit callbacks and result counts disagree");
        for (Object failure : (java.util.List<?>) type.getMethod("getFailures").invoke(result))
            System.err.println(failure.getClass().getMethod("getTrace").invoke(failure));
        System.out.println("ORIGINAL_CORE_EVENT_VM|tests=" + count + "|failures=" + failures
                + "|assumptions=" + assumptions + "|ignored=" + ignored
                + "|passed=" + (count - failures - assumptions) + "|targetSdk=" + sdk);
        System.out.flush(); System.err.flush();
        System.exit(count > 0 && failures == 0 ? 0 : 1);
    }
}
