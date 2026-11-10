/** Validate the actual API28 font and window JNI before creating a surface. */
public final class Api28WindowAbiProbe {
    public static void main(String[] arguments) throws Exception {
        SdRuntime.initializeFramework(true);
        if (android.os.Build.VERSION.SDK_INT != 28) throw new AssertionError("Framework SDK differs");
        if (new android.graphics.Paint().measureText("SailDroid") <= 0) throw new AssertionError("Font metrics unavailable");
        SdWindowHost.install(System.getProperty("saidroid.window.library"));
        System.out.println("API28_WINDOW_ABI=ready|sdk=28|hwui="+SdWindowHost.hardware());
    }
}
