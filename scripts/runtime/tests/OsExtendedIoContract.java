/** Own real-kernel contracts for the new splice binding; never a CTS replacement. */
import android.system.ErrnoException;
import android.system.Int64Ref;
import android.system.Os;
import android.system.OsConstants;
import dalvik.system.BlockGuard;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InterruptedIOException;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public final class OsExtendedIoContract {
    private static int checks;
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
        checks++;
    }
    public static void main(String[] args) throws Exception {
        String[] names = {"O_DIRECT", "SPLICE_F_MOVE", "SPLICE_F_NONBLOCK", "SPLICE_F_MORE"};
        for (String name : names) {
            int expected = Integer.parseInt(System.getProperty("saidroid.test.constant." + name));
            require(OsConstants.class.getField(name).getInt(null) == expected, name + " differs from actual C headers");
        }
        File dir = Files.createTempDirectory(new File(System.getenv("TMPDIR")).toPath(), "splice-own-").toFile();
        File input = new File(dir, "input"), output = new File(dir, "output");
        Files.write(input.toPath(), new byte[]{'f','o','o','b','a','r'});
        FileDescriptor[] pipe = Os.pipe2(0);
        try (FileInputStream in = new FileInputStream(input); FileOutputStream out = new FileOutputStream(output)) {
            Int64Ref offIn = new Int64Ref(1), offOut = new Int64Ref(0);
            final AtomicInteger reads = new AtomicInteger(), writes = new AtomicInteger();
            BlockGuard.Policy previous = BlockGuard.getThreadPolicy();
            BlockGuard.setThreadPolicy(new BlockGuard.Policy() {
                public void onWriteToDisk() { writes.incrementAndGet(); }
                public void onReadFromDisk() { reads.incrementAndGet(); }
                public void onNetwork() { throw new AssertionError("Unexpected network callback"); }
                public void onUnbufferedIO() {}
                public void onExplicitGc() {}
                public int getPolicyMask() { return 0; }
            });
            try {
                require(Os.splice(in.getFD(), offIn, pipe[1], null, 10, OsConstants.SPLICE_F_MORE) == 5, "Actual file-to-pipe result");
                require(offIn.value == 6, "Actual input Int64Ref update");
                require(Os.splice(pipe[0], null, out.getFD(), offOut, 10, OsConstants.SPLICE_F_MOVE) == 5, "Actual pipe-to-file result");
                require(offOut.value == 5, "Actual output Int64Ref update");
                require(reads.get() == 2 && writes.get() == 2, "Both canonical disk policy callbacks required per splice");
            } finally { BlockGuard.setThreadPolicy(previous); }
            require(in.getChannel().position() == 0 && out.getChannel().position() == 0, "Explicit offsets must preserve descriptor positions");
            require(Arrays.equals(Files.readAllBytes(output.toPath()), new byte[]{'o','o','b','a','r'}), "Actual kernel-transferred bytes");
            long before = offOut.value;
            try { Os.splice(pipe[0], null, out.getFD(), offOut, 1, OsConstants.SPLICE_F_NONBLOCK); throw new AssertionError("Empty nonblocking pipe did not fail"); }
            catch (ErrnoException e) { require(e.errno == OsConstants.EAGAIN, "Actual nonblocking EAGAIN"); }
            require(offOut.value == before, "Failed splice must preserve offset carrier");
        } finally { Os.close(pipe[0]); Os.close(pipe[1]); }

        final FileDescriptor[] blockedPipe = Os.pipe2(0);
        final CountDownLatch entered = new CountDownLatch(1);
        final AtomicInteger tid = new AtomicInteger();
        final AtomicReference<Throwable> result = new AtomicReference<>();
        try (FileOutputStream out = new FileOutputStream(output)) {
            Thread blocked = new Thread(new Runnable() { public void run() {
                tid.set(Os.gettid()); entered.countDown();
                try { Os.splice(blockedPipe[0], null, out.getFD(), null, 1, 0); result.set(new AssertionError("Unexpected blocking splice completion")); }
                catch (Throwable e) { result.set(e); }
            }}, "own-splice-interruption");
            blocked.start();
            require(entered.await(3, TimeUnit.SECONDS), "Owned worker started");
            String syscall = System.getProperty("saidroid.test.splice.syscall");
            boolean inNative = false;
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (System.nanoTime() < deadline && blocked.isAlive()) {
                String actual = new String(Files.readAllBytes(new File("/proc/self/task/" + tid.get() + "/syscall").toPath()), "UTF-8");
                if (actual.startsWith(syscall + " ")) { inNative = true; break; }
                Thread.sleep(10);
            }
            require(inNative, "Actual owned worker must enter the kernel splice syscall before close");
            System.out.println("OS_EXTENDED_IO_BLOCKED=verified|tid=" + tid.get() + "|syscall=" + syscall);
            libcore.io.IoBridge.closeAndSignalBlockedThreads(blockedPipe[0]);
            blocked.join(3000);
            require(!blocked.isAlive(), "Actual asynchronous close must release blocked splice");
            require(result.get() instanceof InterruptedIOException, "Actual asynchronous close must throw InterruptedIOException: " + result.get());
        } finally {
            // The read descriptor is already invalid after the canonical close.
            if (blockedPipe[0].valid()) libcore.io.IoBridge.closeAndSignalBlockedThreads(blockedPipe[0]);
            Os.close(blockedPipe[1]);
            Files.deleteIfExists(input.toPath()); Files.deleteIfExists(output.toPath()); Files.delete(dir.toPath());
        }
        System.out.println("OS_EXTENDED_IO_CONTRACT=PASS|checks=" + checks + "|kernel_splice=true|real_offset_updates=true|blockguard_notifications=true|async_close=true|owned_files_removed=true");
    }
}
