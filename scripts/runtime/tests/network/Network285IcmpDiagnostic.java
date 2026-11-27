import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructTimeval;
import java.io.FileDescriptor;
import java.net.InetAddress;
import java.net.Inet4Address;
import java.net.InetSocketAddress;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

/** Bounded observation of genuine ICMP sockets; external reachability is not a pass assertion. */
public final class Network285IcmpDiagnostic {
    private static JSONObject error(Throwable failure) throws Exception {
        JSONObject out = new JSONObject();
        out.put("class", failure.getClass().getName());
        out.put("message", String.valueOf(failure.getMessage()));
        if (failure instanceof ErrnoException) out.put("errno", ((ErrnoException) failure).errno);
        return out;
    }
    private static JSONObject inspect(InetAddress address) throws Exception {
        JSONObject out = new JSONObject();
        out.put("address", address.getHostAddress());
        out.put("family", address instanceof Inet4Address ? 4 : 6);
        out.put("loopback", address.isLoopbackAddress());
        long begin = System.nanoTime();
        try { out.put("java_icmp_reachable", address.isReachableByICMP(1000)); }
        catch (Throwable failure) { out.put("java_icmp_error", error(failure)); }
        out.put("java_elapsed_ms", (System.nanoTime() - begin) / 1000000L);
        FileDescriptor fd = null;
        String step = "socket";
        try {
            boolean ipv4 = address instanceof Inet4Address;
            fd = Os.socket(ipv4 ? OsConstants.AF_INET : OsConstants.AF_INET6,
                    OsConstants.SOCK_DGRAM, ipv4 ? OsConstants.IPPROTO_ICMP : OsConstants.IPPROTO_ICMPV6);
            out.put("socket_opened", true);
            step = "timeout";
            Os.setsockoptTimeval(fd, OsConstants.SOL_SOCKET, OsConstants.SO_RCVTIMEO,
                    StructTimeval.fromMillis(1000));
            byte[] request = new byte[] { (byte)(ipv4 ? 8 : 128), 0, 0, 0, 0, 0, 0x12, 0x34 };
            step = "sendto";
            out.put("sent", Os.sendto(fd, request, 0, request.length, 0, address, 0));
            step = "getsockname";
            InetSocketAddress local = (InetSocketAddress) Os.getsockname(fd);
            out.put("local", local.toString());
            out.put("kernel_identifier", local.getPort());
            byte[] response = new byte[256];
            InetSocketAddress source = new InetSocketAddress(0);
            step = "recvfrom";
            int received = Os.recvfrom(fd, response, 0, response.length, 0, source);
            out.put("received", received);
            out.put("source", source.toString());
            JSONArray header = new JSONArray();
            for (int i = 0; i < Math.min(received, 16); ++i) header.put(response[i] & 255);
            out.put("header", header);
            boolean matches = received == request.length && address.equals(source.getAddress())
                    && (response[0] & 255) == (ipv4 ? 0 : 129)
                    && (response[4] & 255) == (local.getPort() >>> 8)
                    && (response[5] & 255) == (local.getPort() & 255)
                    && response[6] == request[6] && response[7] == request[7];
            out.put("raw_reply_matches", matches);
        } catch (Throwable failure) {
            out.put("raw_error_step", step);
            out.put("raw_error", error(failure));
        } finally {
            if (fd != null) try { Os.close(fd); } catch (Throwable failure) { out.put("close_error", error(failure)); }
        }
        return out;
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("expected uid and host");
        int expectedUid = Integer.parseInt(args[0]);
        if (Os.getuid() != expectedUid || Os.geteuid() != expectedUid)
            throw new SecurityException("actual ordinary UID differs");
        JSONObject out = new JSONObject();
        out.put("uid", Os.getuid());
        out.put("uname_nodename", Os.uname().nodename);
        out.put("host", args[1]);
        out.put("sdk", android.os.Build.VERSION.SDK_INT);
        out.put("no_new_privs", Os.prctl(39, 0, 0, 0, 0));
        JSONArray rows = new JSONArray();
        try {
            InetAddress[] addresses = InetAddress.getAllByName(args[1]);
            out.put("resolved_count", addresses.length);
            if (addresses.length > 8) throw new IllegalStateException("bounded diagnostic refuses more than 8 addresses");
            for (InetAddress address : addresses) rows.put(inspect(address));
        } catch (Throwable failure) { out.put("resolution_error", error(failure)); }
        out.put("results", rows);
        System.out.println("NETWORK285_ICMP_OBSERVATION=" + out.toString());
    }
}
