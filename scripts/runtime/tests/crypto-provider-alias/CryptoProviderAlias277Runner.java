/** Trusted VM-only target-SDK setup, never installed in the component. */
public final class CryptoProviderAlias277Runner {
    public static void main(String[] args) throws Exception {
        int sdk = Integer.parseInt(args[0]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if (dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion() != sdk)
            throw new AssertionError("Target SDK readback");
        String root = System.getenv("ANDROID_ROOT");
        System.load(root + "/lib/libsdbridge.so");
        Class<?> bridge = Class.forName("SdBridge");
        if (!(Boolean) bridge.getMethod("loadBionicLibrary", String.class, String.class).invoke(
                null, root + "/android-libs/libandroid_runtime.so", root + "/android-libs"))
            throw new AssertionError("Actual framework native bootstrap");
        int registered = (Integer) bridge.getMethod("registerFrameworkNatives").invoke(null);
        if (registered != 104) throw new AssertionError("Actual framework JNI count: " + registered);
        if (!(Boolean) bridge.getMethod("installClassLoaderNamespaces").invoke(null))
            throw new AssertionError("Actual native load namespaces");
        Class.forName("SdClassLoaderNamespaces").getMethod("installNativePathListener").invoke(null);
        Class.forName("SdCryptoProvider").getMethod("install").invoke(null);
        Class.forName("SdTls").getMethod("install").invoke(null);
        System.out.println("ALIAS277_BOOTSTRAP=ready|jni=" + registered + "|ui=false");
        CryptoProviderAlias277Contract.run(Boolean.parseBoolean(args[1]));
        System.out.flush();
        System.err.flush();
        System.exit(0);
    }
}
