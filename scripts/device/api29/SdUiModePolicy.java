import android.app.UiModeManager;
import android.content.res.Configuration;

/** Proposed NEW owned Android resource policy; not a Sailfish theme observation. */
public final class SdUiModePolicy {
    public static final SdUiModePolicy DEFAULT = new SdUiModePolicy(UiModeManager.MODE_NIGHT_NO);
    private final int nightPolicy;
    SdUiModePolicy(int mode) {
        if (mode == UiModeManager.MODE_NIGHT_AUTO)
            throw new UnsupportedOperationException("No automatic night-mode controller is available");
        if (mode != UiModeManager.MODE_NIGHT_NO && mode != UiModeManager.MODE_NIGHT_YES)
            throw new IllegalArgumentException("Unknown night policy: " + mode);
        nightPolicy = mode;
    }
    public int nightMode() { return nightPolicy; }
    public void applyTo(Configuration config) {
        if (config == null) throw new NullPointerException("owned configuration");
        config.uiMode = (config.uiMode & ~(Configuration.UI_MODE_TYPE_MASK | Configuration.UI_MODE_NIGHT_MASK))
            | Configuration.UI_MODE_TYPE_NORMAL
            | (nightPolicy == UiModeManager.MODE_NIGHT_YES
                ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
    }
    int currentModeType(Configuration config) {
        if (config == null) throw new IllegalStateException("Owned UI configuration is unavailable");
        int type = config.uiMode & Configuration.UI_MODE_TYPE_MASK;
        int night = config.uiMode & Configuration.UI_MODE_NIGHT_MASK;
        if (type != Configuration.UI_MODE_TYPE_NORMAL)
            throw new IllegalStateException("Owned UI mode type is undefined or inconsistent: " + type);
        int expected = nightPolicy == UiModeManager.MODE_NIGHT_YES
            ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO;
        if (night != expected)
            throw new IllegalStateException("Owned effective night configuration differs from policy: " + night);
        return type;
    }
}
