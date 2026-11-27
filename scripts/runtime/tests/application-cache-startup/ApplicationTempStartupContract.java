import android.system.Os;
import android.system.StructStat;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Properties;

/** Actual per-app Java scratch paths retain canonical command-line semantics. */
public final class ApplicationTempStartupContract {
    private static int checks;
    private static void check(boolean value, String why) {
        checks++;
        if (!value) throw new AssertionError(why);
    }
    public static void run(String label) throws Exception {
        check(Os.getuid() == 65534, "ordinary UID");
        Path data = Paths.get(System.getenv("SAILDROID_DATA_DIR"));
        Path cache = data.resolve("cache");
        String expected = cache.toString();
        check(expected.equals(System.getProperty("java.io.tmpdir")), "actual application cache configuration");
        Properties saved = System.getProperties();
        try {
            System.getProperties().clear();
            check(expected.equals(System.getProperty("java.io.tmpdir")), "clear retains startup temporary directory");
            System.setProperties(new Properties());
            check(expected.equals(System.getProperty("java.io.tmpdir")), "replacement retains startup temporary directory");
            System.setProperties(null);
            check(expected.equals(System.getProperty("java.io.tmpdir")), "reset retains startup temporary directory");
            System.setProperty("java.io.tmpdir", "/not-this-application");
            check(expected.equals(System.getProperty("java.io.tmpdir")), "canonical command-line value cannot be overridden");
            System.setProperty("user.home", "/still-mutable");
            check("/still-mutable".equals(System.getProperty("user.home")), "user.home remains mutable");
        } finally { System.setProperties(saved); }
        Path file = java.io.File.createTempFile("app-temp-", ".bin").toPath();
        check(file.getParent().equals(cache) && file.toFile().getCanonicalFile().toPath().equals(file), "default temporary file belongs to real private cache");
        byte[] bytes = {23, 7, 29, 16}; Files.write(file, bytes);
        check(java.util.Arrays.equals(bytes, Files.readAllBytes(file)), "real temporary file IO");
        StructStat st = Os.lstat(cache.toString());
        check(st.st_uid == Os.getuid() && (st.st_mode & 0777) == 0700, "private owner and mode");
        StructStat fs = Os.lstat(file.toString());
        check(fs.st_uid == Os.getuid() && (fs.st_mode & 0077) == 0, "temporary file inaccessible to other UIDs");
        System.out.println("APPLICATION_TEMP_STARTUP_CONTRACT=PASS|application=" + label + "|checks=" + checks + "|uid=" + Os.getuid() + "|file=" + file);
    }
}
