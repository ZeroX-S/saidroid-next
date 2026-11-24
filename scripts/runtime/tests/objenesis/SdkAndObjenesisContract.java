/** Platform bootstrap sets real process SDK before creating an app loader. */
public final class SdkAndObjenesisContract {
    public static void main(String[]args)throws Exception {
        System.load(System.getProperty("saidroid.bridge.library"));
        Class<?> bridge=Class.forName("SdBridge");
        String root="/var/tmp/saidroid-next-api29-native-20261025-r1";
        String dirs=root+"/lib64:"+root+"/apex/com.android.runtime.debug/lib64:"
                +root+"/apex/com.android.conscrypt/lib64:"+root+"/apex/com.android.resolv/lib64";
        if(!(Boolean)bridge.getMethod("loadBionicLibrary",String.class,String.class).invoke(null,root+"/lib64/libandroid_runtime.so",dirs))
            throw new AssertionError("Actual Android native bootstrap failed");
        if((Integer)bridge.getMethod("registerFrameworkNatives").invoke(null)<1)
            throw new AssertionError("Actual framework JNI registration failed");
        if(android.os.Build.VERSION.SDK_INT!=29)throw new AssertionError("Actual component SDK properties differ");
        int sdk=Integer.parseInt(args[2]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion()!=sdk)
            throw new AssertionError("Java SDK not bound");
        String boot=System.getProperty("java.boot.class.path");
        String nativeBoot=dalvik.system.VMRuntime.getRuntime().bootClassPath();
        if(!boot.equals(nativeBoot)||!boot.contains("/core-oj.jar"))
            throw new AssertionError("Boot property does not describe real canonical inputs");
        for(String path:boot.split(":"))if(!new java.io.File(path).isFile())throw new AssertionError("Missing physical boot JAR "+path);
        ClassLoader app=new dalvik.system.PathClassLoader(args[0]+":"+args[1],ClassLoader.getSystemClassLoader());
        Class<?> hidden=Class.forName("HiddenApiAppProbe",true,app);
        int expected=sdk>27?3:1;
        int denied=(Integer)hidden.getMethod("run").invoke(null);
        if(denied!=expected)throw new AssertionError("Native SDK policy differs: "+denied+" expected "+expected);
        Class.forName("ObjenesisCompatibilityProbe",true,app).getMethod("run").invoke(null);
        System.out.println("SDK_BINDING=PASS|java_target="+sdk+"|native_denial_bits="+denied+"|boot_paths=actual");
    }
}
