import android.os.*;
import java.util.*;
import java.io.*;

/** Session-owned context manager on the dedicated private Binder device. */
public final class SdBinderRegistry extends ServiceManagerNative {
    private final HashMap<String,IBinder> entries=new HashMap<String,IBinder>();
    private final HashMap<Integer,IBinder> processes=new HashMap<Integer,IBinder>();
    public SdBinderRegistry(){entries.put("sensorservice",new SdSensorService(this));}
    synchronized IBinder endpointForPid(int pid){return processes.get(pid);}
    @Override public boolean onTransact(int code,Parcel data,Parcel reply,int flags){
        // API29's Java proxy uses the native servicemanager's indexed protocol;
        // ServiceManagerNative's array reply does not match its own proxy.
        if(code==IServiceManager.LIST_SERVICES_TRANSACTION){
            data.enforceInterface("android.os.IServiceManager");int index=data.readInt();String[] names=listServices(data.readInt());
            if(index<0||index>=names.length)return false;
            reply.writeString(names[index]);return true;
        }
        return super.onTransact(code,data,reply,flags);
    }
    private static boolean privateName(String name){return name!=null&&(name.startsWith("saidroid.process.")||name.startsWith("saidroid.provider.")||name.startsWith("saidroid.sip."));}
    private void check(String name){if(Binder.getCallingUid()!=android.os.Process.myUid()||!privateName(name))throw new SecurityException("Private service identity differs");}
    @Override public synchronized IBinder getService(String name){if(Binder.getCallingUid()!=android.os.Process.myUid())throw new SecurityException("Private service UID differs");return privateName(name)||"sensorservice".equals(name)?entries.get(name):null;}
    @Override public IBinder checkService(String name){return getService(name);}
    @Override public synchronized void addService(final String name,final IBinder binder,boolean isolated,int priority)throws RemoteException{
        check(name);if(binder==null)throw new NullPointerException("Service Binder required");IBinder old=entries.get(name);if(old!=null&&old.isBinderAlive()&&old!=binder)throw new IllegalStateException("Private process endpoint already registered");
        final int pid=Binder.getCallingPid();
        binder.linkToDeath(new IBinder.DeathRecipient(){public void binderDied(){synchronized(SdBinderRegistry.this){if(entries.get(name)==binder)entries.remove(name);if(processes.get(pid)==binder)processes.remove(pid);}}},0);entries.put(name,binder);if(name.startsWith("saidroid.process."))processes.put(pid,binder);
        System.err.println("SDBINDER=endpoint_registered|name="+name+"|pid="+Binder.getCallingPid());
    }
    @Override public synchronized String[] listServices(int flags){if(Binder.getCallingUid()!=android.os.Process.myUid())throw new SecurityException();return entries.keySet().toArray(new String[0]);}
    @Override public void setPermissionController(IPermissionController controller){throw new UnsupportedOperationException("Private registry owns no system permission controller");}
    public static void main(String[] args){try{
        SdRuntime.initializeFramework(false);Looper.prepareMainLooper();android.os.Process.setArgV0("org.saildroid.binder");
        SdBinderRegistry registry=new SdBinderRegistry();if(!SdBridge.becomeBinderContextManager(registry))throw new IllegalStateException("Private context claim failed");
        SdBridge.startBinderPool();SdRuntimeControl.start();
        String path=System.getenv("SAILDROID_READY_FILE");if(path==null)throw new IllegalStateException("Broker readiness path unavailable");
        try(FileWriter output=new FileWriter(path)){output.write(Integer.toString(android.os.Process.myPid()));}
        org.saildroid.host.HostApi.ready();System.err.println("SDBINDER=registry_ready|pid="+android.os.Process.myPid());Looper.loop();
    }catch(Throwable failure){failure.printStackTrace();System.err.println("SDBINDER=registry_failed");Runtime.getRuntime().halt(12);}}
}
