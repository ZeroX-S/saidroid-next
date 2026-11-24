import dalvik.system.VMRuntime;
import java.lang.reflect.InvocationTargetException;
import java.security.NoSuchAlgorithmException;
import java.security.Provider;
import java.security.Security;
import java.util.Arrays;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import sun.security.jca.Providers;

/** Exercise real JCA selection, provider identity and actual HMAC output. */
public final class CryptoPolicyContract {
    private static int checks;
    private static void check(boolean yes) { checks++; if(!yes)throw new AssertionError("check "+checks); }
    private interface Action { void run() throws Exception; }
    private static void rejected(Action action) throws Exception {
        try { action.run(); throw new AssertionError("Deprecated system BC selection accepted"); }
        catch(Exception exception) {
            Throwable cause=exception;
            while(cause.getCause()!=null)cause=cause.getCause();
            check(cause instanceof NoSuchAlgorithmException);
            check(cause.getMessage().contains("BC provider no longer provides"));
        }
    }
    private static String hex(byte[] input) {
        char[] digits="0123456789abcdef".toCharArray();StringBuilder out=new StringBuilder();
        for(byte value:input)out.append(digits[(value>>>4)&15]).append(digits[value&15]);
        return out.toString();
    }
    private static void vector(Mac mac) throws Exception {
        byte[] key=new byte[20];Arrays.fill(key,(byte)0x0b);
        mac.init(new SecretKeySpec(key,"HmacSHA256"));
        check(hex(mac.doFinal("Hi There".getBytes("US-ASCII"))).equals("b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"));
    }
    public static void main(String[] args) throws Exception {
        int threshold=Providers.getMaximumAllowableApiLevelForBcDeprecation();
        int sdk=VMRuntime.getRuntime().getTargetSdkVersion();
        Provider[] before=Security.getProviders();Provider bc=Security.getProvider("BC");
        check(threshold==27 && sdk==29 && bc!=null);
        String[][] cases={
            {"java.security.AlgorithmParameters","AES"},
            {"java.security.cert.CertificateFactory","X.509"},
            {"javax.crypto.Cipher","ARC4"},
            {"javax.crypto.KeyAgreement","ECDH"},
            {"java.security.KeyFactory","RSA"},
            {"javax.crypto.KeyGenerator","HMACSHA256"},
            {"java.security.KeyPairGenerator","RSA"},
            {"javax.crypto.Mac","HMACSHA256"},
            {"java.security.MessageDigest","SHA-256"},
            {"javax.crypto.SecretKeyFactory","DESEDE"},
            {"java.security.Signature","SHA256WITHRSA"}};
        int bcIndex=0;for(int i=0;i<before.length;i++)if(before[i]==bc)bcIndex=i+1;
        try {
            for(String[] row:cases) {
                Class<?> type=Class.forName(row[0]);
                rejected(()->type.getMethod("getInstance",String.class,String.class).invoke(null,row[1],"BC"));
                rejected(()->type.getMethod("getInstance",String.class,Provider.class).invoke(null,row[1],bc));
            }
            VMRuntime.getRuntime().setTargetSdkVersion(27);
            check(VMRuntime.getRuntime().getTargetSdkVersion()==27);
            vector(Mac.getInstance("HmacSHA256","BC"));
            Providers.setMaximumAllowableApiLevelForBcDeprecation(26);
            rejected(()->Mac.getInstance("HmacSHA256","BC"));
            VMRuntime.getRuntime().setTargetSdkVersion(29);
            Providers.setMaximumAllowableApiLevelForBcDeprecation(29);
            vector(Mac.getInstance("HmacSHA256",bc));
            Providers.setMaximumAllowableApiLevelForBcDeprecation(27);
            rejected(()->Mac.getInstance("HmacSHA256",bc));
            // No-provider selection continues to choose an actual available provider.
            vector(Mac.getInstance("HmacSHA256"));
            Provider replacement=new Provider("BC",1.0,"Private real primitive identity fixture"){};
            replacement.put("Mac.HMACSHA256",bc.getService("Mac","HmacSHA256").getClassName());
            Security.removeProvider("BC");check(Security.insertProviderAt(replacement,bcIndex)==bcIndex);
            check(Security.getProvider("BC")==replacement);
            vector(Mac.getInstance("HmacSHA256","BC"));
            vector(Mac.getInstance("HmacSHA256",replacement));
            rejected(()->Providers.checkBouncyCastleDeprecation(bc,"Mac","HmacSHA256"));
            Providers.checkBouncyCastleDeprecation(replacement,"Mac","not-an-algorithm");
            try{Mac.getInstance("not-an-algorithm",replacement);throw new AssertionError("Missing algorithm accepted");}
            catch(NoSuchAlgorithmException expected){check(!expected.getMessage().contains("BC provider no longer provides"));}
        } finally {
            Security.removeProvider("BC");Security.insertProviderAt(bc,bcIndex);
            Providers.setMaximumAllowableApiLevelForBcDeprecation(threshold);
            VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        }
        Provider[] after=Security.getProviders();check(before.length==after.length);
        for(int i=0;i<before.length;i++)check(before[i]==after[i]);
        check(Providers.getMaximumAllowableApiLevelForBcDeprecation()==threshold && VMRuntime.getRuntime().getTargetSdkVersion()==sdk);
        System.out.println("CRYPTO_POLICY_CONTRACT=PASS|checks="+checks+"|service_families=11|explicit_overloads=22|real_hmac_vectors=5|provider_identity_and_sdk_restored=true");
    }
}
