import android.os.*;
import com.android.internal.os.BinderInternal;
import java.io.*;
import java.util.*;

/** Bounded real-kernel two-process probe; no host servicemanager is accessed. */
public final class KernelBinderProbe {
    private static final String ECHO="org.saildroid.probe.echo";
    private static int serverPid;
    private static volatile int callbackPid;
    private static final class Registry extends ServiceManagerNative {
        final HashMap<String,IBinder> entries=new HashMap<String,IBinder>();
        public IBinder getService(String name){return entries.get(name);}
        public IBinder checkService(String name){return getService(name);}
        public void addService(String name,IBinder value,boolean isolated,int priority){if(!name.startsWith("saidroid.probe."))throw new SecurityException(name);entries.put(name,value);}
        public String[] listServices(int flags){return entries.keySet().toArray(new String[0]);}
        public void setPermissionController(IPermissionController controller){throw new UnsupportedOperationException();}
    }
    public static void main(String[] args)throws Exception{
        System.load(args[0]);if(!SdBridge.loadBionicLibrary(args[1]+"/libandroid_runtime.so",args[1]))throw new AssertionError("Android runtime unavailable");
        if(!SdBridge.configurePrivateBinder("/home/art/runtime/binder/binder"))throw new AssertionError("Private driver unavailable");
        if(SdBridge.registerFrameworkNatives()<1)throw new AssertionError("Native registration failed");
        Looper.prepareMainLooper();serverPid=android.os.Process.myPid();
        new Thread(new Runnable(){public void run(){try{Thread.sleep(25000);}catch(Exception ignored){}Runtime.getRuntime().halt(91);}},"probe-deadline").start();
        if(args[2].equals("server")){
            Registry registry=new Registry();
            registry.addService("saidroid.probe.echo",new Binder(){protected boolean onTransact(int code,Parcel data,Parcel reply,int flags)throws RemoteException{
                if(code==1){data.enforceInterface(ECHO);int number=data.readInt();IBinder callback=data.readStrongBinder();int caller=Binder.getCallingPid();Parcel request=Parcel.obtain(),response=Parcel.obtain();try{request.writeInterfaceToken(ECHO);request.writeInt(number+1);callback.transact(1,request,response,0);response.readException();if(response.readInt()!=number+2)throw new AssertionError("Callback reply differs");}finally{request.recycle();response.recycle();}reply.writeNoException();reply.writeInt(number*2);reply.writeInt(caller);reply.writeInt(Binder.getCallingUid());reply.writeInt(serverPid);return true;}
                return super.onTransact(code,data,reply,flags);
            }},false,0);
            if(!SdBridge.becomeBinderContextManager(registry.asBinder()))throw new AssertionError("Context claim failed");
            SdBridge.startBinderPool();
            try(FileWriter file=new FileWriter(args[3])){file.write(Integer.toString(serverPid));}
            System.err.println("KERNEL_BINDER_SERVER=ready|pid="+serverPid);Looper.loop();
        }else{
            SdBridge.startBinderPool();IServiceManager registry=ServiceManagerNative.asInterface(BinderInternal.getContextObject());
            IBinder echo=registry.checkService("saidroid.probe.echo");if(echo==null)throw new AssertionError("No remote service");
            Binder callback=new Binder(){protected boolean onTransact(int code,Parcel data,Parcel reply,int flags){data.enforceInterface(ECHO);int number=data.readInt();callbackPid=Binder.getCallingPid();reply.writeNoException();reply.writeInt(number+1);return true;}};
            Parcel request=Parcel.obtain(),response=Parcel.obtain();request.writeInterfaceToken(ECHO);request.writeInt(21);request.writeStrongBinder(callback);
            if(!echo.transact(1,request,response,0))throw new AssertionError("Remote call rejected");response.readException();int value=response.readInt(),caller=response.readInt(),uid=response.readInt(),remote=response.readInt();request.recycle();response.recycle();
            if(value!=42||caller!=android.os.Process.myPid()||uid!=android.os.Process.myUid()||remote==caller||callbackPid!=remote)throw new AssertionError("Binder identity/callback mismatch");
            System.err.println("KERNEL_BINDER_CLIENT=PASS|value="+value+"|client_pid="+caller+"|server_pid="+remote+"|callback_pid="+callbackPid+"|uid="+uid);System.exit(0);
        }
    }
}
