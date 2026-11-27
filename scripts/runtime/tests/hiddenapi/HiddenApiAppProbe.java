/** Loaded by the actual application PathClassLoader, never the boot loader. */
public final class HiddenApiAppProbe {
    public static int run()throws Exception {
        if(HiddenApiAppProbe.class.getClassLoader()==Object.class.getClassLoader())throw new AssertionError("Probe must have application domain");
        if(!"29".equals(String.valueOf(29)))throw new AssertionError("Public API unavailable");
        // These external library APIs are not Android implementation internals.
        if(!org.hamcrest.CoreMatchers.is("value").matches("value"))
            throw new AssertionError("Hamcrest public API unavailable");
        if(junit.runner.Version.id()==null)throw new AssertionError("JUnit public API unavailable");
        int denied=0;
        try{dalvik.system.VMRuntime.class.getDeclaredMethod("setHiddenApiExemptions",String[].class);}
        catch(NoSuchMethodException expected){denied|=1;}
        try{dalvik.system.VMDebug.class.getDeclaredMethod("attachAgent",String.class,ClassLoader.class);}
        catch(NoSuchMethodException expected){denied|=2;}
        return denied;
    }
}
