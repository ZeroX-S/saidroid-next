import android.os.SystemProperties;
import java.util.TimeZone;
import org.apache.harmony.luni.internal.util.TimezoneGetter;

/** Supplies Android's default timezone from Sailfish's selected IANA zone. */
public final class SdTimeZone extends TimezoneGetter implements Runnable {
    private static volatile String current;
    private static final SdTimeZone instance = new SdTimeZone();

    private static native String refreshNative();

    public static synchronized void install() {
        if (current != null) return;
        String identifier = refreshNative();
        if (identifier == null) {
            identifier = SystemProperties.get("persist.sys.timezone", "UTC");
            System.err.println("SDTIMEZONE=unavailable|source=host-localtime|fallback=" + identifier);
        }
        current = identifier;
        if (TimezoneGetter.getInstance() == null) TimezoneGetter.setInstance(instance);
        System.setProperty("user.timezone", identifier);
        TimeZone.setDefault(null);
        Thread watcher = new Thread(instance, "Saildroid timezone");
        watcher.setDaemon(true);
        watcher.start();
        TimeZone zone = TimeZone.getDefault();
        System.err.println("SDTIMEZONE=ready|id=" + identifier + "|java_id=" + zone.getID()
                + "|offset_ms=" + zone.getOffset(System.currentTimeMillis()) + "|source=host-localtime");
    }

    @Override
    public String getId() {
        return current;
    }

    @Override
    public void run() {
        while (!Thread.currentThread().isInterrupted()) {
            try {
                Thread.sleep(5000);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                return;
            }
            try {
                String identifier = refreshNative();
                if (identifier != null && !identifier.equals(current)) {
                    current = identifier;
                    System.setProperty("user.timezone", identifier);
                    TimeZone.setDefault(null);
                    SdServices.notifyTimeZoneChanged(identifier);
                    System.err.println("SDTIMEZONE=changed|id=" + identifier);
                }
            } catch (Exception failure) {
                System.err.println("SDTIMEZONE=refresh_failed|type=" + failure.getClass().getName());
            }
        }
    }
}
