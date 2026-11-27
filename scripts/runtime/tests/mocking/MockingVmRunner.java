/** Execute original Mockito APK tests on ART without claiming instrumentation. */
public final class MockingVmRunner {
    public static void main(String[] args) throws Exception {
        System.load(System.getProperty("saidroid.bridge.library"));
        Class<?> bridge=Class.forName("SdBridge");
        String nativeRoot="/var/tmp/saidroid-next-api29-native-20261025-r1";
        String dirs=nativeRoot+"/lib64:"+nativeRoot+"/apex/com.android.runtime.debug/lib64:"
                +nativeRoot+"/apex/com.android.conscrypt/lib64:"+nativeRoot+"/apex/com.android.resolv/lib64";
        if(!(Boolean)bridge.getMethod("loadBionicLibrary",String.class,String.class).invoke(null,
                nativeRoot+"/lib64/libandroid_runtime.so",dirs))throw new AssertionError("Actual Android native bootstrap failed");
        if((Integer)bridge.getMethod("registerFrameworkNatives").invoke(null)<1)
            throw new AssertionError("Actual framework JNI registration failed");
        Class.forName("SdCryptoProvider").getMethod("install").invoke(null);
        Class.forName("SdTls").getMethod("install").invoke(null);
        System.setProperty("dexmaker.dexcache",args[1]);
        dalvik.system.PathClassLoader loader = new dalvik.system.PathClassLoader(
                args[0], null, Object.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?>[] tests = new Class<?>[args.length-2];
        for (int i=2;i<args.length;i++) tests[i-2]=Class.forName(args[i],true,loader);
        Class<?> junit=Class.forName("org.junit.runner.JUnitCore",true,loader);
        // This component probe deliberately uses the original JUnit method runner;
        // AndroidJUnit4 itself needs a live registered Instrumentation instance.
        Class<?> runnerType=Class.forName("org.junit.runner.Runner",true,loader);
        Class<?> block=Class.forName("org.junit.runners.BlockJUnit4ClassRunner",true,loader);
        Class<?> suite=Class.forName("org.junit.runners.Suite",true,loader);
        java.util.List<Object> runners=new java.util.ArrayList<Object>();
        for(Class<?> test:tests)runners.add(block.getConstructor(Class.class).newInstance(test));
        java.lang.reflect.Constructor<?> ctor=suite.getDeclaredConstructor(Class.class,java.util.List.class);
        ctor.setAccessible(true);
        Object all=ctor.newInstance(MockingVmRunner.class,runners);
        Object result=junit.getMethod("run",runnerType).invoke(junit.newInstance(),all);
        Class<?> type=result.getClass();
        int count=(Integer)type.getMethod("getRunCount").invoke(result);
        int failures=(Integer)type.getMethod("getFailureCount").invoke(result);
        for(Object failure:(java.util.List<?>)type.getMethod("getFailures").invoke(result)) {
            System.err.println(failure);
            System.err.println(failure.getClass().getMethod("getTrace").invoke(failure));
        }
        System.out.println("MOCKING_ORIGINAL_VM|cases="+count+"|failures="+failures
                +"|scope=component-diagnostic-not-instrumentation");
        if(count==0||failures!=0)throw new AssertionError("Original Mockito cases failed");
    }
}
