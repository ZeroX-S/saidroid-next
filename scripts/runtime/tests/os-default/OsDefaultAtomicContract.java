import java.io.File;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import libcore.io.*;

/** Real process OS CAS with concurrent contenders, actual delegated rename and restoration. */
public final class OsDefaultAtomicContract {
    private static int checks;
    private static void check(boolean v,String why) {checks++;if(!v)throw new AssertionError(why);}
    public static void run() throws Exception {
        Os initial = Os.getDefault();
        check(initial == Libcore.os && initial == Libcore.getOs(), "actual shared OS state");
        check(Modifier.isVolatile(Libcore.class.getField("os").getModifiers()), "canonical volatile publication");
        check(initial != Libcore.rawOs, "guarded default retained");
        try { Os.compareAndSetDefault(initial,null);throw new AssertionError("null accepted"); }
        catch(NullPointerException expected) { checks++; }
        check(Os.getDefault() == initial, "null update preserved state");
        final AtomicInteger renameCalls = new AtomicInteger();
        Os delegate = new ForwardingOs(initial) {
            public void rename(String from,String to)throws android.system.ErrnoException {
                renameCalls.incrementAndGet();super.rename(from,to);
            }
            public String toString() { return "actual-delegated-os"; }
        };
        check(new ForwardingOs(delegate){}.toString().contains("actual-delegated-os"), "delegate description");
        try { new ForwardingOs(null){};throw new AssertionError("null delegate accepted"); }
        catch(NullPointerException expected) { checks++; }
        check(!Os.compareAndSetDefault(null,delegate) && Os.getDefault()==initial, "wrong expect rejected");
        Path dir=Files.createTempDirectory("os-atomic-contract");Path source=dir.resolve("before"),target=dir.resolve("after");
        try {
            Files.write(source,new byte[]{19,85,2});
            check(Os.compareAndSetDefault(initial,delegate),"install real delegate");
            android.system.Os.rename(source.toString(),target.toString());
            check(renameCalls.get()==1 && !Files.exists(source) && Files.readAllBytes(target)[1]==85,"actual system call routed and executed");
        } finally {
            if(Os.getDefault()==delegate)check(Os.compareAndSetDefault(delegate,initial),"restore real delegate");
            Files.deleteIfExists(source);Files.deleteIfExists(target);Files.deleteIfExists(dir);
        }
        final int rounds=64, contenders=8;ExecutorService pool=Executors.newFixedThreadPool(contenders);
        try {
            for(int round=0;round<rounds;round++) {
                CountDownLatch ready=new CountDownLatch(contenders),go=new CountDownLatch(1);
                AtomicInteger winners=new AtomicInteger();AtomicReference<Os> winning=new AtomicReference<>();List<Future<?>> tasks=new ArrayList<>();
                for(int i=0;i<contenders;i++) {
                    Os candidate=new ForwardingOs(initial){};
                    tasks.add(pool.submit(()->{
                        ready.countDown();if(!go.await(5,TimeUnit.SECONDS))throw new AssertionError("contenders not released");
                        if(Os.compareAndSetDefault(initial,candidate)) { winners.incrementAndGet();winning.set(candidate); }
                        return null;
                    }));
                }
                check(ready.await(5,TimeUnit.SECONDS),"all contenders ready");go.countDown();
                for(Future<?> task:tasks)task.get(5,TimeUnit.SECONDS);
                check(winners.get()==1,"exactly one atomic CAS winner");
                check(Os.getDefault()==winning.get()&&Libcore.os==winning.get(),"winning delegate published to both paths");
                check(Os.compareAndSetDefault(winning.get(),initial),"restore between rounds");
            }
        } finally {
            pool.shutdownNow();check(pool.awaitTermination(5,TimeUnit.SECONDS),"all owned threads terminated");
            Os current=Os.getDefault();if(current!=initial)Os.compareAndSetDefault(current,initial);
        }
        check(Os.getDefault()==initial,"initial actual OS restored");
        System.out.println("OS_DEFAULT_ATOMIC_CONTRACT=PASS|checks="+checks+"|rounds=64|contenders=8|real_delegated_rename=true|all_threads_closed=true|initial_os_restored=true");
    }
}
