import android.net.Credentials;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.Process;
import java.lang.reflect.Method;

/** Actual platform JNI registration and kernel Unix sockets, VM diagnostic only. */
public final class NativeNetworkRegistrationContract {
    private static native int registerActual(long address);
    public static void bootstrap(boolean register,String helper) throws Exception {
        System.load(System.getProperty("saidroid.bridge.library"));
        Class<?> bridge=Class.forName("SdBridge");
        String root=System.getProperty("saidroid.native.root");
        String dirs=root+"/lib64:"+root+"/apex/com.android.runtime.debug/lib64:"
                +root+"/apex/com.android.conscrypt/lib64:"+root+"/apex/com.android.resolv/lib64";
        if(!(Boolean)bridge.getMethod("loadBionicLibrary",String.class,String.class).invoke(null,
                root+"/lib64/libandroid_runtime.so",dirs))throw new AssertionError("Native bootstrap failed");
        if((Integer)bridge.getMethod("registerFrameworkNatives").invoke(null)<1)
            throw new AssertionError("Framework JNI registration failed");
        if(register){
            System.load(helper);
            for(String symbol:new String[]{"_ZN7android36register_android_net_LocalSocketImplEP7_JNIEnv",
                    "_ZN7android33register_android_net_NetworkUtilsEP7_JNIEnv"}){
                long pointer=(Long)bridge.getMethod("lookupSymbol",String.class).invoke(null,symbol);
                if(pointer==0||registerActual(pointer)!=0)throw new AssertionError("Actual JNI registration failed: "+symbol);
                System.out.println("NETWORK_JNI_REGISTERED="+symbol);
            }
        }
    }
    public static void main(String[] args) throws Exception {
        bootstrap(Boolean.parseBoolean(args[0]),args[1]);
        String name="saidroid.vm.socket."+Process.myPid();
        LocalServerSocket listener=new LocalServerSocket(name);
        LocalSocket client=new LocalSocket();LocalSocket server=null;
        try{
            client.connect(new LocalSocketAddress(name));server=listener.accept();
            client.setSoTimeout(2000);server.setSoTimeout(2000);
            Credentials peer=client.getPeerCredentials();
            if(peer.getPid()!=Process.myPid()||peer.getUid()!=Process.myUid())throw new AssertionError("Kernel peer credentials differ");
            client.getOutputStream().write(new byte[]{11,22,33,44});
            for(int value:new int[]{11,22,33,44})if(server.getInputStream().read()!=value)throw new AssertionError("Unix socket payload differs");
            server.getOutputStream().write(73);
            if(client.getInputStream().read()!=73)throw new AssertionError("Unix socket response differs");
            client.shutdownOutput();
            if(server.getInputStream().read()!=-1)throw new AssertionError("Unix socket shutdown not delivered");
        }finally{client.close();if(server!=null)server.close();listener.close();}
        // Ask the actual netd-client API about an invalid descriptor. This
        // proves error propagation, not Android netd or host-network support.
        Method bind=Class.forName("android.net.NetworkUtils").getDeclaredMethod("bindSocketToNetwork",int.class,int.class);
        bind.setAccessible(true);int result=(Integer)bind.invoke(null,-1,0);
        if(result>=0)throw new AssertionError("Invalid socket did not return a real negative error: "+result);
        System.out.println("NATIVE_NETWORK_REGISTRATION_CONTRACT=PASS|unix_roundtrip=true|kernel_peer=true|shutdown=true|invalid_fd_error="+result);
    }
}
