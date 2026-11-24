/** Trusted platform bootstrap launches a separate real application loader. */
public final class HiddenApiContract {
    public static void main(String[]args)throws Exception {
        if(HiddenApiContract.class.getClassLoader()!=Object.class.getClassLoader())throw new AssertionError("Platform caller must be on boot classpath");
        ClassLoader app=new dalvik.system.PathClassLoader(args[0],ClassLoader.getSystemClassLoader());
        Class<?> probe=Class.forName("HiddenApiAppProbe",true,app);
        if(probe.getClassLoader()!=app)throw new AssertionError("Application probe loader mismatch");
        java.lang.reflect.Method run=probe.getDeclaredMethod("run");
        int expected=Integer.parseInt(args[1]);int actual=(Integer)run.invoke(null);
        if(actual!=expected)throw new AssertionError("Application denial bits="+actual+" expected="+expected);
        // Platform access must remain available without installing exemptions.
        if(dalvik.system.VMRuntime.class.getDeclaredMethod("setHiddenApiExemptions",String[].class)==null)
            throw new AssertionError("Platform internal reflection unavailable");
        int after=(Integer)run.invoke(null);
        if(after!=expected)throw new AssertionError("Trusted lookup leaked application permission");
        System.out.println("HIDDENAPI_CONTRACT=PASS|denied_bits="+actual+"|public_api=available|platform_access=available|permission_leak=false");
    }
}
