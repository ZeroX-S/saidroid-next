import android.system.GaiException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructAddrinfo;
import java.net.InetAddress;

public final class CanonicalNumericHostsContract {
    private static int checks;
    private static void check(boolean ok, String why) {
        if (!ok) throw new AssertionError(why);
        checks++;
    }
    private static StructAddrinfo hints(int flags, int family) {
        StructAddrinfo h = new StructAddrinfo();
        h.ai_flags = flags; h.ai_family = family; h.ai_socktype = OsConstants.SOCK_STREAM;
        return h;
    }
    private static InetAddress[] resolve(String host, int flags, int family, int network) throws Exception {
        return Os.android_getaddrinfo(host, hints(flags, family), network);
    }
    private static void reject(String host) throws Exception {
        try {
            resolve(host, OsConstants.AI_NUMERICHOST, OsConstants.AF_UNSPEC, 0);
            throw new AssertionError("Accepted non-numeric IPv4: " + host);
        } catch (GaiException expected) {
            check(expected.error == OsConstants.EAI_NONAME, "Numeric rejection error ABI: " + expected);
        }
    }
    public static void main(String[] args) throws Exception {
        check(Os.getuid() == 65534, "Actual unprivileged process required");
        check(OsConstants.AI_NUMERICHOST == 4, "Translator numeric flag ABI");
        InetAddress[] leading = resolve("0177.00.00.01", OsConstants.AI_NUMERICHOST, OsConstants.AF_INET, 0);
        check(leading.length == 1 && leading[0].getHostAddress().equals("177.0.0.1"), "Decimal leading zero octets");
        InetAddress[] ordinary = resolve("0177.00.00.01", 0, OsConstants.AF_INET, 0);
        check(ordinary.length == 1 && ordinary[0].getHostAddress().equals("177.0.0.1"), "Ordinary decimal leading zero octets");
        for (String legacy : new String[]{"1", "0", "1234", "1.2", "1.2.3", "4294967295", "0x7f.0x0.0x0.0x1", "0256.0.0.1"}) {
            try { resolve(legacy, 0, OsConstants.AF_UNSPEC, 0); throw new AssertionError("Accepted ordinary deprecated numeric " + legacy); }
            catch (GaiException expected) { check(expected.error == OsConstants.EAI_NONAME, "Ordinary numeric error ABI"); }
            try { InetAddress.getByName(legacy); throw new AssertionError("Accepted Java deprecated numeric " + legacy); }
            catch (java.net.UnknownHostException expected) { checks++; }
            check(!InetAddress.isNumeric(legacy), "Deprecated forms not numeric");
            try { InetAddress.parseNumericAddress(legacy); throw new AssertionError("Parsed deprecated numeric " + legacy); }
            catch (IllegalArgumentException expected) { checks++; }
        }
        for (String host : new String[]{"", " ", "\t", "\n", "1", "0", "1234", "1.2", "1.2.3", "1.2.3.4.", "1..2.3", ".1.2.3.4", "1.2.3.-1", "1.2.3.256", "0256.0.0.1", "0x7f.0x0.0x0.0x1", "+1.2.3.4", "1.2.3.4 ", "localhost", "www.google.com", "999999999999999999999.0.0.1"}) reject(host);
        for (int i = 0; i < 1024; i++) {
            int[] octets = {i & 255, (i * 31) & 255, (i * 73) & 255, (i * 137) & 255};
            String text = "000" + octets[0] + ".0" + octets[1] + ".00" + octets[2] + ".0000" + octets[3];
            InetAddress[] actual = resolve(text, OsConstants.AI_NUMERICHOST, OsConstants.AF_INET, 0);
            check(actual.length == 1, "Single stream address expected");
            byte[] bytes = actual[0].getAddress();
            check(bytes.length == 4, "Actual IPv4 bytes");
            for (int j = 0; j < 4; j++) check((bytes[j] & 255) == octets[j], "Actual decimal bytes at " + j);
            check(java.util.Arrays.equals(bytes, resolve(text, 0, OsConstants.AF_INET, 0)[0].getAddress()), "Ordinary actual IPv4 bytes");
            check(InetAddress.isNumeric(text), "Java numeric predicate accepts decimal zeros");
            check(java.util.Arrays.equals(bytes, InetAddress.parseNumericAddress(text).getAddress()), "Java parser actual IPv4 bytes");
            check(java.util.Arrays.equals(bytes, InetAddress.getByName(text).getAddress()), "Java ordinary resolution actual IPv4 bytes");
        }
        check(resolve("::1", OsConstants.AI_NUMERICHOST, OsConstants.AF_INET6, 0)[0].isLoopbackAddress(), "IPv6 loopback");
        check(resolve("::ffff:127.0.0.1", OsConstants.AI_NUMERICHOST, OsConstants.AF_UNSPEC, 0)[0].isLoopbackAddress(), "IPv4 mapped IPv6");
        check(resolve("fe80::1%lo", OsConstants.AI_NUMERICHOST, OsConstants.AF_INET6, 0).length == 1, "Actual scoped IPv6 resolver");
        InetAddress[] local = resolve("localhost", 0, OsConstants.AF_UNSPEC, 0);
        check(local.length > 0, "Non-numeric resolver still available");
        for (InetAddress a : local) check(a.isLoopbackAddress(), "Local host file address");
        try {
            resolve(null, OsConstants.AI_NUMERICHOST | OsConstants.AI_PASSIVE, OsConstants.AF_INET, 0);
            throw new AssertionError("Existing JNI null hostname must throw");
        } catch (NullPointerException expected) { checks++; }
        try {
            resolve("127.0.0.1", OsConstants.AI_NUMERICHOST, OsConstants.AF_INET, 77);
            throw new AssertionError("Non-default Android network must not leak to host resolver");
        } catch (GaiException expected) {
            check(expected.error == OsConstants.EAI_SYSTEM, "Network error ABI");
            check(expected.getCause() instanceof android.system.ErrnoException, "Network errno cause");
            check(((android.system.ErrnoException) expected.getCause()).errno == OsConstants.ENONET, "Non-default ENONET");
        }
        System.out.println("CANONICAL_NUMERIC_HOSTS_CONTRACT=PASS|checks=" + checks + "|uid=" + Os.getuid() + "|EAI_NONAME=" + OsConstants.EAI_NONAME + "|EAI_SYSTEM=" + OsConstants.EAI_SYSTEM);
    }
}
