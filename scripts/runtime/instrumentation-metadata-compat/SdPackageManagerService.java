import android.content.*;
import android.content.pm.*;
import android.os.*;
import android.os.Process;
import java.lang.reflect.*;
import java.util.*;

/** API 29 package service. Answers derive from the real selected APK. */
public final class SdPackageManagerService implements InvocationHandler {
    private static final SdPackageManagerService instance=new SdPackageManagerService();
    private final Binder binder=new Binder();private final IPackageManager service;
    private SdAppPermissions permissions;
    private final HashMap<Integer,Long> useTimes=new HashMap<Integer,Long>();
    private final ArrayList<String> loadedDex=new ArrayList<String>();
    private SdPackageManagerService(){service=(IPackageManager)Proxy.newProxyInstance(IPackageManager.class.getClassLoader(),new Class<?>[]{IPackageManager.class},this);binder.attachInterface(service,"android.content.pm.IPackageManager");}
    public static IBinder binder(){return instance.binder;}public static IPackageManager service(){return instance.service;}
    private ApplicationInfo app(String name){
        if(SdApkPackage.NAME.equals(name))return SdApkPackage.applicationInfo();if(!"android".equals(name))return SdInstrumentation.applicationInfo(name);
        ApplicationInfo value=new ApplicationInfo();value.packageName="android";value.name=value.className="android.app.Application";value.processName="android";value.uid=Process.SYSTEM_UID;value.sourceDir=value.publicSourceDir=System.getenv("ANDROID_ROOT")+"/framework/framework-res.apk";value.flags=ApplicationInfo.FLAG_SYSTEM;value.targetSdkVersion=29;value.enabled=true;return value;
    }
    private PackageInfo info(String name,int flags){if(SdApkPackage.NAME.equals(name))return SdApkPackage.packageInfo(flags);if(SdInstrumentation.applicationInfo(name)!=null)return SdInstrumentation.packageInfo(name);ApplicationInfo app=app(name);if(app==null)return null;PackageInfo result=new PackageInfo();result.packageName=name;result.applicationInfo=app;result.versionCode=29;result.versionName="10";return result;}
    private synchronized int permission(String name,String owner)throws Exception{
        if(SdApkPackage.NAME.equals(owner)){
            if(permissions==null)permissions=new SdAppPermissions(SdApkPackage.APK,SdApkPackage.NAME);
            return permissions.holds(name)?PackageManager.PERMISSION_GRANTED:PackageManager.PERMISSION_DENIED;
        }
        ApplicationInfo runner=SdInstrumentation.applicationInfo(owner);
        if(runner==null)return PackageManager.PERMISSION_DENIED;
        return new SdAppPermissions(runner.sourceDir,owner).holds(name)?PackageManager.PERMISSION_GRANTED:PackageManager.PERMISSION_DENIED;
    }
    private static ProviderInfo provider(String authority){for(PackageParser.Provider p:SdApkPackage.parsed().providers)if(p.info.authority!=null&&Arrays.asList(p.info.authority.split(";")).contains(authority)){ProviderInfo result=new ProviderInfo(p.info);result.applicationInfo=SdApkPackage.applicationInfo();result.metaData=p.metaData;return result;}return null;}
    private static PackageParser.Package platform;
    private static synchronized PermissionInfo permissionInfo(String name,int flags)throws Exception{
        if(name==null)throw new IllegalArgumentException("Permission name required");
        for(PackageParser.Permission p:SdApkPackage.parsed().permissions)if(name.equals(p.info.name)){PermissionInfo out=new PermissionInfo(p.info);if((flags&PackageManager.GET_META_DATA)!=0)out.metaData=p.metaData;return out;}
        if(platform==null){platform=new PackageParser().parsePackage(new java.io.File(System.getenv("ANDROID_ROOT")+"/framework/framework-res.apk"),0);if(!"android".equals(platform.packageName))throw new SecurityException("Platform permission manifest identity differs");}
        for(PackageParser.Permission p:platform.permissions)if(name.equals(p.info.name)){PermissionInfo out=new PermissionInfo(p.info);if((flags&PackageManager.GET_META_DATA)!=0)out.metaData=p.metaData;return out;}
        return null;
    }
    @Override public Object invoke(Object proxy,Method method,Object[] a)throws Throwable{
        String n=method.getName();if(n.equals("asBinder"))return binder;if(n.equals("toString"))return "SailDroid APK package service";if(n.equals("hashCode"))return System.identityHashCode(proxy);if(n.equals("equals"))return proxy==a[0];
        if(n.equals("getApplicationInfo"))return app((String)a[0]);if(n.equals("getPackageInfo"))return info((String)a[0],(Integer)a[1]);
        if(n.equals("notifyPackageUse")){
            if(!SdApkPackage.NAME.equals(a[0])&&SdInstrumentation.applicationInfo((String)a[0])==null)throw new SecurityException("Usage package mismatch");
            synchronized(useTimes){useTimes.put((Integer)a[1],SystemClock.elapsedRealtime());}return null;
        }
        if(n.equals("notifyDexLoad")){
            if(!SdApkPackage.NAME.equals(a[0])&&SdInstrumentation.applicationInfo((String)a[0])==null)throw new SecurityException("DEX owner mismatch");
            synchronized(loadedDex){loadedDex.add(String.valueOf(a[1])+"|"+String.valueOf(a[2])+"|"+String.valueOf(a[3]));}return null;
        }
        if(n.equals("getPackageUid")){ApplicationInfo app=app((String)a[0]);return app==null?-1:app.uid;}
        if(n.equals("getPackagesForUid"))return (Integer)a[0]==Process.myUid()?new String[]{SdApkPackage.NAME}:(Integer)a[0]==Process.SYSTEM_UID?new String[]{"android"}:null;
        if(n.equals("getNameForUid"))return (Integer)a[0]==Process.myUid()?SdApkPackage.NAME:null;
        if(n.equals("getPackageGids")){if(app((String)a[0])==null)return null;String groups=new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get("/proc/self/status")),"UTF-8");for(String line:groups.split("\n"))if(line.startsWith("Groups:")){String value=line.substring(7).trim();if(value.isEmpty())return new int[0];String[] parts=value.split("\\s+");int[] ids=new int[parts.length];for(int i=0;i<parts.length;i++)ids[i]=Integer.parseInt(parts[i]);return ids;}throw new IllegalStateException("Process group information unavailable");}
        if(n.equals("checkPermission"))return permission((String)a[0],(String)a[1]);
        if(n.equals("checkUidPermission"))return (Integer)a[1]==Process.myUid()?permission((String)a[0],SdApkPackage.NAME):PackageManager.PERMISSION_DENIED;
        if(n.equals("isPackageAvailable"))return app((String)a[0])!=null;
        if(n.equals("isInstantApp")){
            if((Integer)a[1]!=Process.myUid()/100000)throw new SecurityException("Cross-user instant application query unavailable");
            ApplicationInfo value=app((String)a[0]);
            // This installation store deploys full APKs only. Read the real
            // parsed ApplicationInfo flag; do not advertise an instant installer.
            return value!=null&&value.isInstantApp();
        }
        if(n.equals("getPermissionInfo"))return permissionInfo((String)a[0],(Integer)a[2]);
        if(n.equals("getInstrumentationInfo"))return SdInstrumentation.info((ComponentName)a[0],((Number)a[1]).intValue());
        if(n.equals("getActivityInfo"))return SdApkPackage.activityInfo((ComponentName)a[0],(Integer)a[1]);
        if(n.equals("getServiceInfo"))return SdApkPackage.serviceInfo((ComponentName)a[0],(Integer)a[1]);
        if(n.equals("queryIntentServices"))return new ParceledListSlice<ResolveInfo>(SdApkPackage.resolveServices((Intent)a[0],(String)a[1],(Integer)a[2]));
        if(n.equals("resolveService")){List<ResolveInfo> results=SdApkPackage.resolveServices((Intent)a[0],(String)a[1],(Integer)a[2]);return results.isEmpty()?null:results.get(0);}
        if(n.equals("getReceiverInfo"))return SdApkPackage.receiverInfo((ComponentName)a[0],(Integer)a[1]);
        if(n.equals("getProviderInfo"))return SdApkPackage.providerInfo((ComponentName)a[0],(Integer)a[1]);
        if(n.equals("queryIntentActivities"))return new ParceledListSlice<ResolveInfo>(SdApkPackage.resolveActivities((Intent)a[0],(String)a[1],(Integer)a[2]));
        if(n.equals("resolveIntent")){List<ResolveInfo> results=SdApkPackage.resolveActivities((Intent)a[0],(String)a[1],(Integer)a[2]);return results.isEmpty()?null:results.get(0);}
        if(n.equals("resolveContentProvider"))return provider((String)a[0]);
        if(n.equals("getInstalledPackages"))return new ParceledListSlice<PackageInfo>(Arrays.asList(info(SdApkPackage.NAME,(Integer)a[0]),info("android",(Integer)a[0])));
        if(n.equals("getInstalledApplications"))return new ParceledListSlice<ApplicationInfo>(Arrays.asList(app(SdApkPackage.NAME),app("android")));
        if(n.equals("getApplicationEnabledSetting")){ApplicationInfo app=app((String)a[0]);if(app==null)throw new IllegalArgumentException("Unknown package");return app.enabled?PackageManager.COMPONENT_ENABLED_STATE_DEFAULT:PackageManager.COMPONENT_ENABLED_STATE_DISABLED;}
        if(n.equals("getComponentEnabledSetting")){
            ComponentName component=(ComponentName)a[0];int user=(Integer)a[1];
            if(user!=Process.myUid()/100000)throw new SecurityException("Cross-user component state unavailable");
            int flags=PackageManager.MATCH_DISABLED_COMPONENTS;
            if(SdApkPackage.activityInfo(component,flags)==null&&SdApkPackage.serviceInfo(component,flags)==null&&SdApkPackage.receiverInfo(component,flags)==null&&SdApkPackage.providerInfo(component,flags)==null)throw new IllegalArgumentException("Unknown declared component");
            // This package store currently has no per-component overrides.
            // DEFAULT asks Android to use the actual manifest enabled flag.
            System.err.println("SDPACKAGE=component_state|class="+component.getClassName()+"|state=default");
            return PackageManager.COMPONENT_ENABLED_STATE_DEFAULT;
        }
        if(n.equals("hasSystemFeature"))return false; // No optional Android hardware feature has a host backend yet.
        if(n.equals("getSystemAvailableFeatures"))return new ParceledListSlice<FeatureInfo>(Collections.<FeatureInfo>emptyList());
        if(n.equals("getInstallerPackageName"))return app((String)a[0])==null?null:"org.saildroid.manager";
        if(n.equals("isPackageSuspendedForUser")){if(app((String)a[0])==null)throw new IllegalArgumentException("Unknown package");return false;}
        throw SdRuntimeDiagnostics.unsupported("APK package service",method);
    }
}
