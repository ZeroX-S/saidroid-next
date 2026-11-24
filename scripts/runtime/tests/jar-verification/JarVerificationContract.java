import java.io.*;
import java.security.*;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.jar.*;
import sun.security.jca.Providers;

/** Actual platform crypto and signed JAR verification; no mock algorithms or trust overrides. */
public final class JarVerificationContract {
    static int checks;
    static void require(boolean value,String reason){if(!value)throw new AssertionError(reason);checks++;}
    static void signed(String path, boolean tampered)throws Exception{
        try(JarFile jar=new JarFile(path,true)){
            JarEntry entry=jar.getJarEntry("payload.txt");require(entry!=null,"Actual payload entry");
            byte[] data;try(InputStream stream=jar.getInputStream(entry)){
                ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[113];int n;
                while((n=stream.read(buffer))!=-1)bytes.write(buffer,0,n);data=bytes.toByteArray();
            }
            if(tampered)throw new AssertionError("Tampered signed payload accepted");
            require(new String(data,"UTF-8").equals("SailDroid real signed JAR contract\n"),"Actual signed payload bytes");
            java.security.cert.Certificate[] certs=entry.getCertificates();
            require(certs!=null&&certs.length==1,"Actual verified signer certificate");
            certs[0].verify(certs[0].getPublicKey());require(entry.getCodeSigners()!=null&&entry.getCodeSigners().length==1,"Actual verified code signer");
        }catch(SecurityException expected){if(!tampered)throw expected;checks++;}
    }
    public static void run()throws Exception{
        Provider[] original=Security.getProviders();Provider marker=new Provider("OwnUnlistedJarProvider",1.0,"Empty boundary marker"){};
        require(Security.addProvider(marker)>0,"Ordinary custom provider insertion");
        try{
            final Provider[] normal=Security.getProviders();final Throwable[] workerError={null};
            CountDownLatch go=new CountDownLatch(1),done=new CountDownLatch(1);
            Thread worker=new Thread(new Runnable(){public void run(){try{go.await();if(!Arrays.equals(normal,Security.getProviders()))throw new AssertionError("JAR provider list leaked to unrelated thread");}catch(Throwable t){workerError[0]=t;}finally{done.countDown();}}});worker.start();
            Object token=Providers.startJarVerification();
            try{
                Provider[] restricted=Security.getProviders();Set<String> expected=new HashSet<>(Arrays.asList("com.android.org.conscrypt.OpenSSLProvider","com.android.org.bouncycastle.jce.provider.BouncyCastleProvider","com.android.org.conscrypt.JSSEProvider","sun.security.provider.VerificationProvider"));
                require(restricted.length>=3&&restricted[0].getClass().getName().equals("com.android.org.conscrypt.OpenSSLProvider"),"Canonical first JAR crypto provider");
                for(Provider p:restricted)require(expected.contains(p.getClass().getName()),"Only canonical JAR providers: "+p.getClass());
                require(Security.getProvider(marker.getName())==null,"Unlisted ordinary provider excluded from JAR verification");
                go.countDown();done.await();require(workerError[0]==null,"Thread-local JAR provider boundary");
                SecureRandom random=SecureRandom.getInstance("SHA1PRNG");
                require(random.getProvider().getClass().getName().equals("com.android.org.conscrypt.OpenSSLProvider"),"Actual canonical JAR entropy provider");
                byte[] a=random.generateSeed(64),b=random.generateSeed(64);require(a.length==64&&b.length==64&&!Arrays.equals(a,b),"Real native entropy generation sanity");
                require(Providers.getSunProvider().getClass().getName().equals("com.android.org.conscrypt.OpenSSLProvider"),"Canonical verification fallback selector");
                Object nested=Providers.startJarVerification();Providers.stopJarVerification(nested);require(Arrays.equals(restricted,Security.getProviders()),"Nested list restores outer scope");
            }finally{Providers.stopJarVerification(token);go.countDown();worker.join();}
            require(Arrays.equals(normal,Security.getProviders())&&Security.getProvider(marker.getName())==marker,"Normal provider identity restored");
            String valid=System.getProperty("saidroid.test.jar.valid"),bad=System.getProperty("saidroid.test.jar.tampered");
            for(int i=0;i<16;i++){signed(valid,false);signed(bad,true);}
            require(Arrays.equals(normal,Security.getProviders()),"Signature checks restore normal provider identity");
        }finally{Security.removeProvider(marker.getName());}
        require(Arrays.equals(original,Security.getProviders()),"Global provider state restored");
        System.out.println("JAR_VERIFICATION_CONTRACT=PASS|checks="+checks+"|signed_rounds=16|tampered_rejected=16|entropy=actual-conscrypt|thread_scope=isolated|normal_providers=restored");
    }
}
