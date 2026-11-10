import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.os.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Declared Activity processes communicate through the private kernel Binder. */
public final class SdRemoteActivities {
    static final String CALLBACK="org.saildroid.process.ActivityResult";
    static final int READY=1,RESULT=2,CALLING_ACTIVITY=3;
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
        final android.content.ComponentName callingActivity;
        final AtomicBoolean complete=new AtomicBoolean();
        Callback(Lifecycle lifecycle,android.content.ComponentName callingActivity){this.lifecycle=lifecycle;this.callingActivity=callingActivity;attachInterface(null,CALLBACK);}
        void failed(final String type){if(complete.compareAndSet(false,true))post(new Runnable(){public void run(){lifecycle.failed(type);}});}
        @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags)throws RemoteException{
            if(code==INTERFACE_TRANSACTION){reply.writeString(CALLBACK);return true;}
            if(code!=READY&&code!=RESULT&&code!=CALLING_ACTIVITY)return super.onTransact(code,data,reply,flags);
            if(Binder.getCallingUid()!=android.os.Process.myUid())throw new SecurityException("Activity result UID differs");
            data.enforceInterface(CALLBACK);
            if(code==CALLING_ACTIVITY){
                android.content.ComponentName caller=complete.get()?null:callingActivity;
                reply.writeNoException();reply.writeInt(caller==null?0:1);if(caller!=null)caller.writeToParcel(reply,0);return true;
            }
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
    public static void start(final Intent intent,final ActivityInfo info,final Lifecycle lifecycle){start(intent,info,null,lifecycle);}
    public static void start(final Intent intent,final ActivityInfo info,final android.content.ComponentName callingActivity,final Lifecycle lifecycle){
        if(!SdKernelServices.enabled())throw new UnsupportedOperationException("Activity processes require private Binder");
        final Callback callback=new Callback(lifecycle,callingActivity);
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
    static android.content.ComponentName callingActivity(IBinder callback)throws RemoteException{
        Parcel data=Parcel.obtain(),reply=Parcel.obtain();try{
            data.writeInterfaceToken(CALLBACK);
            if(!callback.transact(CALLING_ACTIVITY,data,reply,0))throw new RemoteException("Activity caller metadata endpoint unavailable");
            reply.readException();return reply.readInt()!=0?android.content.ComponentName.CREATOR.createFromParcel(reply):null;
        }finally{data.recycle();reply.recycle();}
    }
    static void ready(IBinder callback)throws RemoteException{
        Parcel data=Parcel.obtain();try{data.writeInterfaceToken(CALLBACK);if(!callback.transact(READY,data,null,IBinder.FLAG_ONEWAY))throw new RemoteException("Activity caller ended");}finally{data.recycle();}
    }
    static void finish(IBinder callback,int code,Intent value,boolean foreground)throws RemoteException{
        Parcel data=Parcel.obtain();try{
            data.writeInterfaceToken(CALLBACK);data.writeInt(code);data.writeInt(value==null?0:1);if(value!=null)value.writeToParcel(data,0);data.writeInt(foreground?1:0);
            if(!callback.transact(RESULT,data,null,IBinder.FLAG_ONEWAY))throw new RemoteException("Activity caller ended");
        }finally{data.recycle();}
    }
}
