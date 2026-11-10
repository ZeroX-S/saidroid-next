/** AudioRecord capture uses the host's physical PulseAudio input. */
public final class SdAudioRecord {
    private static SdAppPermissions permissions;
    private SdAudioRecord() {}

    private static native void nativeInstall();

    public static void install() {
        if (android.os.Build.VERSION.SDK_INT == 28) nativeInstall();
    }

    public static synchronized String authorize() throws Exception {
        if (permissions == null) permissions = new SdAppPermissions(SdApkPackage.APK, SdApkPackage.NAME);
        if (!permissions.holds("android.permission.RECORD_AUDIO")) {
            throw new SecurityException("Recording requires explicit application microphone permission");
        }
        return SdAudio.recordingInput().getString("name");
    }
}
