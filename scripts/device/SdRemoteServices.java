import android.app.IServiceConnection;
import android.content.*;
import android.content.pm.*;
import android.os.*;
import java.util.*;
import java.util.concurrent.*;

/** Starts declared secondary processes and binds through real kernel Binder. */
public final class SdRemoteServices {
    private static final Object lock=new Object();
    private static final HashMap<String,IBinder> endpoints=new HashMap<String,IBinder>();
    private static final HashMap<String,Object> starters=new HashMap<String,Object>();
    private static final IdentityHashMap<IBinder,ArrayList<Connection>> connections=new IdentityHashMap<IBinder,ArrayList<Connection>>();
    private static final ExecutorService workers=Executors.newCachedThreadPool();
    private static final class Connection {final IServiceConnection callback;final ServiceInfo info;volatile boolean active=true;IBinder endpoint;Connection(IServiceConnection callback,ServiceInfo info){this.callback=callback;this.info=info;}}
    private static void check(String caller,int user){if(!SdApkPackage.NAME.equals(caller)||user!=android.os.Process.myUid()/100000)throw new SecurityException("Remote Service caller differs");}
    private static ServiceInfo resolve(Intent intent,String type){List<ResolveInfo> result=SdApkPackage.resolveServices(intent,type,0);return result.isEmpty()?null:result.get(0).serviceInfo;}
    public static boolean isRemote(Intent intent,String type){ServiceInfo info=resolve(intent,type);return info!=null&&info.processName!=null&&!info.processName.equals(SdApkPackage.processName());}
    private static IBinder cached(ServiceInfo info)throws RemoteException{
        synchronized(lock){IBinder current=endpoints.get(info.processName);if(current!=null&&current.isBinderAlive())return current;}
        IBinder endpoint=SdKernelServices.registry().checkService(SdKernelServices.processName(SdApkPackage.NAME,info.processName));
        if(endpoint!=null){synchronized(lock){endpoints.put(info.processName,endpoint);}return endpoint;}return null;
    }
    private static IBinder ensure(ServiceInfo info)throws Exception{
        Object gate;synchronized(lock){gate=starters.get(info.processName);if(gate==null){gate=new Object();starters.put(info.processName,gate);}}
        synchronized(gate){
            IBinder endpoint=cached(info);if(endpoint!=null)return endpoint;
            org.saildroid.host.HostApi.startService(SdApkPackage.NAME,info.name,info.processName);
            endpoint=SdProcessStartup.awaitEndpoint(SdKernelServices.processName(SdApkPackage.NAME,info.processName),"Service process did not publish its endpoint: "+info.processName);
            synchronized(lock){endpoints.put(info.processName,endpoint);}
            final String process=info.processName;final IBinder bound=endpoint;
            endpoint.linkToDeath(new IBinder.DeathRecipient(){public void binderDied(){ArrayList<Connection> targets=new ArrayList<Connection>();synchronized(lock){if(endpoints.get(process)==bound)endpoints.remove(process);for(ArrayList<Connection> list:connections.values())for(Connection connection:list)if(connection.active&&connection.endpoint==bound)targets.add(connection);}for(Connection connection:targets)try{connection.callback.connected(new ComponentName(connection.info.packageName,connection.info.name),null,true);}catch(RemoteException ignored){}}},0);
            System.err.println("SDSERVICE=remote_process_ready|process="+info.processName);return endpoint;
        }
    }
    private interface Writer {void write(Parcel data);}
    private static Parcel transact(IBinder endpoint,int code,Writer writer)throws RemoteException{
        Parcel data=Parcel.obtain(),reply=Parcel.obtain();data.writeInterfaceToken(SdServiceEndpoint.DESCRIPTOR);writer.write(data);
        try{if(!endpoint.transact(code,data,reply,0))throw new RemoteException("Private Service endpoint rejected transaction");reply.readException();return reply;}catch(Throwable failure){reply.recycle();if(failure instanceof RemoteException)throw(RemoteException)failure;throw new IllegalStateException(failure);}finally{data.recycle();}
    }
    private static void intent(Parcel data,Intent intent,String type){intent.writeToParcel(data,0);data.writeString(type);}
    public static int bind(final Intent intent,final String type,final IServiceConnection callback,final int flags,final String caller,final int user){
        check(caller,user);final ServiceInfo info=resolve(intent,type);if(info==null||!SdKernelServices.enabled())return 0;
        if((flags&Context.BIND_AUTO_CREATE)==0)try{if(cached(info)==null)return 0;}catch(RemoteException failure){return 0;}
        final Connection connection=new Connection(callback,info);synchronized(lock){ArrayList<Connection> list=connections.get(callback.asBinder());if(list==null){list=new ArrayList<Connection>();connections.put(callback.asBinder(),list);}list.add(connection);}
        workers.execute(new Runnable(){public void run(){try{
            IBinder endpoint=ensure(info);
            synchronized(connection){if(!connection.active)return;connection.endpoint=endpoint;Parcel reply=transact(endpoint,SdServiceEndpoint.BIND,new Writer(){public void write(Parcel data){intent(data,intent,type);data.writeStrongBinder(callback.asBinder());data.writeInt(flags);data.writeString(caller);data.writeInt(user);}});try{if(reply.readInt()!=1)throw new IllegalStateException("Remote service bind was rejected");}finally{reply.recycle();}}
        }catch(Exception failure){if(failure instanceof InterruptedException)Thread.currentThread().interrupt();System.err.println("SDSERVICE=remote_bind_failed|class="+info.name+"|type="+failure.getClass().getName());failure.printStackTrace();if(connection.active)try{callback.connected(new ComponentName(info.packageName,info.name),null,true);}catch(RemoteException ignored){}}}});return 1;
    }
    public static boolean unbind(final IServiceConnection callback){
        final ArrayList<Connection> group;synchronized(lock){group=connections.remove(callback.asBinder());if(group==null)return false;for(Connection connection:group)connection.active=false;}
        workers.execute(new Runnable(){public void run(){HashSet<IBinder> sent=new HashSet<IBinder>();for(Connection connection:group)synchronized(connection){if(connection.endpoint==null||!sent.add(connection.endpoint))continue;try{Parcel reply=transact(connection.endpoint,SdServiceEndpoint.UNBIND,new Writer(){public void write(Parcel data){data.writeStrongBinder(callback.asBinder());}});reply.recycle();}catch(RemoteException failure){System.err.println("SDSERVICE=remote_unbind_dead");}}}});return true;
    }
    public static ComponentName start(final Intent intent,final String type,final boolean foreground,final String caller,final int user){
        check(caller,user);final ServiceInfo info=resolve(intent,type);if(info==null||!SdKernelServices.enabled())return null;
        workers.execute(new Runnable(){public void run(){try{Parcel reply=transact(ensure(info),SdServiceEndpoint.START,new Writer(){public void write(Parcel data){intent(data,intent,type);data.writeInt(foreground?1:0);data.writeString(caller);data.writeInt(user);}});try{if(reply.readInt()==0)throw new IllegalStateException("Remote start rejected");}finally{reply.recycle();}}catch(Exception failure){if(failure instanceof InterruptedException)Thread.currentThread().interrupt();System.err.println("SDSERVICE=remote_start_failed|class="+info.name);failure.printStackTrace();}}});return new ComponentName(info.packageName,info.name);
    }
    public static int stop(final Intent intent,final String type,final int user)throws RemoteException{
        check(SdApkPackage.NAME,user);ServiceInfo info=resolve(intent,type);if(info==null||!SdKernelServices.enabled())return 0;IBinder endpoint=cached(info);if(endpoint==null)return 0;
        Parcel reply=transact(endpoint,SdServiceEndpoint.STOP,new Writer(){public void write(Parcel data){intent(data,intent,type);data.writeInt(user);}});try{return reply.readInt();}finally{reply.recycle();}
    }
    public static IBinder peek(final Intent intent,final String type)throws RemoteException{
        ServiceInfo info=resolve(intent,type);if(info==null||!SdKernelServices.enabled())return null;IBinder endpoint=cached(info);if(endpoint==null)return null;
        Parcel reply=transact(endpoint,SdServiceEndpoint.PEEK,new Writer(){public void write(Parcel data){intent(data,intent,type);}});try{return reply.readStrongBinder();}finally{reply.recycle();}
    }
    public static List<android.app.ActivityManager.RunningTaskInfo> tasks(final int maximum)throws RemoteException{
        if(!SdKernelServices.enabled()||maximum<=0)return new ArrayList<android.app.ActivityManager.RunningTaskInfo>();
        String process=SdApkPackage.applicationInfo().processName;
        IBinder endpoint=SdKernelServices.registry().checkService(SdKernelServices.processName(SdApkPackage.NAME,process));
        if(endpoint==null)return new ArrayList<android.app.ActivityManager.RunningTaskInfo>();
        Parcel reply=transact(endpoint,SdServiceEndpoint.TASKS,new Writer(){public void write(Parcel data){data.writeInt(maximum);}});
        try{return reply.createTypedArrayList(android.app.ActivityManager.RunningTaskInfo.CREATOR);}finally{reply.recycle();}
    }
    public static void broadcast(Intent intent,String type,int result,String resultData,Bundle extras,String[] permissions,int user)throws RemoteException{
        check(SdApkPackage.NAME,user);
        String prefix="saidroid.process."+SdApkPackage.NAME+'.';String self=SdKernelServices.processName(SdApkPackage.NAME,SdApkPackage.processName());
        for(String name:SdKernelServices.registry().listServices(15)){
            if(!name.startsWith(prefix)||name.equals(self))continue;
            IBinder endpoint=SdKernelServices.registry().checkService(name);if(endpoint==null)continue;
            Parcel data=Parcel.obtain();try{
                data.writeInterfaceToken(SdServiceEndpoint.DESCRIPTOR);intent.writeToParcel(data,0);data.writeString(type);data.writeInt(result);data.writeString(resultData);data.writeBundle(extras);data.writeStringArray(permissions);data.writeInt(user);
                if(!endpoint.transact(SdServiceEndpoint.BROADCAST,data,null,IBinder.FLAG_ONEWAY))throw new RemoteException("Remote broadcast endpoint unavailable");
            }catch(DeadObjectException exited){/* Endpoint death cleanup removes this process from the registry. */}finally{data.recycle();}
        }
    }
}
