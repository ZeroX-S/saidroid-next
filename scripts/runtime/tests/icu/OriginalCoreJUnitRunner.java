/** VM diagnostic only: bind the original APK's real SDK before its loader. */
public final class OriginalCoreJUnitRunner {
    public static void main(String[] args) throws Exception {
        int sdk = Integer.parseInt(args[2]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if (dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion() != sdk)
            throw new AssertionError("Original APK target SDK was not bound");
        ClassLoader loader = new dalvik.system.PathClassLoader(args[0], Object.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?> test = Class.forName(args[1], true, loader);
        Class<?> junit = Class.forName("org.junit.runner.JUnitCore", true, loader);
        Object result = junit.getMethod("runClasses", Class[].class).invoke(null, new Object[]{new Class<?>[]{test}});
        Class<?> type = result.getClass();
        int count = (Integer) type.getMethod("getRunCount").invoke(result);
        int failures = (Integer) type.getMethod("getFailureCount").invoke(result);
        for (Object failure : (java.util.List<?>) type.getMethod("getFailures").invoke(result))
            System.err.println(failure.getClass().getMethod("getTrace").invoke(failure));
        System.out.println("ORIGINAL_CORE_JUNIT_VM|tests=" + count + "|failures=" + failures + "|targetSdk=" + sdk);
        System.out.flush();System.err.flush();System.exit(count>0&&failures==0?0:1);
    }
}
