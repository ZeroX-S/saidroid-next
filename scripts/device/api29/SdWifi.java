import android.Manifest;
import android.content.pm.PackageManager;
import android.net.wifi.IWifiManager;
import android.os.Binder;
import android.os.IBinder;
import java.lang.reflect.*;

/** Read-only Wi-Fi radio state backed by the host ConnMan technology. */
public final class SdWifi implements InvocationHandler {
    private static final SdWifi instance=new SdWifi();
    private final Binder binder=new Binder();
    private final IWifiManager service;
    private SdWifi(){
        service=(IWifiManager)Proxy.newProxyInstance(IWifiManager.class.getClassLoader(),new Class<?>[]{IWifiManager.class},this);
        binder.attachInterface(service,"android.net.wifi.IWifiManager");
    }
    public static IBinder binder(){return instance.binder;}
    @Override public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String name=method.getName();
        if(name.equals("asBinder"))return binder;
        if(name.equals("toString"))return "ConnMan read-only Wi-Fi state";
        if(name.equals("hashCode"))return System.identityHashCode(proxy);
        if(name.equals("equals"))return proxy==args[0];
        // Android's WifiManager constructor reads this before its first radio
        // query. This adapter has no verbose Wi-Fi packet/event logging and no
        // API to enable it; report that actual adapter policy, not ConnMan's
        // unrelated daemon debug setting.
        if(name.equals("getVerboseLoggingLevel"))return 0;
        if(name.equals("getWifiEnabledState")){
            if(SdPackageManagerService.service().checkPermission(Manifest.permission.ACCESS_WIFI_STATE,SdApkPackage.NAME,android.os.Process.myUid()/100000)!=PackageManager.PERMISSION_GRANTED)
                throw new SecurityException("ACCESS_WIFI_STATE is not declared by this application");
            int state=org.saildroid.host.HostApi.wifiEnabledState();
            System.err.println("SDWIFI=radio_state|state="+state+"|source=connman|read_only=true");
            return state;
        }
        throw SdRuntimeDiagnostics.unsupported("Host Wi-Fi service",method);
    }
}
