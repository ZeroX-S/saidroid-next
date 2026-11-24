/** Android RTP groups use the host PulseAudio call-media bridge. */
public final class SdRtp {
    private static boolean installed;
    private static SdAppPermissions permissions;
    private static native void nativeInstall();
    private SdRtp() { }

    public static synchronized void install() {
        if (installed || android.os.Build.VERSION.SDK_INT != 28) return;
        try {
            Class.forName("android.net.rtp.AudioGroup");
            System.load(System.getenv("ANDROID_ROOT") + "/lib/libsdvoip.so");
            nativeInstall();
            installed = true;
        } catch (ClassNotFoundException missing) {
            throw new IllegalStateException("Android RTP API unavailable", missing);
        }
    }

    public static synchronized boolean available() { return installed && SdAudio.recordingAvailable(); }

    public static synchronized String authorize(String owner) throws Exception {
        if (!SdApkPackage.NAME.equals(owner)) throw new SecurityException("RTP audio package differs");
        if (permissions == null) permissions = new SdAppPermissions(SdApkPackage.APK, SdApkPackage.NAME);
        if (!permissions.holds("android.permission.INTERNET")) throw new SecurityException("RTP Internet permission required");
        return SdAudioRecord.authorize();
    }
}
