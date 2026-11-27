import android.content.pm.ApplicationInfo;
import android.system.Os;
import android.system.StructStat;
import java.io.File;
import java.lang.reflect.InvocationTargetException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Properties;

/** Startup configuration and unchanged runtime cache validation, at an ordinary UID. */
public final class ApplicationCacheStartupContract {
    private static int checks;
    private static void check(boolean value, String reason) {
        checks++;
        if (!value) throw new AssertionError(reason);
    }
    public static void run(String mode) throws Exception {
        check(Os.getuid() == 65534, "actual ordinary process UID");
        Path data = Paths.get(System.getenv("SAILDROID_DATA_DIR"));
        Path code = data.resolve("code_cache"), cache = code.resolve("dexmaker");
        ApplicationInfo info = new ApplicationInfo();
        info.uid = Os.getuid(); info.packageName = "org.saildroid.cachecontract";
        info.dataDir = data.toString();
        if (mode.equals("wrong-uid")) info.uid++;
        if (mode.equals("code-symlink")) {
            Files.delete(code); Files.createSymbolicLink(code, data.resolve("external"));
        }
        if (mode.equals("target-symlink")) Files.createSymbolicLink(cache, data.resolve("external"));
        if (mode.equals("unsafe-mode")) Os.chmod(code.toString(), 0777);
        if (mode.equals("target-file")) Files.write(cache, new byte[]{7});
        String expected = mode.equals("wrong-property") ? data.resolve("external").toString() : cache.toString();
        check(expected.equals(System.getProperty("dexmaker.dexcache")), "actual VM startup value");
        Properties previous = System.getProperties();
        try {
            System.getProperties().clear();
            check(expected.equals(System.getProperty("dexmaker.dexcache")), "startup configuration survives clear");
            System.setProperties(new Properties());
            check(expected.equals(System.getProperty("dexmaker.dexcache")), "startup configuration survives replacement");
            System.setProperties(null);
            check(expected.equals(System.getProperty("dexmaker.dexcache")), "startup configuration survives reset");
        } finally { System.setProperties(previous); }
        try {
            Class.forName("SdApplicationCodeCache").getMethod("bind", ApplicationInfo.class).invoke(null, info);
            check(mode.equals("valid"), "invalid cache boundary accepted: " + mode);
        } catch (InvocationTargetException error) {
            Throwable cause = error.getCause();
            check(!mode.equals("valid") && (cause instanceof SecurityException || cause instanceof java.io.IOException),
                    "unexpected binding failure: " + cause);
            check(expected.equals(System.getProperty("dexmaker.dexcache")), "rejected configuration was rewritten");
            check(!Files.exists(data.resolve("external/dexmaker")), "rejected symlink target changed");
            System.out.println("APPLICATION_CACHE_STARTUP_CONTRACT=PASS|mode=" + mode + "|checks=" + checks + "|uid=" + Os.getuid());
            return;
        }
        StructStat st = Os.lstat(cache.toString());
        check(st.st_uid == Os.getuid() && (st.st_mode & 0777) == 0700, "actual cache ownership and mode");
        Path payload = cache.resolve("payload"); byte[] content = {3, 14, 15, 92};
        Files.write(payload, content);
        check(Arrays.equals(Files.readAllBytes(payload), content), "actual private cache file IO");
        Class.forName("SdApplicationCodeCache").getMethod("bind", ApplicationInfo.class).invoke(null, info);
        check(Files.exists(payload), "idempotent binding retained file");
        System.out.println("APPLICATION_CACHE_STARTUP_CONTRACT=PASS|mode=" + mode + "|checks=" + checks + "|uid=" + Os.getuid());
    }
}
