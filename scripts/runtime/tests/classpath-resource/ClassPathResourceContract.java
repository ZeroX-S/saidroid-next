import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.jar.*;
import libcore.io.ClassPathURLStreamHandler;
import dalvik.system.CloseGuard;

/** Checks actual archive FD/CloseGuard lifetimes, concurrent streams and signed resources. */
public final class ClassPathResourceContract {
    static int checks;
    static void require(boolean value,String why){if(!value)throw new AssertionError(why);checks++;}
    static int fds(String path)throws Exception{
        int n=0;String canonical=new File(path).getCanonicalPath();
        for(String entry:new File("/proc/self/fd").list()){
            try{if(Files.readSymbolicLink(Paths.get("/proc/self/fd",entry)).toString().equals(canonical))n++;}
            catch(IOException vanished){}
        }
        return n;
    }
    static byte[] read(InputStream input)throws Exception{
        try(InputStream stream=input;ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] buffer=new byte[7];int n;while((n=stream.read(buffer))!=-1)out.write(buffer,0,n);return out.toByteArray();
        }
    }
    public static void run()throws Exception{
        String valid=System.getProperty("saidroid.test.jar.valid"),bad=System.getProperty("saidroid.test.jar.tampered");
        final Set<Throwable> pending=Collections.synchronizedSet(Collections.newSetFromMap(new IdentityHashMap<Throwable,Boolean>()));
        final int[] events={0,0};CloseGuard.Tracker old=CloseGuard.getTracker();boolean enabled=CloseGuard.isEnabled();
        try{
            CloseGuard.setEnabled(true);CloseGuard.setTracker(new CloseGuard.Tracker(){public void open(Throwable site){pending.add(site);synchronized(events){events[0]++;}}public void close(Throwable site){if(site!=null){pending.remove(site);synchronized(events){events[1]++;}}}});
            int initial=fds(valid);require(initial==0,"No preexisting fixture archive FD");
            ClassPathURLStreamHandler legacy=new ClassPathURLStreamHandler(valid);
            require(fds(valid)>initial&&!pending.isEmpty(),"Legacy cached API and CloseGuard actually active");legacy.close();
            require(fds(valid)==initial&&pending.isEmpty(),"Legacy explicit close releases actual FD/guard");
            ClassPathURLStreamHandler scoped=new ClassPathURLStreamHandler(valid,true);
            require(fds(valid)==initial&&pending.isEmpty(),"Scoped constructor closes validation archive");
            for(int i=0;i<128;i++){
                URL url=scoped.getEntryUrlOrNull("payload.txt");require(url!=null,"Actual resource lookup");
                require(scoped.getEntryUrlOrNull("missing.txt")==null,"Actual missing entry");
                JarURLConnection connection=(JarURLConnection)url.openConnection();
                require(connection.getContentLength()==35,"Metadata reads real entry length");
                require(fds(valid)==initial&&pending.isEmpty(),"Lookup and metadata leave no real FD/guard");
                byte[] actual=read(connection.getInputStream());
                require(new String(actual,"UTF-8").equals("SailDroid real signed JAR contract\n"),"Actual signed bytes");
                require(connection.getJarEntry().getCertificates()!=null,"Signed stream verified actual certificate");
                require(fds(valid)==initial&&pending.isEmpty(),"Stream close releases archive FD/guard");
            }
            final AtomicReference<Throwable> failure=new AtomicReference<>();Thread[] workers=new Thread[4];
            for(int n=0;n<workers.length;n++){
                workers[n]=new Thread(new Runnable(){public void run(){try{for(int i=0;i<32;i++)if(!new String(read(scoped.getEntryUrlOrNull("payload.txt").openStream()),"UTF-8").equals("SailDroid real signed JAR contract\n"))throw new AssertionError("Concurrent resource bytes");}catch(Throwable t){failure.compareAndSet(null,t);}}});workers[n].start();
            }
            for(Thread worker:workers)worker.join();require(failure.get()==null,"Concurrent resource streams independent: "+failure.get());
            require(fds(valid)==initial&&pending.isEmpty(),"Concurrent stream FDs and guards all closed");
            ClassPathURLStreamHandler corrupted=new ClassPathURLStreamHandler(bad,true);
            for(int i=0;i<16;i++){
                try{read(corrupted.getEntryUrlOrNull("payload.txt").openStream());throw new AssertionError("Tampered signed resource accepted");}
                catch(SecurityException expected){checks++;}
                require(fds(bad)==0&&pending.isEmpty(),"Failed signature stream closes real archive");
            }
            corrupted.close();scoped.close();
            try{scoped.getEntryUrlOrNull("payload.txt");throw new AssertionError("Closed handler lookup accepted");}catch(IllegalStateException expected){checks++;}
            require(pending.isEmpty()&&events[0]>512&&events[0]==events[1],"All actual archive CloseGuard opens/close paired");
        }finally{CloseGuard.setTracker(old);CloseGuard.setEnabled(enabled);}
        System.out.println("CLASSPATH_RESOURCE_CONTRACT=PASS|checks="+checks+"|lookup_rounds=128|concurrent_reads=128|tampered_rejected=16|fd_cleanup=true|closeguard=active-and-paired|legacy_cache=retained");
    }
}
