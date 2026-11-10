import android.Manifest;
import android.content.pm.PackageManager;
import android.net.wifi.IWifiManager;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiSsid;
import android.net.wifi.SupplicantState;
import android.net.DhcpInfo;
import android.net.NetworkUtils;
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
    private static boolean permission(String name)throws android.os.RemoteException{
        return SdPackageManagerService.service().checkPermission(name,SdApkPackage.NAME,android.os.Process.myUid()/100000)==PackageManager.PERMISSION_GRANTED;
    }
    private static org.json.JSONObject connection(boolean includeName)throws org.json.JSONException,android.os.RemoteException{
        if(!permission(Manifest.permission.ACCESS_WIFI_STATE))throw new SecurityException("ACCESS_WIFI_STATE is not declared by this application");
        return new org.json.JSONObject(org.saildroid.host.HostApi.wifiConnectionInfo(includeName));
    }
    private static int ipv4(String address){
        if(address.length()==0)return 0;
        return NetworkUtils.inetAddressToInt((java.net.Inet4Address)NetworkUtils.numericToInetAddress(address));
    }
    private static WifiInfo connectionInfo()throws org.json.JSONException,android.os.RemoteException{
        boolean location=permission(Manifest.permission.ACCESS_FINE_LOCATION)||permission(Manifest.permission.ACCESS_COARSE_LOCATION);
        org.json.JSONObject snapshot=connection(location);
        WifiInfo info=new WifiInfo();
        info.setSupplicantState(snapshot.getBoolean("connected")?SupplicantState.COMPLETED:SupplicantState.DISCONNECTED);
        String address=snapshot.optString("address");
        if(address.length()!=0)info.setInetAddress(NetworkUtils.numericToInetAddress(address));
        if(location&&snapshot.has("name")){
            byte[] bytes=snapshot.getString("name").getBytes(java.nio.charset.StandardCharsets.UTF_8);
            StringBuilder hex=new StringBuilder();
            for(byte value:bytes)hex.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
            info.setSSID(WifiSsid.createFromHex(hex.toString()));
        }
        System.err.println("SDWIFI=connection_info|connected="+snapshot.getBoolean("connected")+"|source=connman|name_authorized="+location);
        return info;
    }
    private static DhcpInfo dhcpInfo()throws org.json.JSONException,android.os.RemoteException{
        org.json.JSONObject snapshot=connection(false);
        DhcpInfo info=new DhcpInfo();
        info.ipAddress=ipv4(snapshot.optString("address"));
        info.netmask=ipv4(snapshot.optString("netmask"));
        info.gateway=ipv4(snapshot.optString("gateway"));
        org.json.JSONArray dns=snapshot.optJSONArray("dns");
        if(dns!=null&&dns.length()>0)info.dns1=ipv4(dns.getString(0));
        if(dns!=null&&dns.length()>1)info.dns2=ipv4(dns.getString(1));
        return info;
    }
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
        if(name.equals("getConnectionInfo"))return connectionInfo();
        if(name.equals("getDhcpInfo"))return dhcpInfo();
        if(name.equals("getSupportedFeatures")){
            if(!permission(Manifest.permission.ACCESS_WIFI_STATE))throw new SecurityException("ACCESS_WIFI_STATE is not declared by this application");
            return org.saildroid.host.HostApi.wifiSupportedFeatures();
        }
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
