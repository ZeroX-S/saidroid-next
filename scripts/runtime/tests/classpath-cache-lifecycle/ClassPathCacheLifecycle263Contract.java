import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.lang.ref.WeakReference;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.jar.*;
import libcore.io.ClassPathURLStreamHandler;
import dalvik.system.CloseGuard;

/** Actual cached/uncached archive ownership, GC reclamation and signed-resource checks. */
public final class ClassPathCacheLifecycle263Contract {
    static int checks;
    static final String TEXT="SailDroid real signed JAR contract\n";
    static void check(boolean ok,String name){if(!ok)throw new AssertionError(name);checks++;}
    static int fds(String name)throws Exception{
        String path=new File(name).getCanonicalPath();int count=0;
        for(String fd:new File("/proc/self/fd").list())try{
            if(Files.readSymbolicLink(Paths.get("/proc/self/fd",fd)).toString().equals(path))count++;
        }catch(IOException gone){}
        return count;
    }
    static byte[] bytes(InputStream input)throws Exception{
        try(InputStream in=input;ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] b=new byte[7];int n;while((n=in.read(b))!=-1)out.write(b,0,n);return out.toByteArray();
        }
    }
    static void content(InputStream input)throws Exception{check(TEXT.equals(new String(bytes(input),"UTF-8")),"actual signed content");}
    static boolean closed(JarFile f){try{f.size();return false;}catch(IllegalStateException yes){return true;}}
    static WeakReference<ClassPathURLStreamHandler> abandoned(String name)throws Exception{
        ClassPathURLStreamHandler h=new ClassPathURLStreamHandler(name,true);
        JarURLConnection c=(JarURLConnection)h.getEntryUrlOrNull("payload.txt").openConnection();
        content(c.getInputStream());check(fds(name)==1,"live explicit cache owns one real FD");
        return new WeakReference<ClassPathURLStreamHandler>(h);
    }
    static WeakReference<ClassLoader> loaderRound(String name)throws Exception{
        ClassLoader loader=new dalvik.system.PathClassLoader(name,null);
        for(int i=0;i<32;i++){
            content(loader.getResourceAsStream("payload.txt"));
            check(fds(name)==0,"implicit ClassLoader stream closes archive while loader remains live");
        }
        URL resource=loader.getResource("payload.txt");
        JarURLConnection a=(JarURLConnection)resource.openConnection(),b=(JarURLConnection)resource.openConnection();
        check(a.getUseCaches()&&b.getUseCaches(),"returned URL has normal cached default");
        check(a.getJarFile()==b.getJarFile(),"explicit classloader URL connections share real archive");
        content(a.getInputStream());check(!closed(b.getJarFile()),"stream close leaves shared explicit cache usable");
        return new WeakReference<ClassLoader>(loader);
    }
    static void reclaimed(WeakReference<?> owner,String name,Set<Throwable> pending)throws Exception{
        // Do not promote WeakReference.get() to a strong interpreter register before GC.
        for(int i=0;i<250;i++){
            System.gc();System.runFinalization();Thread.sleep(20);
        }
        check(owner.get()==null,"owner actually unreachable");
        check(fds(name)==0,"owner Cleaner actually closed real archive FD");
        check(pending.isEmpty(),"Cleaner paired all real CloseGuard acquisitions");
    }
    public static void run()throws Exception{
        final String valid=System.getProperty("saidroid.test.jar.valid"),tampered=System.getProperty("saidroid.test.jar.tampered");
        final Set<Throwable> pending=Collections.synchronizedSet(Collections.newSetFromMap(new IdentityHashMap<Throwable,Boolean>()));
        final int[] events={0,0};CloseGuard.Tracker old=CloseGuard.getTracker();boolean enabled=CloseGuard.isEnabled();
        try{
            CloseGuard.setEnabled(true);CloseGuard.setTracker(new CloseGuard.Tracker(){
                public void open(Throwable t){pending.add(t);synchronized(events){events[0]++;}}
                public void close(Throwable t){if(t!=null){pending.remove(t);synchronized(events){events[1]++;}}}
            });
            check(fds(valid)==0,"no preexisting fixture archive FD");
            ClassPathURLStreamHandler legacy=new ClassPathURLStreamHandler(valid);
            check(fds(valid)==1&&!pending.isEmpty(),"legacy cache remains real and CloseGuard active");legacy.close();
            check(fds(valid)==0&&pending.isEmpty(),"legacy explicit close");
            final ClassPathURLStreamHandler handler=new ClassPathURLStreamHandler(valid,true);
            check(fds(valid)==0&&pending.isEmpty(),"scoped metadata constructor leaves no open FD");
            for(int i=0;i<64;i++){
                URL url=handler.getEntryUrlOrNull("payload.txt");check(url!=null&&handler.getEntryUrlOrNull("missing.txt")==null,"real metadata lookup");
                JarURLConnection c=(JarURLConnection)url.openConnection();c.setUseCaches(false);
                check(c.getContentLength()==35&&fds(valid)==0&&pending.isEmpty(),"metadata has no retained archive");
                JarFile owned=c.getJarFile();content(c.getInputStream());
                check(c.getJarEntry().getCertificates()!=null,"real signature verified");
                check(closed(owned)&&fds(valid)==0&&pending.isEmpty(),"uncached stream closes owned real archive and guard");
                try{c.getInputStream();throw new AssertionError("uncached closed connection reused");}catch(IllegalStateException expected){checks++;}
            }
            final AtomicReference<Throwable> error=new AtomicReference<Throwable>();Thread[] workers=new Thread[4];
            for(int i=0;i<workers.length;i++){
                workers[i]=new Thread(new Runnable(){public void run(){try{for(int j=0;j<16;j++){
                    URLConnection c=handler.getEntryUrlOrNull("payload.txt").openConnection();c.setUseCaches(false);
                    if(!TEXT.equals(new String(bytes(c.getInputStream()),"UTF-8")))throw new AssertionError("concurrent bytes");
                }}catch(Throwable t){error.compareAndSet(null,t);}}});workers[i].start();
            }
            for(Thread w:workers)w.join();check(error.get()==null,"concurrent independent uncached reads: "+error.get());
            check(fds(valid)==0&&pending.isEmpty(),"all concurrent real FDs and guards released");
            URL resource=handler.getEntryUrlOrNull("payload.txt");JarURLConnection a=(JarURLConnection)resource.openConnection(),b=(JarURLConnection)resource.openConnection();
            check(a!=b&&a.getUseCaches()&&b.getUseCaches(),"distinct explicit cached connections");
            JarFile shared=a.getJarFile();check(shared==b.getJarFile()&&fds(valid)==1&&!pending.isEmpty(),"cache shares actual JarFile and one live FD");
            content(a.getInputStream());check(a.getJarFile()==shared&&!closed(shared),"cached connection remains usable after stream close");content(b.getInputStream());
            JarURLConnection no=(JarURLConnection)resource.openConnection();no.setUseCaches(false);JarFile separate=no.getJarFile();check(separate!=shared&&!closed(separate)&&!closed(shared),"uncached JarFile is distinct and both real archives remain readable");content(no.getInputStream());
            check(closed(separate)&&!closed(shared)&&fds(valid)==1,"uncached close leaves shared cache alive");
            handler.close();check(closed(shared)&&fds(valid)==0&&pending.isEmpty(),"owner explicit close cleans real cache");
            try{handler.getEntryUrlOrNull("payload.txt");throw new AssertionError("closed owner accepted lookup");}catch(IllegalStateException expected){checks++;}
            ClassPathURLStreamHandler bad=new ClassPathURLStreamHandler(tampered,true);
            for(int i=0;i<16;i++){
                JarURLConnection c=(JarURLConnection)bad.getEntryUrlOrNull("payload.txt").openConnection();c.setUseCaches(false);
                try{bytes(c.getInputStream());throw new AssertionError("tampered signed content accepted");}catch(SecurityException expected){checks++;}
                check(fds(tampered)==0&&pending.isEmpty(),"signature rejection closes actual archive and guard");
            }
            bad.close();System.out.println("CACHE263_GC=handler-owner-start");reclaimed(abandoned(valid),valid,pending);System.out.println("CACHE263_GC=loader-owner-start");reclaimed(loaderRound(valid),valid,pending);
            check(CloseGuard.isEnabled()&&pending.isEmpty()&&events[0]>256&&events[0]==events[1],"all real CloseGuard opens paired; policy never disabled");
            System.out.println("CLASSPATH_CACHE_LIFECYCLE263_CONTRACT=PASS|checks="+checks+"|guard_opens="+events[0]+"|guard_closes="+events[1]+"|actual_FD_cleanup=true|explicit_shared_cache=true|uncached_streams=true|owner_gc_cleanup=true|signed_tamper_rejected=16");
        }finally{CloseGuard.setTracker(old);CloseGuard.setEnabled(enabled);}
    }
}
