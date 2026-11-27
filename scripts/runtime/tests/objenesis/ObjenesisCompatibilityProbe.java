/** Uses the unchanged original APK's Objenesis implementation, not a replacement. */
public final class ObjenesisCompatibilityProbe {
    public static final class NeverConstruct {
        public static int calls;
        public final int value;
        public NeverConstruct(){calls++;value=73;throw new AssertionError("Constructor ran");}
    }
    public static void run()throws Exception {
        ClassLoader loader=ObjenesisCompatibilityProbe.class.getClassLoader();
        Class<?> platform=Class.forName("org.objenesis.strategy.PlatformDescription",true,loader);
        if(!(Boolean)platform.getMethod("isAndroidOpenJDK").invoke(null))
            throw new AssertionError("Original Objenesis did not recognize actual OpenJDK boot JAR");
        Class<?> objenesis=Class.forName("org.objenesis.ObjenesisStd",true,loader);
        Object allocator=objenesis.newInstance();
        Object value=objenesis.getMethod("newInstance",Class.class).invoke(allocator,NeverConstruct.class);
        if(value.getClass()!=NeverConstruct.class||NeverConstruct.calls!=0||((NeverConstruct)value).value!=0)
            throw new AssertionError("Actual constructor-free allocation failed");
        System.out.println("OBJENESIS_ORIGINAL=PASS|openjdk_detection=actual|constructor_called=false|zero_initialized=true");
    }
}
