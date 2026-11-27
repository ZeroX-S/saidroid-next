import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import java.io.FileDescriptor;

/** Observe actual kernel descriptor flags and nonblocking socket behavior. */
public final class SocketFlagsContract {
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void flags(FileDescriptor fd,boolean cloexec,boolean nonblock)throws Exception{
        int descriptor=Os.fcntlInt(fd,OsConstants.F_GETFD,0);
        int status=Os.fcntlInt(fd,OsConstants.F_GETFL,0);
        require(((descriptor&OsConstants.FD_CLOEXEC)!=0)==cloexec,"Kernel close-on-exec flag");
        require(((status&OsConstants.O_NONBLOCK)!=0)==nonblock,"Kernel nonblocking flag");
    }
    public static void main(String[] args)throws Exception{
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(29);
        require(OsConstants.SOCK_CLOEXEC==OsConstants.O_CLOEXEC&&OsConstants.SOCK_CLOEXEC!=0,"Runtime close-on-exec value socket="+OsConstants.SOCK_CLOEXEC+" open="+OsConstants.O_CLOEXEC);
        require(OsConstants.SOCK_NONBLOCK==OsConstants.O_NONBLOCK&&OsConstants.SOCK_NONBLOCK!=0,"Runtime nonblocking value socket="+OsConstants.SOCK_NONBLOCK+" open="+OsConstants.O_NONBLOCK);
        for(int mask=0;mask<4;mask++){
            int type=OsConstants.SOCK_STREAM|(mask%2!=0?OsConstants.SOCK_CLOEXEC:0)|(mask>=2?OsConstants.SOCK_NONBLOCK:0);
            FileDescriptor first=new FileDescriptor(),second=new FileDescriptor();
            Os.socketpair(OsConstants.AF_UNIX,type,0,first,second);
            try{
                flags(first,mask%2!=0,mask>=2);flags(second,mask%2!=0,mask>=2);
                if(mask>=2){
                    try{Os.read(first,new byte[1],0,1);throw new AssertionError("Empty nonblocking socket did not return EAGAIN");}
                    catch(ErrnoException expected){require(expected.errno==OsConstants.EAGAIN,"Real nonblocking errno");}
                }
                byte[] message={1,23,45};require(Os.write(first,message,0,3)==3,"Real socket write");
                byte[] actual=new byte[3];require(Os.read(second,actual,0,3)==3&&java.util.Arrays.equals(message,actual),"Real socket bytes");
            }finally{Os.close(first);Os.close(second);}
        }
        FileDescriptor single=Os.socket(OsConstants.AF_UNIX,OsConstants.SOCK_STREAM|OsConstants.SOCK_CLOEXEC|OsConstants.SOCK_NONBLOCK,0);
        try{flags(single,true,true);}finally{Os.close(single);}
        System.out.println("SOCKET_FLAGS_CONTRACT=PASS|native_runtime_values=true|kernel_fcntl=true|nonblocking_errno=true|real_bytes=true|combinations=4");
    }
}
