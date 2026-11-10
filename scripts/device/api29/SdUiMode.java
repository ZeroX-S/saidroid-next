import android.app.IUiModeManager;
import android.content.res.Configuration;
import android.content.res.Resources;
import java.util.Objects;
import java.util.function.Supplier;

/** Proposed read-only API29 service over actual owned resource Configuration + policy. */
public final class SdUiMode extends IUiModeManager.Stub {
    private static final SdUiMode INSTANCE = new SdUiMode(SdUiModePolicy.DEFAULT,
        () -> new Configuration(Resources.getSystem().getConfiguration()));
    private final SdUiModePolicy policy;
    private final Supplier<Configuration> configuration;
    SdUiMode(SdUiModePolicy policy, Supplier<Configuration> source) {
        this.policy = Objects.requireNonNull(policy, "policy");
        configuration = Objects.requireNonNull(source, "configuration source");
    }
    public static android.os.IBinder binder() { return INSTANCE; }
    @Override public int getCurrentModeType() { return policy.currentModeType(configuration.get()); }
    @Override public int getNightMode() {
        policy.currentModeType(configuration.get());
        return policy.nightMode(); // policy, not shifted effective uiMode and never inferred AUTO.
    }
    @Override public boolean isUiModeLocked() { return true; }
    @Override public boolean isNightModeLocked() { return true; }
    @Override public void setNightMode(int mode) {
        throw new UnsupportedOperationException("Owned UI policy is read-only; no host night-mode controller");
    }
    @Override public void enableCarMode(int flags) {
        throw new UnsupportedOperationException("Car mode and car-home launch are unsupported");
    }
    @Override public void disableCarMode(int flags) {
        throw new UnsupportedOperationException("Car mode and car-home launch are unsupported");
    }
}
