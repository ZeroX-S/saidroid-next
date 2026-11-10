import android.content.pm.PermissionInfo;
import android.content.res.AssetManager;
import android.content.res.XmlResourceParser;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
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
    private static final Path POLICY_ROOT = java.nio.file.Paths.get("/var/lib/saildroid/permissions");
    private final String apkPath;
    private String apkDigest;
    private Map<String,Object> apkIdentity;
    private final String owner;
    private final Map<String, Integer> declarations = new HashMap<String, Integer>();
    private final Map<String, Integer> platformDeclarations = new HashMap<String, Integer>();
    private final Set<String> requested = new HashSet<String>();

    public SdAppPermissions(String apk, String expectedPackage) throws Exception {
        owner = expectedPackage;
        apkPath = apk;
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
        Integer protection = platformDeclarations.get(permission);
        if (protection != null) {
            int base = protection & PermissionInfo.PROTECTION_MASK_BASE;
            return base == PermissionInfo.PROTECTION_NORMAL
                    || (base == PermissionInfo.PROTECTION_DANGEROUS
                    && "granted".equals(decisions().getProperty(permission)) && supported(permission));
        }
        // A package may not redefine Android's permission namespace or replace
        // a platform permission's protection level with an app declaration.
        protection = declarations.get(permission);
        if (permission.startsWith("android.") || protection == null) return false;
        int base = protection & PermissionInfo.PROTECTION_MASK_BASE;
        return base == PermissionInfo.PROTECTION_NORMAL || base == PermissionInfo.PROTECTION_SIGNATURE;
    }

    private synchronized String digest() throws Exception {
        Path path = java.nio.file.Paths.get(apkPath);
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))
            throw new SecurityException("APK is not a regular file");
        Map<String,Object> identity = Files.readAttributes(path, "unix:dev,ino,size,lastModifiedTime,ctime", LinkOption.NOFOLLOW_LINKS);
        if (apkDigest == null || !identity.equals(apkIdentity)) {
            java.security.MessageDigest hash = java.security.MessageDigest.getInstance("SHA-256");
            try (java.io.InputStream input = new FileInputStream(apkPath)) {
                byte[] bytes = new byte[65536]; int count;
                while ((count = input.read(bytes)) != -1) hash.update(bytes, 0, count);
            }
            StringBuilder result = new StringBuilder();
            for (byte value : hash.digest()) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            if (!identity.equals(Files.readAttributes(path, "unix:dev,ino,size,lastModifiedTime,ctime", LinkOption.NOFOLLOW_LINKS)))
                throw new SecurityException("APK changed during permission verification");
            apkDigest = result.toString();
            apkIdentity = identity;
        }
        return apkDigest;
    }

    private static void trusted(Path path, boolean directory) throws IOException {
        Map<String,Object> status = Files.readAttributes(path, "unix:uid,mode", LinkOption.NOFOLLOW_LINKS);
        int mode = ((Number)status.get("mode")).intValue();
        if (((Number)status.get("uid")).intValue() != 0 || (mode & 0022) != 0
                || (mode & 0170000) != (directory ? 0040000 : 0100000))
            throw new SecurityException("Untrusted host permission policy");
    }

    private Properties decisions() {
        Properties result = new Properties();
        if (!SdApkPackage.NAME.equals(owner) || !owner.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+")) return result;
        try {
            for (Path part = POLICY_ROOT.getRoot(); part != null;) {
                trusted(part, true);
                if (part.equals(POLICY_ROOT)) break;
                part = part.resolve(POLICY_ROOT.getName(part.getNameCount()));
                if (!Files.exists(part, LinkOption.NOFOLLOW_LINKS)) return result;
            }
            Path path = POLICY_ROOT.resolve(owner + ".properties");
            if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return result;
            trusted(path, false);
            try (java.io.InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) { result.load(input); }
            if (!owner.equals(result.getProperty("package")) || !digest().equals(result.getProperty("apk.sha256")))
                return new Properties();
        } catch (Exception failure) {
            // A damaged/untrusted policy must deny, including during permission checks.
            System.err.println("SDPERMISSION=host_policy_rejected|type=" + failure.getClass().getSimpleName());
            return new Properties();
        }
        return result;
    }

    public boolean canRequest(String name) {
        Integer protection = platformDeclarations.get(name);
        return requested.contains(name) && protection != null
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

    /** Hosted APK code cannot authorize itself. Host policy is edited outside ART. */
    public void decide(Map<String, Boolean> choices) {
        if (!choices.isEmpty()) throw new SecurityException("Runtime grants require the trusted host permission controller");
    }

    public boolean interactiveAuthorizationAvailable() { return false; }

    public Set<String> getOwnedGrants() {
        Set<String> result = new HashSet<String>();
        for (String name : declarations.keySet()) if (holds(name)) result.add(name);
        return java.util.Collections.unmodifiableSet(result);
    }
}
