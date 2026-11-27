import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.InvalidAlgorithmParameterException;
import java.security.InvalidKeyException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.PBEParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** Independent VM contract; original CTS input and assertions remain untouched. */
public final class PbeApi29Contract {
    private static int checks;
    private static final String MIXED = "PBEWITHSHAAND128BITAES-CBC-BC";
    private static void check(boolean value, String message) {
        checks++;
        if (!value) throw new AssertionError(message);
    }
    private static SecretKey passwordKey(byte[] salt, int iterations) throws Exception {
        SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WITHHMACSHA1");
        check(factory.getProvider().getName().equals("BC"), "Actual BC PBKDF2 provider");
        SecretKey key = factory.generateSecret(new PBEKeySpec("password".toCharArray(), salt, iterations, 128));
        check(key.getClass().getName().equals("com.android.org.bouncycastle.jcajce.provider.symmetric.util.BCPBEKey"),
                "Actual original-style BCPBEKey");
        return key;
    }
    private static Cipher mixed() throws Exception {
        Cipher cipher = Cipher.getInstance(MIXED);
        check(cipher.getProvider().getName().equals("BC"), "Actual BC PBE cipher owner");
        return cipher;
    }
    private static void nativeMappings(String root) throws Exception {
        String maps = new String(Files.readAllBytes(Paths.get("/proc/self/maps")), "UTF-8");
        Set<String> arts = new HashSet<>(), images = new HashSet<>(), cores = new HashSet<>();
        for (String line : maps.split("\n")) {
            String[] fields = line.trim().split(" +");
            String path = fields[fields.length - 1];
            if (path.endsWith("/libart.so")) arts.add(path);
            if (path.endsWith(".art")) images.add(path);
            if (path.endsWith("/libjavacore.so")) cores.add(path);
        }
        check(arts.equals(java.util.Collections.singleton(root + "/lib/libart.so")), "Exact current ART");
        check(cores.equals(java.util.Collections.singleton(root + "/lib/libjavacore.so")), "Exact current Linux JNI");
        check(images.size() == 9, "Actual nine matching boot images");
        for (String image : images) check(image.startsWith(root + "/system/framework/arm64/"), "Current image owner");
        check(maps.contains(root + "/android-libs/libjavacrypto.so"), "Actual component Conscrypt native crypto");
        check(maps.contains(root + "/lib/libsdmath-precision.so"), "Unchanged private Math owner");
    }
    public static void run(int sdk, String root) throws Exception {
        check(android.system.Os.getuid() == 65534, "Actual ordinary VM UID");
        check(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion() == sdk, "Actual requested target SDK");
        check(android.system.Os.prctl(39, 0, 0, 0, 0) == 1, "Actual kernel no_new_privs");
        byte[] plaintext = new byte[20];
        for (int i = 0; i < plaintext.length; ++i) plaintext[i] = (byte)i;
        byte[] salt = "salt".getBytes("UTF-8");
        SecretKey key = passwordKey(salt, 100);
        SecretKeySpec aesKey = new SecretKeySpec(key.getEncoded(), "AES");
        byte[] providedIV = new byte[16];
        new SecureRandom().nextBytes(providedIV);
        IvParameterSpec explicit = new IvParameterSpec(providedIV);
        Cipher cipher = mixed();
        cipher.init(Cipher.ENCRYPT_MODE, key, explicit);
        byte[] explicitCiphertext = cipher.doFinal(plaintext);
        check(Arrays.equals(cipher.getIV(), providedIV), "Caller IV retained exactly");
        Cipher independent = Cipher.getInstance("AES/CBC/PKCS5Padding", "AndroidOpenSSL");
        independent.init(Cipher.ENCRYPT_MODE, aesKey, new IvParameterSpec(providedIV));
        check(Arrays.equals(explicitCiphertext, independent.doFinal(plaintext)), "Explicit IV agrees with independent Conscrypt AES");
        cipher = mixed();
        cipher.init(Cipher.DECRYPT_MODE, passwordKey(salt, 100), explicit);
        check(Arrays.equals(plaintext, cipher.doFinal(explicitCiphertext)), "Explicit-IV PBE decrypt remains functional");
        for (int mode : new int[]{Cipher.ENCRYPT_MODE, Cipher.DECRYPT_MODE}) {
            try {
                mixed().init(mode, key, new IvParameterSpec(new byte[8]));
                throw new AssertionError("Malformed PBE IV accepted");
            } catch (InvalidAlgorithmParameterException expected) { checks++; }
        }
        for (int mode : new int[]{Cipher.ENCRYPT_MODE, Cipher.DECRYPT_MODE}) {
            try {
                mixed().init(mode, key, new PBEParameterSpec(salt, 100, new IvParameterSpec(providedIV)));
                throw new AssertionError("Nested PBE IV must not be silently ignored");
            } catch (InvalidAlgorithmParameterException expected) {
                check(expected.getMessage().contains("No IV"), "Unsupported nested IV keeps its original rejection");
            }
        }
        Cipher ordinary = Cipher.getInstance("AES/CBC/PKCS5Padding", "BC");
        ordinary.init(Cipher.ENCRYPT_MODE, aesKey);
        byte[] randomIV = ordinary.getIV();
        check(randomIV != null && randomIV.length == 16 && !Arrays.equals(randomIV, new byte[16]), "Ordinary AES generates an IV");
        byte[] randomCiphertext = ordinary.doFinal(plaintext);
        ordinary.init(Cipher.ENCRYPT_MODE, aesKey);
        check(!Arrays.equals(randomIV, ordinary.getIV()), "Fresh ordinary AES initialization uses fresh randomness");
        ordinary.init(Cipher.DECRYPT_MODE, aesKey, new IvParameterSpec(randomIV));
        check(Arrays.equals(plaintext, ordinary.doFinal(randomCiphertext)), "Ordinary AES real round trip");
        try {
            ordinary.init(Cipher.DECRYPT_MODE, aesKey);
            throw new AssertionError("Ordinary AES decrypt accepted no IV");
        } catch (InvalidKeyException expected) {
            check(expected.getMessage().contains("No IV"), "Ordinary missing-IV key initialization rejected");
        }

        nativeMappings(root);
        System.out.println("PBE_API29274_NATIVE=ready|sdk=" + sdk + "|uid=65534|images=9|native_crypto=actual");
        PBEParameterSpec legacy = new PBEParameterSpec(salt, 100);
        boolean compatible = sdk > 0 && sdk <= 29;
        if (!compatible) {
            for (int mode : new int[]{Cipher.ENCRYPT_MODE, Cipher.DECRYPT_MODE, Cipher.WRAP_MODE, Cipher.UNWRAP_MODE}) {
                try {
                    mixed().init(mode, passwordKey(salt, 100), legacy);
                    throw new AssertionError("New or unknown SDK acquired legacy zero-IV mode");
                } catch (InvalidAlgorithmParameterException expected) {
                    check(expected.getMessage().contains("No IV"), "Strict missing-IV error retained");
                }
            }
        } else {
            byte[] publishedVector = new byte[]{92,-65,-128,16,-102,-115,-44,52,16,124,-34,-45,58,-70,-17,127,119,-67,87,91,63,-13,-40,9,97,-17,-71,97,10,-61,-19,-73};
            cipher = mixed();
            cipher.init(Cipher.ENCRYPT_MODE, key, legacy);
            byte[] encrypted = cipher.doFinal(plaintext);
            check(Arrays.equals(cipher.getIV(), new byte[16]), "API29 canonical deprecated IV");
            check(Arrays.equals(encrypted, publishedVector), "Exact Android10 compatibility vector");
            independent.init(Cipher.ENCRYPT_MODE, aesKey, new IvParameterSpec(new byte[16]));
            check(Arrays.equals(encrypted, independent.doFinal(plaintext)), "Legacy encryption agrees with independent real AES");
            cipher = mixed();
            cipher.init(Cipher.DECRYPT_MODE, passwordKey(salt, 100), legacy);
            check(Arrays.equals(plaintext, cipher.doFinal(encrypted)), "Fresh PBE key decrypts actual legacy ciphertext");
            byte[] wrappedKeyBytes = new byte[16];
            new SecureRandom().nextBytes(wrappedKeyBytes);
            cipher = mixed();
            cipher.init(Cipher.WRAP_MODE, passwordKey(salt, 100), legacy);
            byte[] wrapped = cipher.wrap(new SecretKeySpec(wrappedKeyBytes, "AES"));
            cipher = mixed();
            cipher.init(Cipher.UNWRAP_MODE, passwordKey(salt, 100), legacy);
            check(Arrays.equals(wrappedKeyBytes, cipher.unwrap(wrapped, "AES", Cipher.SECRET_KEY).getEncoded()), "Real legacy wrap and unwrap");
        }
        System.out.println("PBE_API29274_CONTRACT=PASS|sdk=" + sdk + "|legacy=" + compatible + "|checks=" + checks + "|uid=65534|images=9|native_crypto=actual");
    }
}
