import android.system.ErrnoException;
import android.system.Int32Ref;
import android.system.Os;
import android.system.OsConstants;
import java.io.FileDescriptor;

/** Real FIONREAD input/output and failure semantics through both carrier ABIs. */
public final class IoctlCarrierContract {
    public static void main(String[] args)throws Exception{
        FileDescriptor[] pipe=Os.pipe2(0);
        try{
            byte[] bytes={11,22,33,44};
            if(Os.write(pipe[1],bytes,0,bytes.length)!=4)throw new AssertionError("Pipe write differs");
            Int32Ref value=new Int32Ref(73);
            if(Os.ioctlInt(pipe[0],OsConstants.FIONREAD,value)!=0||value.value!=4)
                throw new AssertionError("Real FIONREAD did not copy output");
            if(Os.read(pipe[0],bytes,0,2)!=2)throw new AssertionError("Pipe read differs");
            value.value=91;
            if(Os.ioctlInt(pipe[0],OsConstants.FIONREAD,value)!=0||value.value!=2)
                throw new AssertionError("FIONREAD did not track kernel pending bytes");
            Class<?> legacy=Class.forName("android.util.MutableInt");
            Object previous=legacy.getConstructor(int.class).newInstance(17);
            Object result=Os.class.getMethod("ioctlInt",FileDescriptor.class,int.class,legacy).invoke(null,pipe[0],OsConstants.FIONREAD,previous);
            if((Integer)result!=0||legacy.getField("value").getInt(previous)!=2)
                throw new AssertionError("Legacy carrier ABI changed");
            value.value=123;
            try{Os.ioctlInt(new FileDescriptor(),OsConstants.FIONREAD,value);throw new AssertionError("Invalid FD accepted");}
            catch(ErrnoException expected){if(expected.errno!=OsConstants.EBADF||value.value!=123)throw new AssertionError("Invalid-FD errno/copyout changed");}
            try{Os.ioctlInt(pipe[0],-1,value);throw new AssertionError("Unsupported ioctl accepted");}
            catch(ErrnoException expected){if(expected.errno!=OsConstants.ENOTTY||value.value!=123)throw new AssertionError("Invalid-command errno/copyout changed");}
            try{Os.ioctlInt(pipe[0],OsConstants.FIONREAD,(Int32Ref)null);throw new AssertionError("Null carrier accepted");}
            catch(NullPointerException expected){}
            System.out.println("IOCTL_CARRIER_CONTRACT=PASS|kernel_pending_bytes=4,2|legacy_abi=true|errno=true|failure_copyout_unchanged=true");
        }finally{Os.close(pipe[0]);Os.close(pipe[1]);}
    }
}
