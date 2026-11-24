import android.system.ErrnoException;
import android.system.Int64Ref;
import android.system.Os;
import android.system.OsConstants;
import java.io.File;
import java.io.FileDescriptor;
import java.io.RandomAccessFile;
import java.util.Arrays;

/** Real kernel copies, nullable offsets, 64-bit offsets and preserved legacy ABI. */
public final class SendfileCarrierContract {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void content(RandomAccessFile file, byte[] expected) throws Exception {
        require(file.length() == expected.length, "Output length differs");
        byte[] actual = new byte[expected.length];
        file.seek(0); file.readFully(actual);
        require(Arrays.equals(actual, expected), "Output bytes differ");
    }
    public static void main(String[] args) throws Exception {
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(29);
        require(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion() == 29, "Actual SDK binding");
        File root = new File(args[0]);
        require(root.isDirectory() && root.list().length == 0, "Empty owned fixture required");
        File input = new File(root, "input"), output = new File(root, "output");
        try (RandomAccessFile in = new RandomAccessFile(input, "rw");
             RandomAccessFile out = new RandomAccessFile(output, "rw")) {
            byte[] bytes = {11,22,33,44,55,66};
            in.write(bytes); in.seek(1);
            Int64Ref offset = new Int64Ref(2);
            require(Os.sendfile(out.getFD(), in.getFD(), offset, 3) == 3, "Explicit copy count");
            require(offset.value == 5 && in.getFilePointer() == 1, "Explicit offset semantics");
            content(out, new byte[]{33,44,55});
            out.setLength(0); out.seek(0); in.seek(2);
            require(Os.sendfile(out.getFD(), in.getFD(), (Int64Ref)null, 3) == 3, "Null copy count");
            require(in.getFilePointer() == 5, "Null offset must advance kernel position");
            content(out, new byte[]{33,44,55});
            offset.value = 6;
            require(Os.sendfile(out.getFD(), in.getFD(), offset, 8) == 0 && offset.value == 6, "EOF");
            offset.value = 3;
            require(Os.sendfile(out.getFD(), in.getFD(), offset, 0) == 0 && offset.value == 3, "Zero count");
            offset.value = 123;
            try { Os.sendfile(new FileDescriptor(), in.getFD(), offset, 1); throw new AssertionError("Bad FD accepted"); }
            catch (ErrnoException expected) { require(expected.errno == OsConstants.EBADF && offset.value == 123, "EBADF/copyout"); }
            offset.value = -1;
            try { Os.sendfile(out.getFD(), in.getFD(), offset, 1); throw new AssertionError("Negative offset accepted"); }
            catch (ErrnoException expected) { require(expected.errno == OsConstants.EINVAL && offset.value == -1, "EINVAL/copyout"); }
            Class<?> legacy = Class.forName("android.util.MutableLong");
            Object oldOffset = legacy.getConstructor(long.class).newInstance(1L);
            out.setLength(0); out.seek(0);
            long count = (Long)Os.class.getMethod("sendfile", FileDescriptor.class, FileDescriptor.class, legacy, long.class)
                    .invoke(null, out.getFD(), in.getFD(), oldOffset, 2L);
            require(count == 2 && legacy.getField("value").getLong(oldOffset) == 3, "Legacy ABI");
            content(out, new byte[]{22,33});
            long large = (1L << 32) + 7;
            in.seek(large); in.write(new byte[]{77,88,99});
            out.setLength(0); out.seek(0); offset.value = large;
            require(Os.sendfile(out.getFD(), in.getFD(), offset, 3) == 3 && offset.value == large + 3, "64-bit offset");
            content(out, new byte[]{77,88,99});
        } finally {
            require(input.delete() && output.delete(), "Fixture cleanup");
        }
        System.out.println("SENDFILE_CARRIER_CONTRACT=PASS|explicit_and_null_offset=true|real_bytes=true|legacy_abi=true|errno=true|offset64=true");
    }
}
