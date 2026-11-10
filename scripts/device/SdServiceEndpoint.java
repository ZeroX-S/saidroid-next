import android.app.IServiceConnection;
import android.content.*;
import android.os.*;

/** Private-kernel Binder protocol to a real declared Android service process. */
public final class SdServiceEndpoint extends Binder {
    public static final String DESCRIPTOR="org.saildroid.process.Services";
    public static final int BIND=1,UNBIND=2,START=3,STOP=4,PEEK=5,TASKS=6,BROADCAST=7,START_ACTIVITY=8,MANIFEST_RECEIVER=9;
    private static SdServiceEndpoint instance;
    private SdServiceEndpoint(){attachInterface(null,DESCRIPTOR);}
    public static void publish()throws RemoteException{
        instance=new SdServiceEndpoint();String process=SdApkPackage.processName();
        SdKernelServices.registry().addService(SdKernelServices.processName(SdApkPackage.NAME,process),instance,false,0);
        System.err.println("SDSERVICE=process_endpoint|process="+process+"|pid="+android.os.Process.myPid());
    }
    @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags)throws RemoteException{
        if(code==INTERFACE_TRANSACTION){reply.writeString(DESCRIPTOR);return true;}
        if(code<BIND||code>MANIFEST_RECEIVER)return super.onTransact(code,data,reply,flags);
        if(Binder.getCallingUid()!=android.os.Process.myUid())throw new SecurityException("Service process caller UID differs");
        data.enforceInterface(DESCRIPTOR);
        if(code==START_ACTIVITY){
            Intent intent=Intent.CREATOR.createFromParcel(data);IBinder callback=data.readStrongBinder();String caller=data.readString();
            if(!SdApkPackage.NAME.equals(caller)||callback==null)throw new SecurityException("Activity caller differs");
            java.util.List<android.content.pm.ResolveInfo> choices=SdApkPackage.resolveActivities(intent,intent.getType(),0);
            if(choices.isEmpty()||!SdApkPackage.processName().equals(choices.get(0).activityInfo.processName))throw new SecurityException("Activity is not declared in this process");
            SdActivityHost.requestRemoteStart(intent,callback);reply.writeNoException();return true;
        }
        if(code==MANIFEST_RECEIVER){
            String caller=data.readString();
            if(!SdApkPackage.NAME.equals(caller))throw new SecurityException("Receiver caller package differs");
            Intent intent=Intent.CREATOR.createFromParcel(data);int result=data.readInt();String resultData=data.readString();Bundle extras=data.readBundle();String[] permissions=data.createStringArray();int user=data.readInt();
            try { SdManifestReceivers.deliverLocal(intent,result,resultData,extras,permissions,user); }
            catch (RuntimeException failure) { throw failure; }
            catch (Exception failure) { throw new IllegalStateException("Manifest receiver dispatch failed",failure); }
            reply.writeNoException();return true;
        }
        if(code==BROADCAST){
            Intent intent=Intent.CREATOR.createFromParcel(data);String type=data.readString();int result=data.readInt();String resultData=data.readString();Bundle extras=data.readBundle();String[] permissions=data.createStringArray();int user=data.readInt();
            try{SdServices.activityManager().deliverBroadcast(intent,type,result,resultData,extras,permissions,user,true);}catch(Exception failure){System.err.println("SDBROADCAST=delivery_failed|type="+failure.getClass().getName());failure.printStackTrace();}return true;
        }
        if(code==TASKS){int maximum=data.readInt();reply.writeNoException();reply.writeTypedList(SdActivityHost.runningTasks(maximum));return true;}
        if(code==UNBIND){boolean result=SdServiceHost.unbind(IServiceConnection.Stub.asInterface(data.readStrongBinder()));reply.writeNoException();reply.writeInt(result?1:0);return true;}
        Intent intent=Intent.CREATOR.createFromParcel(data);String type=data.readString();
        if(code==BIND){IServiceConnection callback=IServiceConnection.Stub.asInterface(data.readStrongBinder());int mode=data.readInt();String caller=data.readString();int user=data.readInt();int result=SdServiceHost.bind(intent,type,callback,mode,caller,user);reply.writeNoException();reply.writeInt(result);return true;}
        if(code==START){boolean foreground=data.readInt()!=0;String caller=data.readString();int user=data.readInt();ComponentName result=SdServiceHost.start(intent,type,foreground,caller,user);reply.writeNoException();reply.writeInt(result==null?0:1);if(result!=null)result.writeToParcel(reply,0);return true;}
        if(code==STOP){int result=SdServiceHost.stop(intent,type,data.readInt());reply.writeNoException();reply.writeInt(result);return true;}
        if(code==PEEK){IBinder result=SdServiceHost.peek(intent,type);reply.writeNoException();reply.writeStrongBinder(result);return true;}
        return super.onTransact(code,data,reply,flags);
    }
}
