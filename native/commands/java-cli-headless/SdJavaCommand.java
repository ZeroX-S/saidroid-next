import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.Arrays;

/** Headless platform bootstrap for ordinary application-owned Java command classes. */
public final class SdJavaCommand {
    private SdJavaCommand() {}
    public static void main(String[] args) throws Throwable {
        if(args.length==0)throw new IllegalArgumentException("Java main class required");
        dalvik.system.VMRuntime runtime=dalvik.system.VMRuntime.getRuntime();
        int api=Integer.parseInt(System.getProperty("saidroid.framework.api"));
        if(api!=28&&api!=29)throw new IllegalStateException("CLI framework API is unsupported");
        runtime.setTargetSdkVersion(api);
        if(runtime.getTargetSdkVersion()!=api)throw new IllegalStateException("CLI SDK binding failed");
        ClassLoader loader=ClassLoader.getSystemClassLoader();
        if(loader==Object.class.getClassLoader())throw new SecurityException("CLI application loader unavailable");
        // Check ownership without running the requested class initializer. A
        // platform-owned bootstrap must not expose other boot-owned main methods.
        Class<?> target=Class.forName(args[0],false,loader);
        if(target.getClassLoader()!=loader)throw new SecurityException("Java main class must belong to the application loader");
        Method main=target.getMethod("main",String[].class);
        if(main.getDeclaringClass().getClassLoader()!=loader)
            throw new SecurityException("Java main method must belong to the application loader");
        if(!Modifier.isPublic(main.getModifiers())||!Modifier.isStatic(main.getModifiers())||main.getReturnType()!=Void.TYPE)
            throw new NoSuchMethodException("main(String[]) must be public static void");
        // Initialize only the real base JNI, native namespaces and crypto.
        // The application's framework entry also loads fonts/WebView; a CLI
        // command has neither an Application nor a graphics environment.
        String root=System.getenv("ANDROID_ROOT");
        System.load(root+"/lib/libsdbridge.so");
        if(!SdBridge.loadBionicLibrary(root+"/android-libs/libandroid_runtime.so",root+"/android-libs"))
            throw new IllegalStateException("CLI Android native bootstrap failed");
        if(SdBridge.registerFrameworkNatives()!=(api==28?97:104))
            throw new IllegalStateException("CLI framework native registration differs from its component");
        if(android.os.Build.VERSION.SDK_INT!=api)throw new IllegalStateException("CLI framework API differs from its component");
        if(!SdBridge.installClassLoaderNamespaces())throw new IllegalStateException("CLI native namespace backend unavailable");
        SdClassLoaderNamespaces.installNativePathListener();
        SdCryptoProvider.install();
        SdTls.install();
        System.err.println("SD_JAVA_CLI=ready|sdk="+api+"|hidden_api=enabled|user_loader=application|ui=false");
        System.err.println("SD_JAVA_CLI=framework|mode=headless|native=component-private|ui=false");
        try{main.invoke(null,(Object)Arrays.copyOfRange(args,1,args.length));}
        catch(InvocationTargetException failure){throw failure.getCause();}
    }
}
