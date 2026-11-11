import android.content.pm.PermissionInfo;
import android.content.res.AssetManager;
import android.content.res.XmlResourceParser;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.TreeSet;
import org.xmlpull.v1.XmlPullParser;

/** Narrow local-app grants derived from the actual binary APK manifest.
 * Host permissions and permissions owned by other packages are not inferred.
 */
public final class SdAppPermissions {
    private static final String ANDROID = "http://schemas.android.com/apk/res/android";
    private static final Object DECISION_LOCK = new Object();
    private final String owner;
    private final Map<String, Integer> declarations = new HashMap<String, Integer>();
    private final Map<String, Integer> platformDeclarations = new HashMap<String, Integer>();
    private final Set<String> requested = new HashSet<String>();

    public SdAppPermissions(String apk, String expectedPackage) throws Exception {
        owner = expectedPackage;
        readManifest(apk, expectedPackage, declarations, true);
        readManifest(System.getenv("ANDROID_ROOT")+"/framework/framework-res.apk", "android", platformDeclarations, false);
    }

    private void readManifest(String apk, String expectedPackage, Map<String, Integer> target,
                              boolean collectRequested) throws Exception {
        if (apk == null) throw new IllegalArgumentException("APK path is required");
        AssetManager assets = new AssetManager();
        XmlResourceParser xml = null;
        try {
            int cookie = assets.addAssetPath(apk);
            if (cookie == 0) throw new IllegalArgumentException("Cannot read APK: " + apk);
            xml = assets.openXmlResourceParser(cookie, "AndroidManifest.xml");
            boolean verified = false;
            for (int event = xml.next(); event != XmlPullParser.END_DOCUMENT; event = xml.next()) {
                if (event != XmlPullParser.START_TAG) continue;
                String tag = xml.getName();
                if (xml.getDepth() == 1 && "manifest".equals(tag)) {
                    if (!expectedPackage.equals(xml.getAttributeValue(null, "package"))) {
                        throw new SecurityException("Manifest package differs from the bound owner");
                    }
                    verified = true;
                }
                if (xml.getDepth() != 2) continue;
                String name = xml.getAttributeValue(ANDROID, "name");
                if (name == null) continue;
                if ("permission".equals(tag)) {
                    target.put(name, xml.getAttributeIntValue(ANDROID, "protectionLevel", 0));
                } else if (collectRequested && ("uses-permission".equals(tag)
                        || "uses-permission-sdk-23".equals(tag) || "uses-permission-sdk-m".equals(tag))) {
                    int maxSdk = xml.getAttributeIntValue(ANDROID, "maxSdkVersion", Integer.MAX_VALUE);
                    if (maxSdk >= android.os.Build.VERSION.SDK_INT) requested.add(name);
                }
            }
            if (!verified) throw new SecurityException("Missing manifest identity");
        } finally {
            if (xml != null) xml.close();
            assets.close();
        }
    }

    public boolean holds(String permission) {
        if (permission == null) return true;
        if (!requested.contains(permission)) return false;
        Integer protection = declarations.get(permission);
        if (protection == null) {
            protection = platformDeclarations.get(permission);
            if (protection == null) return false;
            int base = protection & PermissionInfo.PROTECTION_MASK_BASE;
            return base == PermissionInfo.PROTECTION_NORMAL
                    || (base == PermissionInfo.PROTECTION_DANGEROUS
                    && "granted".equals(decisions().getProperty(permission)) && supported(permission));
        }
        int base = protection & PermissionInfo.PROTECTION_MASK_BASE;
        // The single hosted app is also the declaring/signing owner. This does
        // not confer signature privileges owned by android or another APK.
        return base == PermissionInfo.PROTECTION_NORMAL || base == PermissionInfo.PROTECTION_SIGNATURE;
    }

    private File decisionFile() {
        if (!SdApkPackage.NAME.equals(owner)) throw new SecurityException("Runtime grant owner differs");
        return new File(SdApkPackage.DATA, "saildroid-runtime-permissions.properties");
    }

    private Properties decisions() {
        Properties result = new Properties();
        if (!SdApkPackage.NAME.equals(owner)) return result;
        Path path = decisionFile().toPath();
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return result;
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalStateException("Runtime permission record must be a regular file");
        }
        try (FileInputStream input = new FileInputStream(path.toFile())) {
            result.load(input);
        } catch (IOException failure) {
            throw new IllegalStateException("Cannot read runtime grants", failure);
        }
        return result;
    }

    public boolean canRequest(String name) {
        Integer protection = platformDeclarations.get(name);
        return requested.contains(name) && !declarations.containsKey(name) && protection != null
                && (protection & PermissionInfo.PROTECTION_MASK_BASE) == PermissionInfo.PROTECTION_DANGEROUS;
    }

    public Set<String> getRuntimePermissions() {
        Set<String> result = new TreeSet<String>();
        for (String name : requested) if (canRequest(name)) result.add(name);
        return java.util.Collections.unmodifiableSet(result);
    }

    public boolean supported(String name) {
        if (!SdApkPackage.NAME.equals(owner) || !canRequest(name)) return false;
        if ("android.permission.CAMERA".equals(name)) return SdCamera.available();
        if ("android.permission.RECORD_AUDIO".equals(name)) return SdAudio.recordingAvailable();
        boolean write = "android.permission.WRITE_EXTERNAL_STORAGE".equals(name);
        if (!write && !"android.permission.READ_EXTERNAL_STORAGE".equals(name)) return false;
        String shared = System.getenv("EXTERNAL_STORAGE");
        if (shared == null) return false;
        File directory = new File(shared);
        return directory.isDirectory() && directory.canRead() && (!write || directory.canWrite());
    }

    public boolean shouldShowRationale(String name) {
        return canRequest(name) && !holds(name) && "denied".equals(decisions().getProperty(name));
    }

    /** Merge choices under a cross-process lock and atomically publish one record. */
    public void decide(Map<String, Boolean> choices) {
        File destination = decisionFile();
        for (Map.Entry<String, Boolean> choice : choices.entrySet()) {
            if (!canRequest(choice.getKey()) || choice.getValue() == null) {
                throw new SecurityException("Permission is not declared for runtime authorization");
            }
            if (choice.getValue() && !supported(choice.getKey())) {
                throw new SecurityException("Permission backend is unavailable");
            }
        }
        if (choices.isEmpty()) return;
        synchronized (DECISION_LOCK) {
            Path lockPath = new File(destination.getParentFile(), "saildroid-runtime-permissions.lock").toPath();
            if (Files.isSymbolicLink(lockPath)) throw new SecurityException("Runtime permission lock is a symbolic link");
            Path temporary = null;
            try (FileOutputStream lockOutput = new FileOutputStream(lockPath.toFile(), true);
                 FileLock lock = lockOutput.getChannel().lock()) {
                Properties state = decisions();
                for (Map.Entry<String, Boolean> choice : choices.entrySet()) {
                    state.setProperty(choice.getKey(), choice.getValue() ? "granted" : "denied");
                }
                temporary = Files.createTempFile(destination.getParentFile().toPath(), ".saildroid-permissions-", ".tmp");
                try (FileOutputStream output = new FileOutputStream(temporary.toFile())) {
                    state.store(output, "Explicit per-application SailDroid runtime permission choices");
                    output.getFD().sync();
                }
                Files.move(temporary, destination.toPath(), StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
            } catch (IOException failure) {
                throw new IllegalStateException("Cannot save runtime permission decision", failure);
            } finally {
                if (temporary != null) {
                    try { Files.deleteIfExists(temporary); }
                    catch (IOException failure) {
                        System.err.println("SDPERMISSION=temporary_cleanup_failed|type=" + failure.getClass().getName());
                    }
                }
            }
        }
    }

    public Set<String> getOwnedGrants() {
        Set<String> result = new HashSet<String>();
        for (String name : declarations.keySet()) if (holds(name)) result.add(name);
        return java.util.Collections.unmodifiableSet(result);
    }
}
