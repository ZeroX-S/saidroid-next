import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.SystemClock;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;

/** Bounded read-only ConnMan, route and resolver observation. */
final class SdHostNetworkObservation {
    private final SdConnectivitySnapshot.Identities identities = new SdConnectivitySnapshot.Identities();
    private SdConnectivitySnapshot cached;
    private long sampledAt;

    public synchronized SdConnectivitySnapshot read() throws IOException {
        long now = SystemClock.elapsedRealtime();
        if (cached != null && now - sampledAt < 500) return cached;
        String text = snapshot();
        SdConnectivitySnapshot snapshot = SdConnectivitySnapshot.parse(text, identities);
        try {
            JSONObject services = new JSONObject(text).getJSONObject("services");
            JSONArray values = services.getJSONArray("values");
            for (SdConnectivitySnapshot.Link observed : snapshot.links.values()) {
                // Retain the existing Wi-Fi/ethernet metering policy when
                // ConnMan provides no metering field.
                if (!observed.meteredKnown && observed.type != ConnectivityManager.TYPE_MOBILE)
                    observed.capabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
                if (services.getString("status").equals("read")) {
                    int activeServices = 0;
                    boolean online = false;
                    for (int i = 0; i < values.length(); i++) {
                        JSONObject service = values.getJSONObject(i);
                        String state = service.getString("state");
                        if (service.getString("interface").equals(observed.name)
                                && (state.equals("ready") || state.equals("online"))) {
                            activeServices++;
                            online = state.equals("online");
                        }
                    }
                    if (activeServices == 1 && online && snapshot.active != null && snapshot.active == observed.id)
                        observed.capabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
                }
            }
            cached = snapshot;
            sampledAt = now;
            return snapshot;
        }
        catch (Exception failure) { throw new IOException("Invalid host service observation", failure); }
    }

    private static String snapshot() throws IOException {
        Process child = null;
        long deadline = System.nanoTime() + 1250000000L;
        ProcessBuilder builder = new ProcessBuilder(System.getenv("ANDROID_ROOT") + "/libexec/saildroid-network-snapshot");
        builder.redirectErrorStream(true);
        builder.environment().remove("LD_PRELOAD");
        builder.environment().remove("LD_LIBRARY_PATH");
        try {
            child = builder.start();
            try (InputStream input = child.getInputStream()) {
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                byte[] chunk = new byte[8192];
                while (true) {
                    while (input.available() > 0) {
                        int count = input.read(chunk, 0, Math.min(chunk.length, input.available()));
                        if (count < 0) break;
                        output.write(chunk, 0, count);
                        if (output.size() > 262144) throw new IOException("Host network snapshot output limit");
                    }
                    if (child.waitFor(5, TimeUnit.MILLISECONDS)) {
                        // Drain buffered output after the trusted non-forking helper exits.
                        while (input.available() > 0) {
                            int count = input.read(chunk, 0, Math.min(chunk.length, input.available()));
                            if (count < 0) break;
                            output.write(chunk, 0, count);
                            if (output.size() > 262144) throw new IOException("Host network snapshot output limit");
                        }
                        if (child.exitValue() != 0) throw new IOException("Host network snapshot failed");
                        return output.toString("UTF-8");
                    }
                    if (System.nanoTime() >= deadline) throw new IOException("Host network snapshot deadline");
                }
            }
        } catch (InterruptedException failure) {
            Thread.currentThread().interrupt();
            throw new IOException("Host network snapshot interrupted", failure);
        } finally {
            if (child != null) {
                child.destroyForcibly();
                try { child.waitFor(250, TimeUnit.MILLISECONDS); }
                catch (InterruptedException failure) { Thread.currentThread().interrupt(); }
                try { child.getErrorStream().close(); } catch (IOException ignored) { }
                try { child.getOutputStream().close(); } catch (IOException ignored) { }
            }
        }
    }
}
