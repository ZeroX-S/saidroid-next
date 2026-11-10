package org.saildroid.host;

/** Native host-session APIs. No shell parsing or runtime interpreter. */
public final class HostApi {
    static { System.load(System.getenv("ANDROID_ROOT")+"/lib/libsdhostapi.so"); }
    private HostApi(){}
    public static native void ready();
    public static native String audioSnapshot();
    public static native int ringerMode();
    public static native int wifiEnabledState();
    public static native void openApplication(String packageName);
    public static native void startService(String packageName,String service,String process);
    public static native void startActivityProcess(String packageName,String activity,String process);
    public static native void startProviderProcess(String packageName,String provider,String process);
    public static native void startReceiverProcess(String packageName,String receiver,String process);
    public static native void activateSelf();
    public static native String state(String packageName);
    public static native String mceString(String method);
    public static native String thermalState();
    public static native boolean mceBoolean(String method);
}
