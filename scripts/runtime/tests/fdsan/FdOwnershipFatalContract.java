import java.io.*;
import libcore.io.Libcore;

/** A separate expendable VM process must abort before an unowned alias closes an owned FD. */
public final class FdOwnershipFatalContract {
    private static native void armFatalOwnership();
    private static native long[] alternateSignalStack();
    private static native void largeSignalStackDiagnostic();
    public static void run() throws Exception {
        System.load(System.getProperty("saidroid.test.fdsan.fatal.helper"));
        if(Boolean.getBoolean("saidroid.test.fdsan.large-altstack-diagnostic")) largeSignalStackDiagnostic();
        long[] alt=alternateSignalStack();
        System.out.println("FD_ALTSTACK=observed|base="+Long.toHexString(alt[0])+"|size="+alt[1]+"|native_sp="+Long.toHexString(alt[2]));
        System.out.flush();
        armFatalOwnership();
        try (FileInputStream stream = new FileInputStream("/dev/null")) {
            FileDescriptor fd=stream.getFD();
            long tag=Libcore.os.android_fdsan_get_owner_tag(fd);
            if(tag==0 || tag!=fd.getOwnerId$()) throw new AssertionError("Real owned descriptor required");
            FileDescriptor alias=new FileDescriptor();alias.setInt$(fd.getInt$());
            if(alias.getOwnerId$()!=0 || Libcore.os.android_fdsan_get_owner_tag(alias)!=tag)
                throw new AssertionError("Independent unowned Java alias required");
            System.out.println("FD_OWNERSHIP_FATAL=armed|uid="+android.system.Os.getuid()
                    +"|fd="+fd.getInt$()+"|actual_tag="+Long.toHexString(tag)+"|alias_owner=0");
            System.out.flush();
            Libcore.os.close(alias);
            throw new AssertionError("Mismatched owner close returned instead of aborting");
        }
    }
}
