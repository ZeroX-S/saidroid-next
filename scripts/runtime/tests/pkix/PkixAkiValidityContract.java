import java.io.File;
import java.io.FileInputStream;
import java.security.cert.*;
import java.util.*;
/** Current-time PKIX diagnostic with fresh owned public certificates and unchanged expired CTS constants. */
public final class PkixAkiValidityContract {
    private static X509Certificate cert(File directory,String name) throws Exception {
        try(FileInputStream in=new FileInputStream(new File(directory,name))) {
            return (X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(in);
        }
    }
    private static CertPathBuilderResult build(X509Certificate root,X509Certificate intermediate,X509Certificate end) throws Exception {
        X509CertSelector selector=new X509CertSelector();selector.setCertificate(end);
        PKIXBuilderParameters parameters=new PKIXBuilderParameters(Collections.singleton(new TrustAnchor(root,null)),selector);
        parameters.setRevocationEnabled(false);
        parameters.addCertStore(CertStore.getInstance("Collection",new CollectionCertStoreParameters(Arrays.asList(intermediate,end))));
        // Use the actual current wall clock, just as the original test does.
        if(parameters.getDate()!=null) throw new AssertionError("Unexpected date override");
        return CertPathBuilder.getInstance("PKIX").build(parameters);
    }
    public static void run(String folder) throws Exception {
        File directory=new File(folder);X509Certificate root=cert(directory,"fresh-root.der"),intermediate=cert(directory,"fresh-int.der"),end=cert(directory,"fresh-ee.der");
        for(X509Certificate c:new X509Certificate[]{root,intermediate,end})c.checkValidity();
        end.verify(intermediate.getPublicKey());intermediate.verify(root.getPublicKey());root.verify(root.getPublicKey());
        CertPathBuilderResult result=build(root,intermediate,end);
        if(result.getCertPath().getCertificates().size()!=2 || !result.getCertPath().getCertificates().get(0).equals(end))throw new AssertionError("Unexpected current-time fresh AKI path");
        X509Certificate oldRoot=cert(directory,"ROOT_CERT.der"),oldInt=cert(directory,"INT_CERT_WITH_KEYID_AKI.der"),oldEnd=cert(directory,"EE_CERT_WITH_FULL_AKI.der");
        int expired=0;for(X509Certificate c:new X509Certificate[]{oldRoot,oldInt,oldEnd}) {
            try{c.checkValidity();}catch(CertificateExpiredException expected){expired++;}
        }
        if(expired!=3)throw new AssertionError("Original certificate expiry differs: "+expired);
        boolean rejected=false;
        try{build(oldRoot,oldInt,oldEnd);}catch(CertPathBuilderException expected){rejected=true;}
        if(!rejected)throw new AssertionError("Expired original fixture was accepted");
        System.out.println("PKIX_AKI_VALIDITY=PASS|fresh_full_AKI_current_time=true|expired_original_rejected=true|original_expired=3|date_override=false|provider="+CertPathBuilder.getInstance("PKIX").getProvider().getName());
    }
}
