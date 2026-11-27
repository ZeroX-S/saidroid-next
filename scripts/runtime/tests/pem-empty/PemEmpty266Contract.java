import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.security.cert.*;
import java.util.*;

/** Independent parser boundaries using fresh real certificates and CRLs; no trust bypass. */
public final class PemEmpty266Contract {
    static int checks;
    static void check(boolean ok,String name){if(!ok)throw new AssertionError(name);checks++;}
    static ByteArrayInputStream input(String s)throws Exception{return new ByteArrayInputStream(s.getBytes("US-ASCII"));}
    static void rejectCertificate(CertificateFactory cf,byte[] bytes,String name)throws Exception{
        try{cf.generateCertificate(new ByteArrayInputStream(bytes));throw new AssertionError("malformed nonempty certificate accepted: "+name+"/"+cf.getProvider().getName());}
        catch(CertificateException expected){checks++;}
    }
    static void rejectCRL(CertificateFactory cf,String s,String name)throws Exception{
        try{cf.generateCRL(input(s));throw new AssertionError("malformed nonempty CRL accepted: "+name+"/"+cf.getProvider().getName());}
        catch(CRLException expected){checks++;}
    }
    static void emptyCertificate(CertificateFactory cf,String s)throws Exception{
        try{check(cf.generateCertificate(input(s))==null,"empty PEM record has no certificate");}
        catch(CertificateException e){throw new AssertionError("empty PEM record rejected instead of no certificate",e);}
    }
    static void emptyCRL(CertificateFactory cf,String s)throws Exception{
        try{check(cf.generateCRL(input(s))==null,"empty PEM record has no CRL");}
        catch(CRLException e){throw new AssertionError("empty PEM record rejected instead of no CRL",e);}
    }
    public static void run()throws Exception{
        String dir=System.getProperty("saidroid.test.pem.fixture");
        String pem=new String(Files.readAllBytes(Paths.get(dir,"ca.pem")),"US-ASCII");
        byte[] der=Files.readAllBytes(Paths.get(dir,"ca.der"));
        String crl=new String(Files.readAllBytes(Paths.get(dir,"valid.crl.pem")),"US-ASCII");
        byte[] crlder=Files.readAllBytes(Paths.get(dir,"valid.crl.der"));
        check(Security.getProvider("BC")!=null,"actual BC provider exists");
        try{CertificateFactory.getInstance("X.509","BC");throw new AssertionError("deprecated BC selector unexpectedly allowed for SDK29");}
        catch(CertificateException expected){checks++;}
        // Android permits explicitly supplied private provider objects; keep the installed
        // provider and its SDK29 deprecation policy unchanged while testing the real SPI.
        Provider privateBC=(Provider)Class.forName("com.android.org.bouncycastle.jce.provider.BouncyCastleProvider").getConstructor().newInstance();
        check(privateBC!=Security.getProvider("BC"),"private provider does not replace system registry");
        CertificateFactory bc=CertificateFactory.getInstance("X509",privateBC);
        for(String header:new String[]{"CERTIFICATE","X509 CERTIFICATE","PKCS7"}){
            for(String suffix:new String[]{"","\n","\r\n","\n\n"})emptyCertificate(bc,"-----BEGIN "+header+"-----"+suffix);
            emptyCertificate(bc,"-----BEGIN "+header+"-----\n-----END "+header+"-----\n");
        }
        for(String header:new String[]{"CRL","X509 CRL","PKCS7"}){
            for(String suffix:new String[]{"","\n","\r\n"})emptyCRL(bc,"-----BEGIN "+header+"-----"+suffix);
            emptyCRL(bc,"-----BEGIN "+header+"-----\n-----END "+header+"-----\n");
        }
        for(String provider:new String[]{"BC","AndroidOpenSSL"}){
            CertificateFactory cf=CertificateFactory.getInstance("X509",provider.equals("BC")?privateBC:Security.getProvider(provider));
            X509Certificate c=(X509Certificate)cf.generateCertificate(input(pem));
            check(Arrays.equals(c.getEncoded(),der),"valid PEM byte-exact DER "+provider);c.verify(c.getPublicKey());checks++;
            check(Arrays.equals(cf.generateCertificate(input(pem.replace("\n","\r\n"))).getEncoded(),der),"CRLF valid certificate "+provider);
            check(Arrays.equals(cf.generateCertificate(new ByteArrayInputStream(der)).getEncoded(),der),"valid binary DER "+provider);
            c.checkValidity();checks++;
            try{c.checkValidity(new Date(c.getNotAfter().getTime()+1000));throw new AssertionError("expired certificate accepted");}catch(CertificateExpiredException expected){checks++;}
            try{c.checkValidity(new Date(c.getNotBefore().getTime()-1000));throw new AssertionError("not-yet-valid certificate accepted");}catch(CertificateNotYetValidException expected){checks++;}
            X509CRL parsed=(X509CRL)cf.generateCRL(input(crl));
            check(Arrays.equals(parsed.getEncoded(),crlder),"valid PEM CRL byte-exact DER "+provider);parsed.verify(c.getPublicKey());checks++;
            check(Arrays.equals(((X509CRL)cf.generateCRL(new ByteArrayInputStream(crlder))).getEncoded(),crlder),"valid binary CRL "+provider);
            check(!parsed.isRevoked(c),"actual generated empty CRL "+provider);
            rejectCertificate(cf,pem.replace("-----END CERTIFICATE-----","").getBytes("US-ASCII"),"nonempty missing footer");
            rejectCertificate(cf,pem.replace("-----END CERTIFICATE-----","-----END CRL-----").getBytes("US-ASCII"),"mismatched footer");
            rejectCertificate(cf,("-----BEGIN CERTIFICATE-----\n###notbase64###\n-----END CERTIFICATE-----\n").getBytes("US-ASCII"),"invalid base64");
            rejectCertificate(cf,Arrays.copyOf(der,Math.min(64,der.length-1)),"truncated DER");
            rejectCRL(cf,crl.replace("-----END X509 CRL-----",""),"nonempty missing CRL footer");
            rejectCRL(cf,crl.replace("-----END X509 CRL-----","-----END CERTIFICATE-----"),"mismatched CRL footer");
            byte[] corrupt=der.clone();corrupt[corrupt.length-1]^=1;
            X509Certificate altered=(X509Certificate)cf.generateCertificate(new ByteArrayInputStream(corrupt));
            try{altered.verify(c.getPublicKey());throw new AssertionError("bad real signature accepted");}catch(SignatureException expected){checks++;}
            if(!provider.equals("BC"))rejectCertificate(cf,"-----BEGIN CERTIFICATE-----".getBytes("US-ASCII"),"native provider truncated header remains rejected");
        }
        rejectCertificate(bc,"-----END CERTIFICATE-----\n".getBytes("US-ASCII"),"footer without header");
        rejectCertificate(bc,"-----BEGIN CERTIFICATE-----\n-----END CRL-----\n".getBytes("US-ASCII"),"empty mismatched boundaries");
        System.out.println("PEM_EMPTY266_CONTRACT=PASS|checks="+checks+"|empty_record=no_certificate|nonempty_missing_footer=rejected|bad_signature=rejected|expired=rejected|real_CRL=true|native_provider=unchanged");
    }
}
