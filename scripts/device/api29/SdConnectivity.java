import android.Manifest;
import android.content.pm.PackageManager;
import android.net.*;
import android.os.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;

/** Passive host network observations. No bearer creation, network binding or bound DNS. */
public final class SdConnectivity implements InvocationHandler {
    interface Provider { SdConnectivitySnapshot read()throws IOException; }
    interface Permissions { void checkAccess()throws RemoteException; }
    private static final SdConnectivity INSTANCE=new SdConnectivity(new SdConnectivityHostProvider(),new Permissions(){
        public void checkAccess()throws RemoteException{
            if(SdPackageManagerService.service().checkPermission(Manifest.permission.ACCESS_NETWORK_STATE,SdApkPackage.NAME,android.os.Process.myUid()/100000)!=PackageManager.PERMISSION_GRANTED)
                throw new SecurityException("ACCESS_NETWORK_STATE is not declared by this application");
        }
    });
    private final Binder binder=new Binder();
    private final IConnectivityManager service;
    private final Provider provider;private final Permissions permissions;
    private final Object state=new Object(),providerLock=new Object();
    private final Map<Integer,Registration> registrations=new LinkedHashMap<Integer,Registration>();
    private ScheduledThreadPoolExecutor worker;
    private ScheduledFuture<?> nextPoll;
    private SdConnectivitySnapshot latest;private long latestNanos;
    private int nextRequest=1;private long polls,providerFailures,events;
    private boolean loggedDefault,loggedListen;
    private boolean closed;
    private static final int MAX_REGISTRATIONS=99;
    private static final long POLL_MS=1000;

    SdConnectivity(Provider provider,Permissions permissions){
        this.provider=provider;this.permissions=permissions;
        service=(IConnectivityManager)java.lang.reflect.Proxy.newProxyInstance(IConnectivityManager.class.getClassLoader(),new Class<?>[]{IConnectivityManager.class},this);
        binder.attachInterface(service,"android.net.IConnectivityManager");
    }
    public static IBinder binder(){return INSTANCE.binder;}
    IConnectivityManager serviceForFixture(){return service;}

    private final class Registration implements IBinder.DeathRecipient {
        final NetworkRequest request;final Messenger messenger;final IBinder token;
        Map<Integer,SdConnectivitySnapshot.Link> matched=new LinkedHashMap<Integer,SdConnectivitySnapshot.Link>();
        boolean linked;
        Registration(NetworkRequest request,Messenger messenger,IBinder token){this.request=request;this.messenger=messenger;this.token=token;}
        public void binderDied(){remove(this);}
    }
    private static final class Delivery {
        final Registration registration;final int type;final SdConnectivitySnapshot.Link link;
        Delivery(Registration r,int type,SdConnectivitySnapshot.Link link){registration=r;this.type=type;this.link=link;}
    }
    private static void validateListen(NetworkCapabilities caps){
        if(caps==null)throw new NullPointerException("NetworkCapabilities missing");
        if(caps.getNetworkSpecifier()!=null)throw new UnsupportedOperationException("Host connectivity does not implement network specifiers");
        Set<UidRange>uids=caps.getUids();if(uids!=null)for(UidRange range:uids)if(range.start!=android.os.Process.myUid()||range.stop!=android.os.Process.myUid())
            throw new SecurityException("Cross-UID network observations unavailable");
    }
    private NetworkRequest register(NetworkCapabilities caps,Messenger messenger,IBinder token,boolean track)throws RemoteException{
        permissions.checkAccess();if(messenger==null||token==null)throw new NullPointerException("Network callback transport missing");
        if(!track)validateListen(caps);
        NetworkCapabilities copy=track?new NetworkCapabilities():new NetworkCapabilities(caps);
        // Every subscription belongs to this process's real host UID. No arbitrary UID ranges.
        copy.setSingleUid(android.os.Process.myUid());
        synchronized(state){
            if(closed)throw new IllegalStateException("Host connectivity closed");
            if(registrations.size()>=MAX_REGISTRATIONS)throw new ServiceSpecificException(ConnectivityManager.Errors.TOO_MANY_REQUESTS);
            if(nextRequest==Integer.MAX_VALUE)throw new IllegalStateException("Network request identity exhausted");
            NetworkRequest request=new NetworkRequest(copy,ConnectivityManager.TYPE_NONE,nextRequest++,track?NetworkRequest.Type.TRACK_DEFAULT:NetworkRequest.Type.LISTEN);
            Registration r=new Registration(request,messenger,token);registrations.put(request.requestId,r);
            try{token.linkToDeath(r,0);r.linked=true;}
            catch(RemoteException failure){registrations.remove(request.requestId);throw failure;}
            if(!registrations.containsKey(request.requestId))throw new RemoteException("Network callback token died during registration");
            if(worker==null){worker=new ScheduledThreadPoolExecutor(1,new ThreadFactory(){public Thread newThread(Runnable task){Thread t=new Thread(task,"saildroid-connectivity");t.setDaemon(true);return t;}});worker.setRemoveOnCancelPolicy(true);}
            if(track?!loggedDefault:!loggedListen){
                if(track)loggedDefault=true;else loggedListen=true;
                System.err.println("SDCONNECTIVITY=subscription|mode="+(track?"track-default":"listen")+"|request="+request.requestId+"|passive=true");
                StackTraceElement[]stack=new Throwable().getStackTrace();int emitted=0;
                for(StackTraceElement frame:stack)if(!frame.getClassName().startsWith("SdConnectivity")&&emitted++<8)System.err.println("SDCONNECTIVITY_CALLER="+frame.toString());
            }
            scheduleLocked(0);
            return new NetworkRequest(request);
        }
    }
    private void scheduleLocked(long delay){
        if(worker==null||registrations.isEmpty()||closed)return;
        // Registration can advance a pending one-second sample to immediate delivery.
        if(nextPoll!=null){if(delay!=0)return;nextPoll.cancel(false);}
        final ScheduledThreadPoolExecutor owner=worker;
        nextPoll=owner.schedule(new Runnable(){public void run(){tick(owner);}},delay,TimeUnit.MILLISECONDS);
    }
    private void remove(Registration r){
        synchronized(state){
            if(registrations.get(r.request.requestId)!=r)return;
            registrations.remove(r.request.requestId);r.matched.clear();
            if(r.linked){r.linked=false;try{r.token.unlinkToDeath(r,0);}catch(NoSuchElementException ignored){}}
            if(registrations.isEmpty()&&worker!=null){
                if(nextPoll!=null){nextPoll.cancel(false);nextPoll=null;}
                worker.shutdown();worker=null;
            }
        }
    }
    private void release(NetworkRequest request){
        if(request==null)throw new NullPointerException("NetworkRequest missing");
        Registration r;synchronized(state){r=registrations.get(request.requestId);if(r!=null&&!r.request.equals(request))throw new SecurityException("Network request identity mismatch");}
        if(r!=null)remove(r);
    }
    private SdConnectivitySnapshot refresh(boolean useCache)throws IOException{
        synchronized(providerLock){
            synchronized(state){if(useCache&&latest!=null&&System.nanoTime()-latestNanos<POLL_MS*1000000L)return latest;polls++;}
            SdConnectivitySnapshot observed;
            try{observed=provider.read();if(observed==null)throw new IOException("Host network snapshot absent");}
            catch(IOException e){synchronized(state){providerFailures++;}throw e;}
            synchronized(state){latest=observed;latestNanos=System.nanoTime();}return observed;
        }
    }
    private SdConnectivitySnapshot snapshot(){
        try{return refresh(true);}catch(IOException failure){
            synchronized(state){if(latest!=null)return latest;}
            throw new IllegalStateException("Host connectivity snapshot unavailable",failure);
        }
    }
    private void tick(ScheduledThreadPoolExecutor owner){
        synchronized(state){if(worker!=owner||registrations.isEmpty()||closed)return;nextPoll=null;}
        try{
            // Never synthesize a loss from a provider failure or partial observation.
            SdConnectivitySnapshot observed=refresh(true);List<Delivery>deliveries=new ArrayList<Delivery>();
            synchronized(state){
                if(worker!=owner||closed)return;
                for(Registration r:registrations.values()){
                    Map<Integer,SdConnectivitySnapshot.Link>matched=new LinkedHashMap<Integer,SdConnectivitySnapshot.Link>();
                    boolean track=r.request.type==NetworkRequest.Type.TRACK_DEFAULT;
                    if(track){SdConnectivitySnapshot.Link active=observed.activeLink();if(active!=null)matched.put(active.id,active);}
                    else for(SdConnectivitySnapshot.Link link:observed.links.values())if(r.request.networkCapabilities.satisfiedByNetworkCapabilities(link.capabilities))matched.put(link.id,link);
                    for(SdConnectivitySnapshot.Link old:r.matched.values())if(!matched.containsKey(old.id)&&(!track||matched.isEmpty()))deliveries.add(new Delivery(r,ConnectivityManager.CALLBACK_LOST,old));
                    for(SdConnectivitySnapshot.Link link:matched.values()){
                        SdConnectivitySnapshot.Link old=r.matched.get(link.id);
                        if(old==null)deliveries.add(new Delivery(r,ConnectivityManager.CALLBACK_AVAILABLE,link));
                        else{
                            boolean wasLive=old.capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED),isLive=link.capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED);
                            if(wasLive!=isLive)deliveries.add(new Delivery(r,isLive?ConnectivityManager.CALLBACK_RESUMED:ConnectivityManager.CALLBACK_SUSPENDED,link));
                            if(!old.capabilities.equals(link.capabilities))deliveries.add(new Delivery(r,ConnectivityManager.CALLBACK_CAP_CHANGED,link));
                            if(!old.properties.equals(link.properties))deliveries.add(new Delivery(r,ConnectivityManager.CALLBACK_IP_CHANGED,link));
                        }
                    }
                    r.matched=matched;
                }
            }
            for(Delivery delivery:deliveries)send(delivery);
        }catch(IOException ignored){/* bounded observation failure; preserve last known state */}
        finally{synchronized(state){if(worker==owner&&!closed)scheduleLocked(POLL_MS);}}
    }
    private void send(Delivery delivery){
        Registration r=delivery.registration;
        synchronized(state){if(registrations.get(r.request.requestId)!=r)return;}
        Bundle bundle=new Bundle();bundle.putParcelable("NetworkRequest",new NetworkRequest(r.request));bundle.putParcelable("Network",new Network(delivery.link.network));
        if(delivery.type==ConnectivityManager.CALLBACK_AVAILABLE||delivery.type==ConnectivityManager.CALLBACK_CAP_CHANGED)bundle.putParcelable("NetworkCapabilities",new NetworkCapabilities(delivery.link.capabilities));
        if(delivery.type==ConnectivityManager.CALLBACK_AVAILABLE||delivery.type==ConnectivityManager.CALLBACK_IP_CHANGED)bundle.putParcelable("LinkProperties",new LinkProperties(delivery.link.properties));
        Message message=Message.obtain();message.what=delivery.type;message.arg1=0;message.setData(bundle);
        try{r.messenger.send(message);synchronized(state){events++;}}
        catch(RemoteException dead){remove(r);}
    }
    void closeForFixture(){
        List<Registration>all;synchronized(state){closed=true;all=new ArrayList<Registration>(registrations.values());}
        for(Registration r:all)remove(r);
    }
    long[] countersForFixture(){synchronized(state){return new long[]{registrations.size(),polls,providerFailures,events,worker==null?0:worker.getQueue().size()};}}
    void refreshForFixture()throws IOException{refresh(false);synchronized(state){scheduleLocked(0);}}

    @Override public Object invoke(Object proxy,Method method,Object[]args)throws Throwable{
        String name=method.getName();if(name.equals("asBinder"))return binder;if(name.equals("toString"))return "SailDroid passive host connectivity";if(name.equals("hashCode"))return System.identityHashCode(proxy);if(name.equals("equals"))return proxy==args[0];
        if(name.equals("requestNetwork")){
            if(args[0]!=null)throw SdRuntimeDiagnostics.unsupported("Host active network request",method);
            if((Integer)args[2]!=0||(Integer)args[4]!=ConnectivityManager.TYPE_NONE)throw new UnsupportedOperationException("Host default observation does not implement timeout/legacy requests");
            return register(null,(Messenger)args[1],(IBinder)args[3],true);
        }
        if(name.equals("listenForNetwork"))return register((NetworkCapabilities)args[0],(Messenger)args[1],(IBinder)args[2],false);
        if(name.equals("releaseNetworkRequest")){release((NetworkRequest)args[0]);return null;}
        // Android configures the process proxy during ActivityThread binding, even
        // for applications that do not declare ACCESS_NETWORK_STATE. These proxy
        // queries expose no network state and must precede the observation gate.
        if(name.equals("getGlobalProxy")||name.equals("getProxyForNetwork"))return null;
        permissions.checkAccess();
        if(name.equals("isNetworkSupported")){int type=(Integer)args[0];return type==ConnectivityManager.TYPE_WIFI||type==ConnectivityManager.TYPE_MOBILE||type==ConnectivityManager.TYPE_ETHERNET;}
        if(name.equals("isTetheringSupported"))return false;
        if(!(name.startsWith("get")||name.equals("isActiveNetworkMetered")))throw SdRuntimeDiagnostics.unsupported("Host connectivity",method);
        SdConnectivitySnapshot data=snapshot();SdConnectivitySnapshot.Link selected=data.activeLink();
        if(name.equals("getNetworkInfoForUid")){
            if((Integer)args[1]!=android.os.Process.myUid())throw new SecurityException("Cross-UID network query unavailable");
            for(SdConnectivitySnapshot.Link link:data.links.values())if(link.network.equals(args[0]))return link.info();return null;
        }
        if(name.equals("getActiveNetworkInfoForUid")){
            if((Integer)args[0]!=android.os.Process.myUid())throw new SecurityException("Cross-UID network query unavailable");return selected==null?null:selected.info();
        }
        if(name.equals("getActiveNetwork"))return selected==null?null:new Network(selected.network);
        if(name.equals("getActiveNetworkInfo"))return selected==null?null:selected.info();
        if(name.equals("getActiveLinkProperties"))return selected==null?null:new LinkProperties(selected.properties);
        if(name.equals("isActiveNetworkMetered"))return selected==null||!selected.meteredKnown||selected.metered;
        if(name.equals("getAllNetworks")){Network[]values=new Network[data.links.size()];int i=0;for(SdConnectivitySnapshot.Link link:data.links.values())values[i++]=new Network(link.network);return values;}
        if(name.equals("getAllNetworkInfo")){NetworkInfo[]values=new NetworkInfo[data.links.size()];int i=0;for(SdConnectivitySnapshot.Link link:data.links.values())values[i++]=link.info();return values;}
        if(name.equals("getNetworkInfo")||name.equals("getNetworkForType")||name.equals("getLinkPropertiesForType")){
            for(SdConnectivitySnapshot.Link link:data.links.values())if(link.type==(Integer)args[0])return name.equals("getNetworkInfo")?link.info():name.equals("getNetworkForType")?new Network(link.network):new LinkProperties(link.properties);return null;
        }
        if(name.equals("getNetworkInfoForNetwork")||name.equals("getLinkProperties")||name.equals("getNetworkCapabilities")){
            for(SdConnectivitySnapshot.Link link:data.links.values())if(link.network.equals(args[0]))return name.equals("getNetworkInfoForNetwork")?link.info():name.equals("getLinkProperties")?new LinkProperties(link.properties):new NetworkCapabilities(link.capabilities);return null;
        }
        throw SdRuntimeDiagnostics.unsupported("Host connectivity",method);
    }
}
