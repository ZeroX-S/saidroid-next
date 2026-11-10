/** Process-private Android MediaPlayer backend. No Android media-server dependency. */
public final class SdMediaPlayer {
    private static native void nativeInstall();
    public static void install() {
        System.load(System.getenv("ANDROID_ROOT")+"/lib/libsdmediaplayer-host.so");
        nativeInstall();
        SdCamera.install();SdSurfaceViews.install();
    }
}
