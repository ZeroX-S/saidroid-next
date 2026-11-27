import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyStore;
import java.security.Provider;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import javax.crypto.spec.SecretKeySpec;
import org.json.JSONObject;

/** Compare the entire real registry and perform a real BKS secret-key roundtrip. */
public final class BcRegistrationContract {
    public static void main(String[] args) throws Exception {
        JSONObject graph=new JSONObject(new String(Files.readAllBytes(Paths.get(
                System.getProperty("saidroid.test.bc-reference"))),"UTF-8"));
        JSONObject expected=graph.getJSONObject("properties");
        Provider bc=(Provider)Class.forName("com.android.org.bouncycastle.jce.provider.BouncyCastleProvider").newInstance();
        if(bc.getVersion()!=1.77)throw new AssertionError("Underlying provider version was replaced");
        Map<String,String> actual=new HashMap<>();
        for(Map.Entry<Object,Object> entry:bc.entrySet())if(!((String)entry.getKey()).startsWith("Provider.id "))
            actual.put((String)entry.getKey(),(String)entry.getValue());
        if(actual.size()!=566||expected.length()!=566)throw new AssertionError("Registry count mismatch");
        int implementations=0;
        for(Iterator<String> it=expected.keys();it.hasNext();) {
            String key=it.next(),value=expected.getString(key);
            if(!value.equals(actual.get(key)))throw new AssertionError("Registry differs: "+key);
            if(!key.startsWith("Alg.Alias.")&&!key.contains(" ")) {
                Class.forName(value,false,bc.getClass().getClassLoader());implementations++;
            }
        }
        if(implementations!=153)throw new AssertionError("Implementation count mismatch");
        char[] password="owned-contract-password".toCharArray();
        byte[] key=new byte[32];for(int i=0;i<key.length;i++)key[i]=(byte)(i*7+11);
        KeyStore first=KeyStore.getInstance("BKS",bc);first.load(null,password);
        first.setEntry("owned-secret",new KeyStore.SecretKeyEntry(new SecretKeySpec(key,"HmacSHA256")),
                new KeyStore.PasswordProtection(password));
        ByteArrayOutputStream encoded=new ByteArrayOutputStream();first.store(encoded,password);
        if(encoded.size()<key.length)throw new AssertionError("Empty encoded BKS");
        KeyStore second=KeyStore.getInstance("BKS",bc);second.load(new ByteArrayInputStream(encoded.toByteArray()),password);
        if(!Arrays.equals(key,second.getKey("owned-secret",password).getEncoded()))throw new AssertionError("BKS roundtrip changed key");
        try{KeyStore bad=KeyStore.getInstance("BKS",bc);bad.load(new ByteArrayInputStream(encoded.toByteArray()),"wrong".toCharArray());throw new AssertionError("Bad BKS password accepted");}
        catch(java.io.IOException expectedFailure){}
        System.out.println("BC_REGISTRATION_CONTRACT=PASS|properties=566|implementation_classes=153|BKS_actual_roundtrip=true|bad_password_rejected=true|actual_version=1.77");
        CryptoPolicyContract.main(new String[0]);
    }
}
