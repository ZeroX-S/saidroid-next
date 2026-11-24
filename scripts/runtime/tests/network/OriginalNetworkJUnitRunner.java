/** Explicit original APK method diagnostic after real platform JNI bootstrap. */
public final class OriginalNetworkJUnitRunner {
    public static void main(String[] args)throws Exception{
        NativeNetworkRegistrationContract.bootstrap(Boolean.parseBoolean(args[0]),args[1]);
        int sdk=Integer.parseInt(args[4]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion()!=sdk)throw new AssertionError("Actual APK SDK not bound");
        ClassLoader loader=new dalvik.system.PathClassLoader(args[2],Object.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?> test=Class.forName(args[3],true,loader),junit=Class.forName("org.junit.runner.JUnitCore",true,loader);
        Class<?> testCase=Class.forName("junit.framework.TestCase",true,loader);
        Object result;
        if(testCase.isAssignableFrom(test))result=junit.getMethod("runClasses",Class[].class).invoke(null,new Object[]{new Class<?>[]{test}});
        else{
            // The original AndroidJUnit4 adapter requires live Instrumentation.
            // Use its standard JUnit method runner for these non-UI methods;
            // this diagnostic is explicitly separate from instrumentation.
            Class<?> runnerType=Class.forName("org.junit.runner.Runner",true,loader);
            Object runner=Class.forName("org.junit.runners.BlockJUnit4ClassRunner",true,loader).getConstructor(Class.class).newInstance(test);
            result=junit.getMethod("run",runnerType).invoke(junit.newInstance(),runner);
        }
        Class<?> type=result.getClass();
        int count=(Integer)type.getMethod("getRunCount").invoke(result),failures=(Integer)type.getMethod("getFailureCount").invoke(result);
        for(Object failure:(java.util.List<?>)type.getMethod("getFailures").invoke(result))
            System.err.println(failure.getClass().getMethod("getTrace").invoke(failure));
        System.out.println("ORIGINAL_NETWORK_VM|tests="+count+"|failures="+failures+"|targetSdk="+sdk);
        if(count==0||failures!=0)throw new AssertionError("Original selected network methods failed");
        // Android's instrumentation process ends after its final callback.
        // Original timeout cases intentionally leave executor workers alive;
        // a standalone VM main must finish its owned process after JUnit ends.
        System.out.flush();System.err.flush();System.exit(0);
    }
}
