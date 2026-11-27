import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.Provider;
import java.security.Security;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.TreeSet;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.DESedeKeySpec;
import javax.crypto.spec.SecretKeySpec;

/** Independent checks of effective services and real operations, no original CTS changes. */
public final class CryptoProviderAlias277Contract {
    private static int checks;
    private static void check(boolean value, String message) {
        ++checks;
        if (!value) throw new AssertionError(message);
    }
    public static void run(boolean duplicateExpected) throws Exception {
        check(android.system.Os.getuid() == 65534, "Actual ordinary VM UID");
        check(android.system.Os.prctl(39, 0, 0, 0, 0) == 1, "Actual kernel no_new_privs");
        Provider provider = Security.getProvider("SailDroidCryptoCompat");
        check(provider != null && provider.getClass().getName().equals("SdCryptoProvider"), "Same actual compatibility provider");
        TreeSet<String> inventory = new TreeSet<>();
        StringBuilder order = new StringBuilder();
        for (Provider p : Security.getProviders()) {
            order.append(p.getName()).append(':').append(p.getClass().getName()).append(';');
            for (Provider.Service service : p.getServices())
                inventory.add(p.getName() + ":" + service.getType().toUpperCase(Locale.ROOT) + "."
                        + service.getAlgorithm().toUpperCase(Locale.ROOT) + "=" + service.getClassName());
        }
        System.out.println("ALIAS277_PROVIDER_ORDER=" + order);
        for (String service : inventory) System.out.println("ALIAS277_EFFECTIVE_SERVICE=" + service);
        int caseProperties = 0;
        for (Object key : provider.keySet())
            if (key.toString().equalsIgnoreCase("SecretKeyFactory.DESede")) ++caseProperties;
        check(caseProperties == (duplicateExpected ? 2 : 1), "Actual case-only property duplication boundary");
        int propertiesAcrossProviders = 0;
        for (Provider p : Security.getProviders())
            for (Object key : p.keySet())
                if (key.toString().equalsIgnoreCase("SecretKeyFactory.DESede")) ++propertiesAcrossProviders;
        Provider[] filtered = Security.getProviders("SecretKeyFactory.DESede");
        check(filtered != null, "Effective provider lookup");
        check(propertiesAcrossProviders == filtered.length + (duplicateExpected ? 1 : 0), "One property per effective provider");
        byte[] raw = new byte[24];
        for (int i = 0; i < raw.length; ++i) raw[i] = (byte)(i * 7 + 1);
        for (String name : new String[]{"DESede", "DESEDE", "desede", "DeSeDe"}) {
            SecretKeyFactory factory = SecretKeyFactory.getInstance(name, provider);
            check(factory.getProvider() == provider, "Explicit unchanged provider for " + name);
            SecretKey key = factory.generateSecret(new DESedeKeySpec(raw));
            check(key.getEncoded().length == 24, "Real DESede key material");
            DESedeKeySpec spec = (DESedeKeySpec)factory.getKeySpec(key, DESedeKeySpec.class);
            check(Arrays.equals(key.getEncoded(), spec.getKey()), "KeySpec real roundtrip");
            SecretKey translated = factory.translateKey(new SecretKeySpec(key.getEncoded(), "DESede"));
            check(Arrays.equals(key.getEncoded(), translated.getEncoded()), "Actual key translation");
            Provider[] matches = Security.getProviders("SecretKeyFactory." + name);
            check(matches.length == filtered.length, "Case-insensitive effective provider filtering");
        }
        byte[] plaintext = "independent alias operation".getBytes(StandardCharsets.UTF_8);
        KeyGenerator generator = KeyGenerator.getInstance("ARC4", provider);
        generator.init(128);
        SecretKey arc4 = generator.generateKey();
        check(arc4.getEncoded().length == 16, "Preserved actual ARC4 key generator");
        for (String name : new String[]{"ARC4", "RC4"}) {
            Cipher cipher = Cipher.getInstance(name, provider);
            cipher.init(Cipher.ENCRYPT_MODE, arc4);
            byte[] encrypted = cipher.doFinal(plaintext);
            check(!Arrays.equals(plaintext, encrypted), "Real ARC4 encryption");
            cipher.init(Cipher.DECRYPT_MODE, arc4);
            check(Arrays.equals(plaintext, cipher.doFinal(encrypted)), "Preserved actual ARC4/RC4 decrypt");
        }
        String root = System.getenv("ANDROID_ROOT");
        String maps = new String(Files.readAllBytes(Paths.get("/proc/self/maps")), StandardCharsets.UTF_8);
        Set<String> images = new HashSet<>();
        for (String line : maps.split("\n")) {
            String[] words = line.trim().split(" +");
            if (words[words.length-1].endsWith(".art")) images.add(words[words.length-1]);
        }
        check(images.size() == 9, "Actual nine images");
        for (String image : images) check(image.startsWith(root + "/system/framework/arm64/"), "Current image owner");
        check(maps.contains(root + "/lib/libart.so") && maps.contains(root + "/android-libs/libjavacrypto.so"), "Actual current ART and crypto native");
        check(Security.getProvider("CertPathProvider").getService("KeyStore", "JKS") != null, "Existing JKS service preserved");
        System.out.println("ALIAS277_CONTRACT=PASS|duplicate=" + duplicateExpected + "|checks=" + checks
                + "|uid=65534|images=9|effective_services=" + inventory.size() + "|desede_providers=" + filtered.length);
    }
}
