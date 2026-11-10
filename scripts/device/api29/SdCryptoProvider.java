import java.security.Provider;
import java.security.Security;

/** Small compatibility overlay for algorithms present in the shipped Android BC jar. */
public final class SdCryptoProvider extends Provider {
    public SdCryptoProvider(){
        super("SailDroidCryptoCompat",1.0,"Android BC algorithm aliases retained for app compatibility");
        // The Android BouncyCastle source contains these implementations but its
        // API29 build removes their registration as an unsupported-algorithm
        // policy. QQ/TBS still requests both names during WebView startup.
        // Provider algorithm lookup is case-insensitive. One canonical entry
        // supports DESede/DESEDE without duplicate service properties.
        put("SecretKeyFactory.DESede","com.android.org.bouncycastle.jcajce.provider.symmetric.DESede$KeyFactory");
        put("Cipher.ARC4","com.android.org.bouncycastle.jcajce.provider.symmetric.ARC4$Base");
        put("Alg.Alias.Cipher.RC4","ARC4");
        put("KeyGenerator.ARC4","com.android.org.bouncycastle.jcajce.provider.symmetric.ARC4$KeyGen");
        put("Alg.Alias.KeyGenerator.RC4","ARC4");
    }
    public static synchronized void install(){
        if(Security.getProvider("SailDroidCryptoCompat")==null)Security.addProvider(new SdCryptoProvider());
    }
}
