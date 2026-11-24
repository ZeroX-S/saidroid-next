/** Process-private Android MediaPlayer backend. No Android media-server dependency. */
public final class SdMediaPlayer {
    private static boolean installed;
    private static native void nativeInstall();
    public static synchronized void installBackend() {
        if (installed) return;
        System.load(System.getenv("ANDROID_ROOT")+"/lib/libsdmediaplayer-host.so");
        nativeInstall();
        installed = true;
    }
    public static void install() {
        installBackend();
        SdCamera.install();SdSurfaceViews.install();
    }
}
