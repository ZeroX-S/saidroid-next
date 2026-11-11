import android.app.ActivityThread;
import android.app.ContentProviderHolder;
import android.content.Context;
import android.content.ContentProviderNative;
import android.content.pm.ProviderInfo;
import android.os.Binder;
import android.os.IBinder;
import android.os.Process;
import android.os.RemoteException;
import android.os.SystemClock;

/** Provider transports belong to their declared process and cross real Binder. */
public final class SdContentProviders {
    private static ContentProviderHolder settings;
    private static ContentProviderHolder instrumentationFiles;
    private static ContentProviderHolder downloads;
    private static ContentProviderHolder media;
    private static ContentProviderHolder documents;
    private static final java.util.HashMap<String,ContentProviderHolder> providers=new java.util.HashMap<String,ContentProviderHolder>();
    private static String registryName(String authority){
        return "saidroid.provider."+SdKernelServices.processName(SdApkPackage.NAME,authority).substring("saidroid.process.".length());
    }
    public static synchronized void publish(java.util.List<ContentProviderHolder> incoming){
        for(ContentProviderHolder holder:incoming){
            if(holder.info==null||holder.provider==null||!SdApkPackage.NAME.equals(holder.info.packageName)||!SdApkPackage.processName().equals(SdApkPackage.providerProcess(holder.info)))throw new SecurityException("Provider owner differs from this process");
            if(holder.connection==null)holder.connection=new Binder();holder.noReleaseNeeded=true;
            for(String name:holder.info.authority.split(";")){
                providers.put(name,holder);
                if(SdKernelServices.enabled())try{SdKernelServices.registry().addService(registryName(name),holder.provider.asBinder(),false,0);}catch(RemoteException failure){throw new IllegalStateException("Provider transport publication failed",failure);}
            }
        }
    }
    public static ContentProviderHolder acquire(String authority,int user){
        if(user!=Process.myUid()/100000)throw new SecurityException("Cross-user provider access unavailable");
        if("android.tradefed.contentprovider".equals(authority)&&SdInstrumentation.requested())return instrumentationFiles();
        if("downloads".equals(authority))return downloads();
        if("media".equals(authority))return media();
        if(SdDocumentsProvider.AUTHORITY.equals(authority))return documents();
        if(!"settings".equals(authority)){
            synchronized(SdContentProviders.class){ContentProviderHolder current=providers.get(authority);if(current!=null)return current;}
            for(android.content.pm.PackageParser.Provider declared:SdApkPackage.parsed().providers){
                if(declared.info.authority==null||!declared.info.enabled)continue;
                for(String name:declared.info.authority.split(";"))if(name.equals(authority)){
                    ProviderInfo info=new ProviderInfo(declared.info);info.processName=SdApkPackage.providerProcess(info);info.applicationInfo=SdApkPackage.applicationInfo();info.metaData=declared.metaData;
                    ContentProviderHolder holder=new ContentProviderHolder(info);holder.noReleaseNeeded=true;
                    if(info.processName.equals(SdApkPackage.processName()))return holder;
                    if(!SdKernelServices.enabled())throw new UnsupportedOperationException("Provider process requires private Binder");
                    try{
                        IBinder transport=SdKernelServices.registry().checkService(registryName(authority));
                        if(transport==null||!transport.isBinderAlive()){
                            String endpoint=SdKernelServices.processName(SdApkPackage.NAME,info.processName);
                            IBinder process=SdKernelServices.registry().checkService(endpoint);
                            if(process==null||!process.isBinderAlive())org.saildroid.host.HostApi.startProviderProcess(SdApkPackage.NAME,info.name,info.processName);
                            long deadline=SystemClock.uptimeMillis()+30000;
                            do{
                                transport=SdKernelServices.registry().checkService(registryName(authority));
                                if(transport!=null&&transport.isBinderAlive())break;
                                if(SystemClock.uptimeMillis()>=deadline)throw new IllegalStateException("Provider process publication deadline");
                                Thread.sleep(25);
                            }while(true);
                        }
                        holder.provider=ContentProviderNative.asInterface(transport);holder.connection=new Binder();
                        System.err.println("SDCONTENT=remote_transport|process="+info.processName+"|local=false");return holder;
                    }catch(InterruptedException failure){Thread.currentThread().interrupt();throw new IllegalStateException("Provider process wait interrupted",failure);}
                    catch(RemoteException failure){throw new IllegalStateException("Provider process transport failed",failure);}
                }
            }
            return null;
        }
        return settings();
    }
    private static synchronized ContentProviderHolder media(){
        if(media==null){
            Context context=ActivityThread.currentApplication();if(context==null)throw new IllegalStateException("Media provider requires a bound app");
            ProviderInfo info=new ProviderInfo();info.authority="media";info.name=SdMediaProvider.class.getName();info.packageName="android";info.applicationInfo=context.getApplicationInfo();info.exported=false;
            SdMediaProvider provider=new SdMediaProvider();provider.attachInfo(context,info);media=new ContentProviderHolder(info);media.provider=provider.getIContentProvider();media.connection=new Binder();media.noReleaseNeeded=true;
        }
        return media;
    }
    private static synchronized ContentProviderHolder documents(){
        if(documents==null){
            Context context=ActivityThread.currentApplication();if(context==null)throw new IllegalStateException("Documents require a bound app");
            ProviderInfo info=SdDocumentsProvider.info();
            SdDocumentsProvider provider=new SdDocumentsProvider();provider.attachInfo(context,info);
            documents=new ContentProviderHolder(info);documents.provider=provider.getIContentProvider();documents.connection=new Binder();documents.noReleaseNeeded=true;
        }
        return documents;
    }
    private static synchronized ContentProviderHolder settings(){
        if(settings==null){
            Context context=ActivityThread.currentActivityThread().getSystemContext();
            ProviderInfo info=new ProviderInfo();info.authority="settings";info.name=SdSettingsProvider.class.getName();info.packageName="android";info.applicationInfo=context.getApplicationInfo();info.exported=true;
            SdSettingsProvider provider=new SdSettingsProvider();provider.attachInfo(context,info);
            settings=new ContentProviderHolder(info);settings.provider=provider.getIContentProvider();settings.connection=new Binder();settings.noReleaseNeeded=true;
        }
        return settings;
    }
    private static synchronized ContentProviderHolder downloads(){
        if(downloads==null){
            Context context=ActivityThread.currentApplication();
            if(context==null)throw new IllegalStateException("Downloads require a bound application");
            ProviderInfo info=new ProviderInfo();info.authority="downloads";info.name=SdDownloadsProvider.class.getName();info.packageName=SdApkPackage.NAME;info.applicationInfo=SdApkPackage.applicationInfo();info.exported=false;
            SdDownloadsProvider provider=new SdDownloadsProvider();provider.attachInfo(context,info);
            downloads=new ContentProviderHolder(info);downloads.provider=provider.getIContentProvider();downloads.connection=new Binder();downloads.noReleaseNeeded=true;
        }
        return downloads;
    }
    private static synchronized ContentProviderHolder instrumentationFiles(){
        if(instrumentationFiles==null){
            Context context=ActivityThread.currentActivityThread().getSystemContext();
            ProviderInfo info=new ProviderInfo();info.authority="android.tradefed.contentprovider";info.name=SdInstrumentationFiles.class.getName();info.packageName="android";info.applicationInfo=context.getApplicationInfo();info.exported=false;
            SdInstrumentationFiles provider=new SdInstrumentationFiles();provider.attachInfo(context,info);
            instrumentationFiles=new ContentProviderHolder(info);instrumentationFiles.provider=provider.getIContentProvider();instrumentationFiles.connection=new Binder();instrumentationFiles.noReleaseNeeded=true;
        }
        return instrumentationFiles;
    }
}
