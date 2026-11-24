import android.app.IInstrumentationWatcher;
import android.content.ComponentName;
import android.content.pm.InstrumentationInfo;
import android.content.pm.PackageParser;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONObject;
import java.io.*;
import java.lang.reflect.Field;
import java.util.Iterator;

/** Bind the APK's declared real Instrumentation through ActivityThread.
 * Results use Android's watcher codes/bundles, retained atomically per run.
 * No test classes, outcomes, contexts or hardware capabilities are fabricated.
 */
public final class SdInstrumentation {
    private static JSONObject request;
    private static ComponentName component;
    private static Bundle accumulated=new Bundle();
    private static boolean finished;
    private static File directory;
    private static android.content.pm.ApplicationInfo runnerApplication;
    private static PackageParser.Package runnerPackage;
    private static android.app.LoadedApk runnerLoadedApk;
    public static java.io.File dynamicConfig(String filename)throws java.io.FileNotFoundException {
        try {
            prepare();
            if(filename==null||!filename.matches("[A-Za-z0-9_.-]+\\.dynamic"))throw new SecurityException("Invalid dynamic configuration name");
            org.json.JSONArray configs=request.optJSONArray("dynamic_configs");
            if(configs!=null)for(int i=0;i<configs.length();i++){
                JSONObject config=configs.getJSONObject(i);
                if(!filename.equals(config.getString("name")))continue;
                File file=new File(config.getString("path")).getCanonicalFile();
                File base=new File(SdApkPackage.DATA,"files/cts-config").getCanonicalFile();
                if(!file.getPath().startsWith(base.getPath()+File.separator)||!file.isFile())throw new SecurityException("Dynamic configuration escaped the instrumentation installation");
                byte[] bytes=java.nio.file.Files.readAllBytes(file.toPath());
                byte[] hash=java.security.MessageDigest.getInstance("SHA-256").digest(bytes);StringBuilder digest=new StringBuilder();for(byte value:hash)digest.append(String.format(java.util.Locale.US,"%02x",value&255));
                if(!digest.toString().equals(config.getString("sha256")))throw new SecurityException("Dynamic configuration hash differs");
                return file;
            }
        }catch(java.io.FileNotFoundException error){throw error;}
        catch(Exception error){throw new java.io.FileNotFoundException(error.toString());}
        throw new java.io.FileNotFoundException("No prepared dynamic configuration "+filename);
    }
    private static void loadRunner(ComponentName name)throws Exception{
        if(SdApkPackage.NAME.equals(name.getPackageName()))return;
        String pkg=name.getPackageName();
        if(!pkg.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+"))throw new SecurityException("Invalid instrumentation package");
        File root=new File("/home/art/apps").getCanonicalFile(),base=new File(root,pkg);
        if(!base.getCanonicalFile().equals(base.getAbsoluteFile())||!base.isDirectory())throw new SecurityException("Instrumentation package directory escaped");
        JSONObject record=new JSONObject(new String(java.nio.file.Files.readAllBytes(new File(base,"record.json").toPath()),"UTF-8"));
        if(!pkg.equals(record.getString("package")))throw new SecurityException("Instrumentation record package differs");
        for(String key:new String[]{"apk","native","data"})if(!new File(record.getString(key)).getCanonicalPath().startsWith(base.getPath()+File.separator))throw new SecurityException("Instrumentation path escaped private installation");
        File apk=new File(record.getString("apk"));runnerPackage=new PackageParser().parsePackage(apk,0);
        if(!pkg.equals(runnerPackage.packageName))throw new SecurityException("Instrumentation APK package differs");
        PackageParser.collectCertificates(runnerPackage,false);PackageParser.collectCertificates(SdApkPackage.parsed(),false);
        // Android requires a matching signer for a non-debuggable target. No
        // dangerous/signature permission is inferred or automatically granted.
        if((SdApkPackage.applicationInfo().flags&android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)==0&&!android.content.pm.Signature.areExactMatch(runnerPackage.mSigningDetails.signatures,SdApkPackage.parsed().mSigningDetails.signatures))throw new SecurityException("Instrumentation signer differs from non-debuggable target");
        runnerApplication=new android.content.pm.ApplicationInfo(runnerPackage.applicationInfo);
        runnerApplication.uid=android.os.Process.myUid();runnerApplication.sourceDir=runnerApplication.publicSourceDir=apk.getCanonicalPath();runnerApplication.nativeLibraryDir=new File(record.getString("native")).getCanonicalPath();runnerApplication.dataDir=new File(record.getString("data")).getCanonicalPath();runnerApplication.credentialProtectedDataDir=runnerApplication.dataDir;runnerApplication.deviceProtectedDataDir=runnerApplication.dataDir+"/device-protected";runnerApplication.metaData=runnerPackage.mAppMetaData;runnerApplication.flags|=android.content.pm.ApplicationInfo.FLAG_INSTALLED;
        SdSharedLibraries.apply(runnerApplication,runnerPackage);
    }
    public static android.content.pm.ApplicationInfo applicationInfo(String name){return runnerApplication!=null&&runnerApplication.packageName.equals(name)?new android.content.pm.ApplicationInfo(runnerApplication):null;}
    public static android.content.pm.PackageInfo packageInfo(String name){
        android.content.pm.ApplicationInfo app=applicationInfo(name);if(app==null)return null;
        android.content.pm.PackageInfo value=new android.content.pm.PackageInfo();value.packageName=name;value.applicationInfo=app;value.versionCode=runnerPackage.mVersionCode;value.versionName=runnerPackage.mVersionName;return value;
    }
    public static boolean requested(){return System.getProperty("saidroid.instrumentation.request")!=null;}
    private static void set(Object object,String name,Object value)throws Exception{Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);f.set(object,value);}
    private static synchronized void prepare()throws Exception{
        if(request!=null)return;
        File data=new File(SdApkPackage.DATA).getCanonicalFile();
        File input=new File(System.getProperty("saidroid.instrumentation.request")).getCanonicalFile();
        if(!input.getPath().startsWith(data.getPath()+File.separator)||!input.isFile()||input.length()>65536)throw new SecurityException("Instrumentation request must belong to target private data");
        request=new JSONObject(new String(java.nio.file.Files.readAllBytes(input.toPath()),"UTF-8"));
        String id=request.getString("run_id");if(!id.matches("[a-zA-Z0-9_-]{1,100}"))throw new IllegalArgumentException("Invalid instrumentation run ID");
        component=ComponentName.unflattenFromString(request.getString("component"));
        if(component==null)throw new IllegalArgumentException("Invalid instrumentation component");
        loadRunner(component);
        InstrumentationInfo info=info(component);if(info==null)throw new IllegalArgumentException("Undeclared instrumentation component");
        if(!SdApkPackage.NAME.equals(info.targetPackage))throw new UnsupportedOperationException("Instrumentation target differs from installed application");
        directory=new File(data,"files/instrumentation/"+id).getCanonicalFile();
        if(!directory.getPath().startsWith(data.getPath()+File.separator)||directory.exists()||!directory.mkdirs())throw new IOException("Instrumentation result directory must be new");
    }
    public static InstrumentationInfo info(ComponentName name){
        return info(name,0);
    }
    public static InstrumentationInfo info(ComponentName name,int flags){
        if(name==null)return null;
        PackageParser.Package source=SdApkPackage.NAME.equals(name.getPackageName())?SdApkPackage.parsed():runnerPackage;
        if(source==null||!source.packageName.equals(name.getPackageName()))return null;
        for(PackageParser.Instrumentation declared:source.instrumentation)if(name.getClassName().equals(declared.info.name)){
            InstrumentationInfo value=new InstrumentationInfo(declared.info);android.content.pm.ApplicationInfo app=SdApkPackage.NAME.equals(name.getPackageName())?SdApkPackage.applicationInfo():applicationInfo(name.getPackageName());
            value.metaData=(flags & android.content.pm.PackageManager.GET_META_DATA)!=0 && declared.metaData!=null ? new Bundle(declared.metaData) : null;
            value.sourceDir=value.publicSourceDir=app.sourceDir;value.dataDir=app.dataDir;value.credentialProtectedDataDir=app.credentialProtectedDataDir;value.deviceProtectedDataDir=app.deviceProtectedDataDir;value.nativeLibraryDir=app.nativeLibraryDir;value.primaryCpuAbi=app.primaryCpuAbi;return value;
        }
        return null;
    }
    private static JSONObject json(Bundle bundle)throws Exception{
        JSONObject value=new JSONObject();if(bundle==null)return value;
        for(String key:bundle.keySet()){
            Object item=bundle.get(key);if(item instanceof Bundle)item=json((Bundle)item);
            if(item==null||item instanceof Number||item instanceof Boolean||item instanceof String||item instanceof JSONObject)value.put(key,item==null?JSONObject.NULL:item);else value.put(key,String.valueOf(item));
        }
        return value;
    }
    private static synchronized void event(String kind,int code,Bundle bundle)throws Exception{
        JSONObject value=new JSONObject();value.put("event",kind);value.put("code",code);value.put("bundle",json(bundle));value.put("time_ms",android.os.SystemClock.uptimeMillis());
        try(FileOutputStream output=new FileOutputStream(new File(directory,"events.jsonl"),true)){output.write((value.toString()+"\n").getBytes("UTF-8"));output.getFD().sync();}
        // Same protocol consumed by Android instrumentation host runners.
        String prefix=kind.equals("finished")?"INSTRUMENTATION_RESULT: ":"INSTRUMENTATION_STATUS: ";
        if(bundle!=null)for(String key:bundle.keySet())System.out.println(prefix+key+"="+String.valueOf(bundle.get(key)));
        System.out.println((kind.equals("finished")?"INSTRUMENTATION_CODE: ":"INSTRUMENTATION_STATUS_CODE: ")+code);
    }
    public static void bind(Object data)throws Exception{
        prepare();
        if(runnerApplication!=null){
            android.app.ActivityThread thread=android.app.ActivityThread.currentActivityThread();
            android.app.LoadedApk target=thread.getPackageInfoNoCheck(SdApkPackage.applicationInfo(),android.content.res.CompatibilityInfo.DEFAULT_COMPATIBILITY_INFO);
            // ActivityThread normally creates the target loader with both APK
            // paths for instrumentation. Our bootstrap has already initialized
            // that loader, so extend the same loader before binding Application.
            // AJUR discovers test classes through the target/context loader.
            ClassLoader shared=target.getClassLoader();
            dalvik.system.BaseDexClassLoader.class.getMethod("addDexPath",String.class).invoke(shared,runnerApplication.sourceDir);
            dalvik.system.BaseDexClassLoader.class.getMethod("addNativePath",java.util.Collection.class).invoke(shared,java.util.Collections.singletonList(runnerApplication.nativeLibraryDir));
            SdBridge.addBionicLibraryPath(runnerApplication.nativeLibraryDir);
            java.lang.reflect.Method load=android.app.ActivityThread.class.getDeclaredMethod("getPackageInfo",android.content.pm.ApplicationInfo.class,android.content.res.CompatibilityInfo.class,ClassLoader.class,boolean.class,boolean.class,boolean.class);load.setAccessible(true);
            runnerLoadedApk=(android.app.LoadedApk)load.invoke(thread,new android.content.pm.ApplicationInfo(runnerApplication),android.content.res.CompatibilityInfo.DEFAULT_COMPATIBILITY_INFO,shared,false,true,false);
        }
        Bundle args=new Bundle();JSONObject values=request.optJSONObject("arguments");
        if(values!=null)for(Iterator<String> it=values.keys();it.hasNext();){String key=it.next();args.putString(key,values.getString(key));}
        set(data,"instrumentationName",component);set(data,"instrumentationArgs",args);
        set(data,"instrumentationWatcher",new IInstrumentationWatcher.Stub(){
            public void instrumentationStatus(ComponentName name,int code,Bundle bundle){
                try{if(!component.equals(name))throw new SecurityException("Instrumentation watcher component mismatch");event("status",code,bundle);}catch(Exception failure){throw new IllegalStateException("Instrumentation status publication failed",failure);}
            }
            public void instrumentationFinished(ComponentName name,int code,Bundle bundle){
                try{if(!component.equals(name))throw new SecurityException("Instrumentation watcher component mismatch");event("finished",code,bundle);}catch(Exception failure){throw new IllegalStateException(failure);}
            }
        });
        System.err.println("SDINSTRUMENTATION=bound|component="+component.flattenToString()+"|target="+SdApkPackage.NAME);
    }
    public static synchronized void add(Bundle result){if(!requested()||finished)throw new IllegalStateException("No active instrumentation");if(result!=null)accumulated.putAll(result);}
    public static synchronized void finish(final int code,Bundle result)throws Exception{
        if(!requested()||finished)throw new IllegalStateException("No active instrumentation");finished=true;
        if(result!=null)accumulated.putAll(result);event("finished",code,accumulated);
        JSONObject value=new JSONObject();value.put("component",component.flattenToString());value.put("target",SdApkPackage.NAME);value.put("code",code);value.put("results",json(accumulated));value.put("pid",android.os.Process.myPid());value.put("run_id",request.getString("run_id"));
        File pending=new File(directory,"result.pending"),output=new File(directory,"result.json");
        try(FileOutputStream stream=new FileOutputStream(pending)){stream.write((value.toString(2)+"\n").getBytes("UTF-8"));stream.getFD().sync();}if(!pending.renameTo(output))throw new IOException("Cannot publish completed instrumentation result");
        System.err.println("SDINSTRUMENTATION=finished|code="+code+"|run="+request.getString("run_id"));
        // Android AMS ends an instrumentation-owned process after finish.
        new Handler(Looper.getMainLooper()).post(new Runnable(){public void run(){System.exit(0);}});
    }
}
