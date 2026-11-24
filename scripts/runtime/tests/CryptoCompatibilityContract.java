import java.security.Security;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.DESedeKeySpec;
import javax.crypto.spec.SecretKeySpec;

/** Public known-answer fixtures, run with real Android BC and native ART. */
public final class CryptoCompatibilityContract {
    private static byte[] hex(String s){byte[] b=new byte[s.length()/2];for(int i=0;i<b.length;i++)b[i]=(byte)Integer.parseInt(s.substring(i*2,i*2+2),16);return b;}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args){try{
        SdRuntime.initializeFramework(true);
        require(Security.getProvider("SailDroidCryptoCompat")!=null,"compat provider registered");
        byte[] key=hex("0123456789abcdef23456789abcdef01456789abcdef0123");
        SecretKeyFactory factory=SecretKeyFactory.getInstance("DESede");
        SecretKey secret=factory.generateSecret(new DESedeKeySpec(key));
        Cipher triple=Cipher.getInstance("DESede/ECB/NoPadding");triple.init(Cipher.ENCRYPT_MODE,secret);
        // Independently checked using OpenSSL's des-ede3 implementation.
        require(Arrays.equals(triple.doFinal(hex("fedcba9876543210")),hex("0737f6c53750d4a4")),"3DES known answer");
        require(Arrays.equals(((DESedeKeySpec)factory.getKeySpec(secret,DESedeKeySpec.class)).getKey(),key),"3DES key spec conversion");
        // RFC 6229, 40-bit RC4 key 01 02 03 04 05, first 16 stream bytes.
        Cipher rc4=Cipher.getInstance("RC4");rc4.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(hex("0102030405"),"RC4"));
        require(Arrays.equals(rc4.doFinal(new byte[16]),hex("b2396305f03dc027ccc3524a0a1118a8")),"RFC6229 RC4 known answer");
        // This overlay must not replace existing cipher/provider selections.
        require(!Cipher.getInstance("AES/GCM/NoPadding").getProvider().getName().equals("SailDroidCryptoCompat"),"existing AES provider retained");
        boolean rejected=false;try{SecretKeyFactory.getInstance("SailDroidImaginaryAlgorithm");}catch(java.security.NoSuchAlgorithmException expected){rejected=true;}
        require(rejected,"unknown algorithms still fail");
        System.out.println("CRYPTO_COMPATIBILITY=PASS|desede_known_answer=true|rc4_rfc6229=true|aes_provider_retained=true|unknown_rejected=true");System.exit(0);
    }catch(Throwable error){error.printStackTrace();System.exit(11);}}
}
