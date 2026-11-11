import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.PackageParser;
import android.content.pm.ResolveInfo;
import android.content.pm.ServiceInfo;
import android.content.pm.ProviderInfo;
import android.os.Process;
import java.io.File;
import java.util.ArrayList;
import java.util.List;

/** Package metadata is parsed from the selected installed APK, never guessed. */
public final class SdApkPackage {
    public static final String NAME=System.getProperty("saidroid.package","com.tencent.mobileqq");
    public static final String APK=System.getProperty("saidroid.apk","/home/art/realapps/qq.apk");
    public static final String NATIVE=System.getProperty("saidroid.native", "/home/art/realapps/qq-libs");
    public static final String DATA=System.getProperty("saidroid.data","/home/art/data/qq");
    private static PackageParser.Package parsed;
    public static synchronized PackageParser.Package parsed(){
        if(parsed==null)try{
            parsed=new PackageParser().parsePackage(new File(APK),0);
            if(!NAME.equals(parsed.packageName))throw new SecurityException("APK package differs from its installation record");
            // API28 leaves the implicit application/component process unset.
            // Services without android:process belong to the application's process.
            if(parsed.applicationInfo.processName==null)parsed.applicationInfo.processName=NAME;
            for(PackageParser.Service service:parsed.services)
                if(service.info.processName==null)service.info.processName=parsed.applicationInfo.processName;
        }catch(Exception failure){throw new IllegalStateException("Cannot read installed APK metadata",failure);}
        return parsed;
    }
    public static ApplicationInfo applicationInfo(){
        PackageParser.Package source=parsed();ApplicationInfo result=new ApplicationInfo(source.applicationInfo);
        result.uid=Process.myUid();result.deviceProtectedDataDir=DATA+"/device-protected";result.credentialProtectedDataDir=DATA;result.sourceDir=result.publicSourceDir=APK;result.nativeLibraryDir=NATIVE;result.dataDir=DATA;
        if(result.className==null)result.className="android.app.Application";
        if(result.processName==null)result.processName=NAME;
        result.metaData=source.mAppMetaData;
        result.flags|=ApplicationInfo.FLAG_INSTALLED;
        SdSharedLibraries.apply(result,source);
        return result;
    }
    public static String processName(){
        String main=parsed().applicationInfo.processName;if(main==null)main=NAME;
        String requested=System.getProperty("saidroid.process"),service=System.getProperty("saidroid.service"),activity=System.getProperty("saidroid.activity"),provider=System.getProperty("saidroid.provider");if(requested==null)return main;
        boolean declared=false;for(PackageParser.Service candidate:parsed().services)if(candidate.info.name.equals(service)&&requested.equals(candidate.info.processName))declared=true;
        for(PackageParser.Activity candidate:parsed().activities)if(candidate.info.name.equals(activity)&&requested.equals(candidate.info.processName))declared=true;
        for(PackageParser.Provider candidate:parsed().providers)if(candidate.info.name.equals(provider)&&requested.equals(providerProcess(candidate.info)))declared=true;
        if(!declared||requested.equals(main))throw new SecurityException("Secondary process differs from its declared component");return requested;
    }
    public static String providerProcess(ProviderInfo info){return info.processName!=null?info.processName:applicationInfo().processName;}
    private static ActivityInfo activity(PackageParser.Activity source){ActivityInfo result=new ActivityInfo(source.info);result.applicationInfo=applicationInfo();if(result.processName==null)result.processName=NAME;result.metaData=source.metaData;return result;}
    public static ActivityInfo activityInfo(ComponentName component,int flags){
        if(component!=null&&NAME.equals(component.getPackageName())&&SdDocumentPicker.class.getName().equals(component.getClassName()))return SdDocumentPicker.activityInfo();
        if(component!=null&&SdPermissionController.PACKAGE.equals(component.getPackageName())&&SdPermissionController.class.getName().equals(component.getClassName()))return SdPermissionController.settingsActivityInfo();
        if(component==null||!NAME.equals(component.getPackageName()))return null;
        for(PackageParser.Activity candidate:parsed().activities)if(candidate.info.name.equals(component.getClassName())){
            return candidate.info.enabled||(flags&PackageManager.GET_DISABLED_COMPONENTS)!=0?activity(candidate):null;
        }
        return null;
    }
    public static ServiceInfo serviceInfo(ComponentName component,int flags){
        if(component==null||!NAME.equals(component.getPackageName()))return null;
        for(PackageParser.Service source:parsed().services)if(source.info.name.equals(component.getClassName())&&(source.info.enabled||(flags&PackageManager.GET_DISABLED_COMPONENTS)!=0)){ServiceInfo result=new ServiceInfo(source.info);result.applicationInfo=applicationInfo();result.metaData=source.metaData;return result;}return null;
    }
    public static List<ResolveInfo> resolveServices(Intent intent,String type,int flags){
        ArrayList<ResolveInfo> result=new ArrayList<ResolveInfo>();
        if(intent.getComponent()!=null){ServiceInfo info=serviceInfo(intent.getComponent(),flags);if(info!=null){ResolveInfo item=new ResolveInfo();item.serviceInfo=info;result.add(item);}return result;}
        if(intent.getPackage()!=null&&!NAME.equals(intent.getPackage()))return result;
        for(PackageParser.Service source:parsed().services){
            if(!source.info.enabled)continue;
            for(PackageParser.ServiceIntentInfo filter:source.intents){int match=filter.match(intent.getAction(),type,intent.getScheme(),intent.getData(),intent.getCategories(),"SailDroidService");if(match>=0){ResolveInfo item=new ResolveInfo();item.serviceInfo=serviceInfo(new ComponentName(NAME,source.info.name),flags);item.filter=filter;item.match=match;item.priority=filter.getPriority();result.add(item);break;}}
        }
        return result;
    }
    public static ActivityInfo receiverInfo(ComponentName component,int flags){
        if(component==null||!NAME.equals(component.getPackageName()))return null;
        for(PackageParser.Activity source:parsed().receivers)if(source.info.name.equals(component.getClassName())&&(source.info.enabled||(flags&PackageManager.GET_DISABLED_COMPONENTS)!=0))return activity(source);return null;
    }
    public static ProviderInfo providerInfo(ComponentName component,int flags){
        if(component==null||!NAME.equals(component.getPackageName()))return null;
        for(PackageParser.Provider source:parsed().providers)if(source.info.name.equals(component.getClassName())&&(source.info.enabled||(flags&PackageManager.GET_DISABLED_COMPONENTS)!=0)){ProviderInfo result=new ProviderInfo(source.info);result.applicationInfo=applicationInfo();result.metaData=source.metaData;return result;}return null;
    }
    public static List<ResolveInfo> resolveActivities(Intent intent,String type,int flags){
        List<ResolveInfo> result=new ArrayList<ResolveInfo>();
        ResolveInfo settings=SdPermissionController.resolveSettings(intent);if(settings!=null){result.add(settings);return result;}
        if(intent.getComponent()!=null){ActivityInfo info=activityInfo(intent.getComponent(),flags);if(info!=null){ResolveInfo resolved=new ResolveInfo();resolved.activityInfo=info;result.add(resolved);}return result;}
        if(intent.getPackage()!=null&&!NAME.equals(intent.getPackage()))return result;
        for(PackageParser.Activity candidate:parsed().activities){
            if(!candidate.info.enabled&&(flags&PackageManager.GET_DISABLED_COMPONENTS)==0)continue;
            for(PackageParser.ActivityIntentInfo filter:candidate.intents){
                if((flags&PackageManager.MATCH_DEFAULT_ONLY)!=0&&!filter.hasCategory(Intent.CATEGORY_DEFAULT))continue;
                int match=filter.match(intent.getAction(),type,intent.getScheme(),intent.getData(),intent.getCategories(),"SailDroidIntent");
                if(match>=0){ResolveInfo resolved=new ResolveInfo();resolved.activityInfo=activity(candidate);resolved.match=match;resolved.priority=filter.getPriority();resolved.filter=filter;result.add(resolved);break;}
            }
        }
        if(result.isEmpty()){ResolveInfo document=SdDocumentPicker.resolve(intent,type);if(document!=null)result.add(document);}
        return result;
    }
    public static PackageInfo packageInfo(int flags){
        PackageParser.Package source=parsed();PackageInfo result=new PackageInfo();result.packageName=NAME;result.versionCode=source.mVersionCode;result.versionName=source.mVersionName;result.applicationInfo=applicationInfo();result.installLocation=source.installLocation;
        if((flags&PackageManager.GET_INSTRUMENTATION)!=0){java.util.ArrayList<android.content.pm.InstrumentationInfo> entries=new java.util.ArrayList<android.content.pm.InstrumentationInfo>();for(PackageParser.Instrumentation item:source.instrumentation)entries.add(SdInstrumentation.info(new ComponentName(NAME,item.info.name)));result.instrumentation=entries.toArray(new android.content.pm.InstrumentationInfo[entries.size()]);}
        if((flags&PackageManager.GET_ACTIVITIES)!=0){ArrayList<ActivityInfo> entries=new ArrayList<ActivityInfo>();for(PackageParser.Activity a:source.activities)if(a.info.enabled||(flags&PackageManager.GET_DISABLED_COMPONENTS)!=0)entries.add(activity(a));result.activities=entries.toArray(new ActivityInfo[entries.size()]);}
        if((flags&PackageManager.GET_RECEIVERS)!=0){ArrayList<ActivityInfo> entries=new ArrayList<ActivityInfo>();for(PackageParser.Activity a:source.receivers)entries.add(activity(a));result.receivers=entries.toArray(new ActivityInfo[entries.size()]);}
        if((flags&PackageManager.GET_SERVICES)!=0){ArrayList<ServiceInfo> entries=new ArrayList<ServiceInfo>();for(PackageParser.Service a:source.services){ServiceInfo info=new ServiceInfo(a.info);info.applicationInfo=applicationInfo();info.metaData=a.metaData;entries.add(info);}result.services=entries.toArray(new ServiceInfo[entries.size()]);}
        if((flags&PackageManager.GET_PROVIDERS)!=0){ArrayList<ProviderInfo> entries=new ArrayList<ProviderInfo>();for(PackageParser.Provider a:source.providers){ProviderInfo info=new ProviderInfo(a.info);info.applicationInfo=applicationInfo();info.metaData=a.metaData;entries.add(info);}result.providers=entries.toArray(new ProviderInfo[entries.size()]);}
        if((flags&PackageManager.GET_PERMISSIONS)!=0){
            result.requestedPermissions=source.requestedPermissions.toArray(new String[source.requestedPermissions.size()]);
            result.requestedPermissionsFlags=new int[result.requestedPermissions.length];
            try{
                SdAppPermissions permissions=new SdAppPermissions(APK,NAME);
                for(int index=0;index<result.requestedPermissions.length;index++)result.requestedPermissionsFlags[index]=PackageInfo.REQUESTED_PERMISSION_REQUIRED|(permissions.holds(result.requestedPermissions[index])?PackageInfo.REQUESTED_PERMISSION_GRANTED:0);
            }catch(Exception failure){throw new IllegalStateException("Cannot read package permission flags",failure);}
        }
        if((flags&(PackageManager.GET_SIGNATURES|PackageManager.GET_SIGNING_CERTIFICATES))!=0){
            synchronized(SdApkPackage.class){
                try{if(source.mSigningDetails==PackageParser.SigningDetails.UNKNOWN)PackageParser.collectCertificates(source,false);}
                catch(Exception failure){throw new IllegalStateException("Cannot verify application signing certificates",failure);}
                if((flags&PackageManager.GET_SIGNATURES)!=0)result.signatures=source.mSigningDetails.signatures.clone();
                if((flags&PackageManager.GET_SIGNING_CERTIFICATES)!=0)result.signingInfo=new android.content.pm.SigningInfo(source.mSigningDetails);
            }
        }
        return result;
    }
}
