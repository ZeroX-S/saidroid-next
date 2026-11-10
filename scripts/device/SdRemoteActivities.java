import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.os.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Declared Activity processes communicate through the private kernel Binder. */
public final class SdRemoteActivities {
    static final String CALLBACK="org.saildroid.process.ActivityResult";
    static final int READY=1,RESULT=2;
    private static final ExecutorService workers=Executors.newCachedThreadPool();
    public interface Lifecycle {
        void ready();
        void finished(int code,Intent data,boolean foreground);
        void failed(String type);
    }
    private static void post(Runnable runnable){
        Message message=Message.obtain(new Handler(Looper.getMainLooper()),runnable);
        message.setAsynchronous(true);message.sendToTarget();
    }
    private static final class Callback extends Binder {
        final Lifecycle lifecycle;
        final AtomicBoolean complete=new AtomicBoolean();
        Callback(Lifecycle lifecycle){this.lifecycle=lifecycle;attachInterface(null,CALLBACK);}
        void failed(final String type){if(complete.compareAndSet(false,true))post(new Runnable(){public void run(){lifecycle.failed(type);}});}
        @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags)throws RemoteException{
            if(code==INTERFACE_TRANSACTION){reply.writeString(CALLBACK);return true;}
            if(code!=READY&&code!=RESULT)return super.onTransact(code,data,reply,flags);
            if(Binder.getCallingUid()!=android.os.Process.myUid())throw new SecurityException("Activity result UID differs");
            data.enforceInterface(CALLBACK);
            if(code==READY){
                if(!complete.get())post(new Runnable(){public void run(){if(!complete.get())lifecycle.ready();}});
            }else{
                final int result=data.readInt();
                final Intent value=data.readInt()!=0?Intent.CREATOR.createFromParcel(data):null;
                final boolean foreground=data.readInt()!=0;
                if(complete.compareAndSet(false,true))post(new Runnable(){public void run(){lifecycle.finished(result,value,foreground);}});
            }
            return true;
        }
    }
    public static void start(final Intent intent,final ActivityInfo info,final Lifecycle lifecycle){
        if(!SdKernelServices.enabled())throw new UnsupportedOperationException("Activity processes require private Binder");
        final Callback callback=new Callback(lifecycle);
        workers.execute(new Runnable(){public void run(){try{
            String name=SdKernelServices.processName(SdApkPackage.NAME,info.processName);
            IBinder found=SdKernelServices.registry().checkService(name);
            if(found!=null&&!found.isBinderAlive())found=null;
            if(found==null){
                org.saildroid.host.HostApi.startActivityProcess(SdApkPackage.NAME,info.name,info.processName);
                long deadline=SystemClock.uptimeMillis()+30000;
                while((found=SdKernelServices.registry().checkService(name))==null){
                    if(SystemClock.uptimeMillis()>deadline)throw new IllegalStateException("Activity process startup deadline");
                    Thread.sleep(50);
                }
            }
            final IBinder endpoint=found;
            endpoint.linkToDeath(new IBinder.DeathRecipient(){public void binderDied(){callback.failed("process-ended");}},0);
            Parcel data=Parcel.obtain(),reply=Parcel.obtain();
            try{
                data.writeInterfaceToken(SdServiceEndpoint.DESCRIPTOR);
                new Intent(intent).setComponent(new android.content.ComponentName(info.packageName,info.name)).writeToParcel(data,0);
                data.writeStrongBinder(callback);data.writeString(SdApkPackage.NAME);
                if(!endpoint.transact(SdServiceEndpoint.START_ACTIVITY,data,reply,0))throw new RemoteException("Activity endpoint unavailable");
                reply.readException();
            }finally{data.recycle();reply.recycle();}
        }catch(Exception failure){
            System.err.println("SDREMOTE_ACTIVITY=start_failed|class="+info.name+"|type="+failure.getClass().getName());
            failure.printStackTrace();callback.failed(failure.getClass().getName());
        }}});
    }
    static void ready(IBinder callback)throws RemoteException{
        Parcel data=Parcel.obtain();try{
            data.writeInterfaceToken(CALLBACK);
            if(!callback.transact(READY,data,null,IBinder.FLAG_ONEWAY))throw new RemoteException("Activity caller ended");
        }catch(DeadObjectException ended){
            // A caller can launch its successor and finish its own process
            // before the successor's asynchronous launch verification runs.
            System.err.println("SDREMOTE_ACTIVITY=ready_caller_ended|activity_retained=true");
        }finally{data.recycle();}
    }
    static void finish(IBinder callback,int code,Intent value,boolean foreground)throws RemoteException{
        Parcel data=Parcel.obtain();try{
            data.writeInterfaceToken(CALLBACK);data.writeInt(code);data.writeInt(value==null?0:1);if(value!=null)value.writeToParcel(data,0);data.writeInt(foreground?1:0);
            if(!callback.transact(RESULT,data,null,IBinder.FLAG_ONEWAY))throw new RemoteException("Activity caller ended");
        }finally{data.recycle();}
    }
}
