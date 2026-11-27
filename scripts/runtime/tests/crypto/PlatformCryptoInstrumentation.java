package org.example.saildroid.platformcrypto;
import android.app.Instrumentation;
import android.os.Bundle;
import java.security.Security;
import java.util.Arrays;
import javax.crypto.*;
import javax.crypto.spec.*;

/** Internal known-answer/negative crypto checks; never counted as official CTS. */
public final class PlatformCryptoInstrumentation extends Instrumentation {
    private static byte[] hex(String s){byte[] b=new byte[s.length()/2];for(int i=0;i<b.length;i++)b[i]=(byte)Integer.parseInt(s.substring(i*2,i*2+2),16);return b;}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void runChecks()throws Exception {
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
        require(javax.net.ssl.SSLContext.getInstance("TLS").getProvider().getName().equals("AndroidOpenSSL"),"matching Android TLS provider selected");
        require(javax.net.ssl.SSLSocketFactory.getDefault().getClass().getName().equals("com.android.org.conscrypt.OpenSSLSocketFactoryImpl"),"matching Android default socket factory");
        javax.net.ssl.SSLParameters parameters=new javax.net.ssl.SSLParameters();
        String[] protocols={"h2","http/1.1"};parameters.setApplicationProtocols(protocols);protocols[0]="mutated";
        require(parameters.getApplicationProtocols()[0].equals("h2"),"ALPN input defensively copied");
        String[] returned=parameters.getApplicationProtocols();returned[0]="mutated";
        require(parameters.getApplicationProtocols()[0].equals("h2"),"ALPN result defensively copied");
        boolean badAlpn=false;try{parameters.setApplicationProtocols(new String[]{""});}catch(IllegalArgumentException expected){badAlpn=true;}
        require(badAlpn,"Empty ALPN protocol rejected");
        Cipher gcm=Cipher.getInstance("AES/GCM/NoPadding");
        require(gcm.getProvider().getName().equals("AndroidOpenSSL"),"real Android native AES provider");
        gcm.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(new byte[16],"AES"),new javax.crypto.spec.GCMParameterSpec(128,new byte[12]));
        byte[] sealed=gcm.doFinal(new byte[16]);
        require(Arrays.equals(sealed,hex("0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf")),"NIST AES-GCM known answer");
        gcm.init(Cipher.DECRYPT_MODE,new SecretKeySpec(new byte[16],"AES"),new javax.crypto.spec.GCMParameterSpec(128,new byte[12]));
        require(Arrays.equals(gcm.doFinal(sealed),new byte[16]),"AES-GCM authenticated decrypt");
        sealed[sealed.length-1]^=1;
        gcm.init(Cipher.DECRYPT_MODE,new SecretKeySpec(new byte[16],"AES"),new javax.crypto.spec.GCMParameterSpec(128,new byte[12]));
        boolean badTag=false;try{gcm.doFinal(sealed);}catch(javax.crypto.AEADBadTagException expected){badTag=true;}
        require(badTag,"AES-GCM modified tag rejected");
        // The alias overlay must not impersonate the platform AES provider.
        require(!Cipher.getInstance("AES/GCM/NoPadding").getProvider().getName().equals("SailDroidCryptoCompat"),"existing AES provider retained");
        boolean rejected=false;try{SecretKeyFactory.getInstance("SailDroidImaginaryAlgorithm");}catch(java.security.NoSuchAlgorithmException expected){rejected=true;}
        require(rejected,"unknown algorithms still fail");
        System.out.println("PLATFORM_CRYPTO=PASS|desede_known_answer=true|rc4_rfc6229=true|aes_provider_retained=true|unknown_rejected=true|platform_tls=AndroidOpenSSL|aes_gcm_nist=true|bad_tag=rejected");
    }
    @Override public void onCreate(Bundle arguments){super.onCreate(arguments);start();}
    @Override public void onStart(){
        Bundle event=new Bundle();event.putString("class",getClass().getName());event.putString("test","platformKnownAnswers");event.putInt("numtests",1);sendStatus(1,event);
        Bundle result=new Bundle();
        try {runChecks();sendStatus(0,event);result.putString("stream","OK (1 test)\n");finish(-1,result);}
        catch(Throwable failure){event.putString("stack",android.util.Log.getStackTraceString(failure));sendStatus(-2,event);result.putString("stream","FAILURES!!! Tests run: 1, Failures: 1\n");result.putString("shortMsg",failure.toString());finish(-1,result);}
    }
}
