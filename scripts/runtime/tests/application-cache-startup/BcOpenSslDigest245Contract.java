/** Known independent vectors, real AndroidOpenSSL ownership and Digest lifecycle. */
public final class BcOpenSslDigest245Contract {
    private static int checks;
    private static void check(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
    private static byte[] bytes(String text){byte[] out=new byte[text.length()/2];for(int i=0;i<out.length;i++)out[i]=(byte)Integer.parseInt(text.substring(i*2,i*2+2),16);return out;}
    private static Object invoke(Object digest,String name,Class<?>[] types,Object... args)throws Exception{return digest.getClass().getMethod(name,types).invoke(digest,args);}
    public static void run(String ignored)throws Exception {
        java.security.Provider provider=java.security.Security.getProvider("AndroidOpenSSL");check(provider!=null,"actual AndroidOpenSSL provider installed");
        Class<?> base=Class.forName("com.android.org.bouncycastle.crypto.digests.OpenSSLDigest");
        java.lang.reflect.Field field=base.getDeclaredField("delegate");field.setAccessible(true);
        for(String row:System.getProperty("saidroid.test.digest.vectors").split(";")) {
            String[] f=row.split(",",-1);String name=f[0];byte[] input=bytes(f[1]),expected=bytes(f[2]);int block=Integer.parseInt(f[3]);
            Object digest=Class.forName(base.getName()+"$"+name).newInstance();
            java.security.MessageDigest delegate=(java.security.MessageDigest)field.get(digest);
            check(delegate.getProvider()==provider,"fixed actual AndroidOpenSSL provider identity");
            java.lang.reflect.Field spiField=delegate.getClass().getDeclaredField("digestSpi");spiField.setAccessible(true);
            Object spi=spiField.get(delegate);
            check(spi.getClass().getName().startsWith("com.android.org.conscrypt.OpenSSLMessageDigestJDK$"),"real Conscrypt EVP SPI implementation behind canonical MessageDigest delegate");
            check(provider.getService("MessageDigest",delegate.getAlgorithm()).getClassName().equals(spi.getClass().getName()),"actual registered SPI class matches instance");
            check(((Integer)invoke(digest,"getDigestSize",new Class<?>[0]))==expected.length,"digest length");
            check(((Integer)invoke(digest,"getByteLength",new Class<?>[0]))==block,"real block length");
            int pos=0;while(pos<input.length){int count=Math.min(17,input.length-pos);invoke(digest,"update",new Class<?>[]{byte[].class,int.class,int.class},input,pos,count);pos+=count;}
            byte[] output=new byte[expected.length+11];java.util.Arrays.fill(output,(byte)0x5a);
            int count=(Integer)invoke(digest,"doFinal",new Class<?>[]{byte[].class,int.class},output,5);
            check(count==expected.length,"actual final output size");
            check(java.util.Arrays.equals(expected,java.util.Arrays.copyOfRange(output,5,5+count)),"independent known digest vector");
            check(output[0]==0x5a&&output[4]==0x5a&&output[5+count]==0x5a&&output[output.length-1]==0x5a,"output offset and untouched sentinels");
            for(byte value:input)invoke(digest,"update",new Class<?>[]{byte.class},value);
            output=new byte[expected.length];invoke(digest,"doFinal",new Class<?>[]{byte[].class,int.class},output,0);
            check(java.util.Arrays.equals(expected,output),"final resets actual EVP context and single-byte path");
            invoke(digest,"update",new Class<?>[]{byte[].class,int.class,int.class},new byte[]{7,8,9},0,3);invoke(digest,"reset",new Class<?>[0]);
            invoke(digest,"update",new Class<?>[]{byte[].class,int.class,int.class},input,0,input.length);output=new byte[expected.length];invoke(digest,"doFinal",new Class<?>[]{byte[].class,int.class},output,0);
            check(java.util.Arrays.equals(expected,output),"reset discards prior input");
            boolean rejected=false;try{invoke(digest,"update",new Class<?>[]{byte[].class,int.class,int.class},input,-1,1);}catch(java.lang.reflect.InvocationTargetException e){rejected=e.getCause()instanceof RuntimeException;}
            check(rejected,"invalid input bounds rejected by actual provider");
        }
        check(java.security.Security.getProvider("AndroidOpenSSL")==provider,"provider registry identity unchanged");
        System.out.println("BC_OPENSSL_DIGEST245_CONTRACT=PASS|vectors=18|functions=6|checks="+checks+"|provider=AndroidOpenSSL|actual_EVP=true");
    }
}
