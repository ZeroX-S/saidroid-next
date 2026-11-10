import android.content.pm.ApplicationInfo;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.File;
import java.io.IOException;

/** Bind documented dynamic-code library interop to this actual app's private cache.
 * The installed APK path is intentionally private to SailDroid rather than
 * /data/app, so DexMaker's last-resort Android path guess cannot identify it.
 * Use its documented property; do not alter APK paths, loaders or generated code.
 */
public final class SdApplicationCodeCache {
    private static void directory(File path, int uid, boolean privateMode) throws IOException {
        if (!path.isAbsolute() || !path.getCanonicalFile().equals(path))
            throw new SecurityException("Application code cache contains a symbolic link or noncanonical path");
        try {
            StructStat st = Os.lstat(path.getPath());
            if (!OsConstants.S_ISDIR(st.st_mode) || st.st_uid != uid
                    || (st.st_mode & (privateMode ? 0077 : 0022)) != 0)
                throw new SecurityException("Application code cache ownership or permissions differ");
        } catch (ErrnoException error) { throw new IOException("Cannot inspect application code cache", error); }
    }
    public static synchronized void bind(ApplicationInfo app) throws IOException {
        int uid = Os.getuid();
        if (uid <= 0 || app == null || app.uid != uid || app.dataDir == null
                || app.packageName == null || app.packageName.isEmpty())
            throw new SecurityException("Actual ordinary application identity required for code cache");
        File data = new File(app.dataDir), code = new File(data, "code_cache");
        directory(data, uid, true); directory(code, uid, false);
        File cache = new File(code, "dexmaker");
        String configured = System.getProperty("dexmaker.dexcache");
        if (configured != null && !configured.equals(cache.getPath()))
            throw new SecurityException("Dynamic code cache property escaped this application cache");
        try { Os.mkdir(cache.getPath(), 0700); }
        catch (ErrnoException error) {
            if (error.errno != OsConstants.EEXIST) throw new IOException("Cannot create application dynamic code cache", error);
        }
        directory(cache, uid, true);
        System.setProperty("dexmaker.dexcache", cache.getPath());
        System.err.println("SDRUNTIME=dynamic_code_cache|package=" + app.packageName + "|uid=" + uid
                + "|path=" + cache + "|scope=private-application|interop=documented-dexmaker-property");
    }
}
