import android.system.Os;
import android.system.OsConstants;
import android.system.ErrnoException;
import java.io.File;
import java.io.FileDescriptor;
import java.net.InetAddress;
import java.nio.file.Files;
import java.nio.file.Paths;
import org.json.JSONArray;
import org.json.JSONObject;

/** Observes public reachability in a bounded actual phone process-local ICMP-denial fixture. */
public final class Network287PhoneReachabilityContract {
    public static void main(String[] args) throws Exception {
        if (args.length != 1 || Os.getuid() != 100000 || Os.geteuid() != 100000
                || Os.prctl(39, 0, 0, 0, 0) != 1 || android.os.Build.VERSION.SDK_INT != 29)
            throw new SecurityException("Expected genuine ordinary UID100000/API29/no_new_privs");
        String root = System.getenv("ANDROID_ROOT");
        String maps = new String(Files.readAllBytes(Paths.get("/proc/self/maps")), "UTF-8");
        if (!maps.contains(root + "/lib/libart.so") || !maps.contains(root + "/lib/libjavacore.so"))
            throw new IllegalStateException("Actual ART/LinuxJNI owner differs");
        int images = 0;
        for (String name : new String[] {"boot.art", "boot-apache-xml-hostdex.art", "boot-apachehttp-hostdex.art",
                "boot-bouncycastle-hostdex.art", "boot-core-junit-hostdex.art", "boot-core-libart.art",
                "boot-junit-runner-hostdex.art", "boot-okhttp-hostdex.art", "boot-wolfssljni-hostdex.art"}) {
            if (!maps.contains(root + "/system/framework/arm64/" + name))
                throw new IllegalStateException("Actual boot image missing: " + name);
            ++images;
        }
        JSONArray results = new JSONArray();
        int before = new File("/proc/self/fd").list().length;
        for (String literal : new String[] {"127.0.0.1", "::1", "192.0.2.1", "2001:db8::1"}) {
            InetAddress address = InetAddress.getByName(literal);
            JSONObject row = new JSONObject();
            row.put("address", literal);
            FileDescriptor fd = null;
            try {
                fd = Os.socket(literal.indexOf(':') >= 0 ? OsConstants.AF_INET6 : OsConstants.AF_INET,
                        OsConstants.SOCK_DGRAM, literal.indexOf(':') >= 0 ? OsConstants.IPPROTO_ICMPV6 : OsConstants.IPPROTO_ICMP);
                row.put("raw_socket_opened", true);
            } catch (ErrnoException failure) { row.put("raw_socket_errno", failure.errno); }
            finally { if (fd != null) Os.close(fd); }
            JSONArray calls = new JSONArray();
            for (int i = 0; i < (address.isLoopbackAddress() ? 16 : 1); ++i) {
                JSONObject call = new JSONObject();
                long start = System.nanoTime();
                try { call.put("reachable", address.isReachable(1000)); }
                catch (Throwable failure) {
                    call.put("error", failure.getClass().getName());
                    call.put("message", String.valueOf(failure.getMessage()));
                }
                call.put("elapsed_ms", (System.nanoTime() - start) / 1000000L);
                calls.put(call);
            }
            row.put("calls", calls);
            results.put(row);
        }
        JSONObject out = new JSONObject();
        out.put("uid", Os.getuid());out.put("images", images);
        out.put("fd_before", before);out.put("fd_after", new File("/proc/self/fd").list().length);
        out.put("results", results);out.put("label", args[0]);
        System.out.println("NETWORK287_PHONE_REACHABILITY=" + out.toString());
    }
}
