import java.io.*;
import java.util.concurrent.TimeUnit;

/** One finite child per refresh. Child has no mutation/API arguments and no shell. */
final class SdConnectivityHostProvider implements SdConnectivity.Provider {
    private final String executable;
    private final SdConnectivitySnapshot.Identities identities=new SdConnectivitySnapshot.Identities();
    SdConnectivityHostProvider(){this(System.getenv("ANDROID_ROOT")+"/libexec/saildroid-network-snapshot");}
    SdConnectivityHostProvider(String executable){this.executable=executable;}
    public SdConnectivitySnapshot read()throws IOException{
        Process child=null;InputStream input=null;long deadline=System.nanoTime()+1250000000L;
        try{
            ProcessBuilder builder=new ProcessBuilder(executable);builder.redirectErrorStream(true);
            // Native host helper uses host GLib/GIO, not the Android/Bionic preload namespace.
            builder.environment().remove("LD_PRELOAD");builder.environment().remove("LD_LIBRARY_PATH");
            child=builder.start();input=child.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[]chunk=new byte[8192];
            for(;;){
                int available=input.available();
                while(available>0){int n=input.read(chunk,0,Math.min(chunk.length,available));if(n<0)break;bytes.write(chunk,0,n);if(bytes.size()>262144)throw new IOException("Host network snapshot output limit");available=input.available();}
                if(child.waitFor(5,TimeUnit.MILLISECONDS)){
                    // The trusted helper never forks. Drain ready bytes only, so even a faulty
                    // inherited pipe cannot turn the exit path into an unbounded EOF wait.
                    while(input.available()>0){int n=input.read(chunk,0,Math.min(chunk.length,input.available()));if(n<0)break;bytes.write(chunk,0,n);if(bytes.size()>262144)throw new IOException("Host network snapshot output limit");}
                    if(child.exitValue()!=0)throw new IOException("Host network snapshot unavailable (helper status "+child.exitValue()+")");
                    return SdConnectivitySnapshot.parse(new String(bytes.toByteArray(),"UTF-8"),identities);
                }
                if(System.nanoTime()>=deadline)throw new IOException("Host network snapshot deadline");
            }
        }catch(InterruptedException e){Thread.currentThread().interrupt();throw new IOException("Host network snapshot interrupted",e);}
        finally{
            if(child!=null){if(child.isAlive())child.destroyForcibly();try{child.waitFor(250,TimeUnit.MILLISECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}}
            if(input!=null)try{input.close();}catch(IOException ignored){}
            if(child!=null){try{child.getErrorStream().close();}catch(IOException ignored){}try{child.getOutputStream().close();}catch(IOException ignored){}}
        }
    }
}
