import org.saildroid.manager.SdAppRegistry;
import java.io.File;
import org.json.JSONObject;
/** VM-only end-to-end verification against the actual signed QQ APK. */
public final class Api29RegistryProbe {
    private static long owner(java.io.FileDescriptor descriptor)throws Exception{return (Long)java.io.FileDescriptor.class.getMethod("getOwnerId$").invoke(descriptor);}
    public static void main(String[] args)throws Exception{
        System.setProperty("saidroid.apps.directory",args[3]+"/apps");System.setProperty("saidroid.desktop.directory",args[3]+"/desktop");System.setProperty("saidroid.runtime.directory",args[3]+"/runtime");
        System.load(args[0]);if(!SdBridge.loadBionicLibrary(args[1]+"/libandroid_runtime.so",args[1])||SdBridge.registerFrameworkNatives()<1)throw new AssertionError("Native bootstrap failed");
        if(android.graphics.Typeface.DEFAULT==null)throw new AssertionError("No default font");
        android.os.Looper.prepareMainLooper();
        if(args.length>4&&args[4].equals("sample-lifecycle")){
            SdAppRegistry.Progress progress=new SdAppRegistry.Progress(){public void update(String message){}};
            JSONObject first=SdAppRegistry.install(new File(args[2]),progress);String name=first.getString("package");
            if(!name.equals("org.example.saildroid.inputprobe"))throw new AssertionError("Unexpected regression package");
            File launcher=new File(args[3]+"/apps/"+name+"/"+name);
            String desktop=new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(args[3]+"/desktop/"+SdAppRegistry.desktopId(name)+".desktop")),"UTF-8");
            File activation=new File(System.getenv("HOME"),".local/share/dbus-1/services/"+SdAppRegistry.desktopId(name)+".service");
            if(activation.exists()||!launcher.canExecute()||!desktop.contains("Exec="+launcher.getAbsolutePath()+" --desktop-token "+name+"\n"))throw new AssertionError("Distinct executable launcher missing");
            File sentinel=new File(first.getString("data"),"update-preserved");try(java.io.FileOutputStream output=new java.io.FileOutputStream(sentinel)){output.write(42);}
            JSONObject second=SdAppRegistry.install(new File(args[2]),progress);
            if(first.getString("apk").equals(second.getString("apk"))||!new File(first.getString("apk")).isFile()||!sentinel.isFile())throw new AssertionError("Update did not preserve previous version or data");
            File lockFile=new File(args[3]+"/runtime/"+name+".lock");
            try(java.io.RandomAccessFile lock=new java.io.RandomAccessFile(lockFile,"rw");java.nio.channels.FileLock held=lock.getChannel().lock()){
                boolean rejected=false;try{SdAppRegistry.uninstall(name);}catch(java.io.IOException expected){rejected=true;}
                if(!rejected||!sentinel.isFile())throw new AssertionError("Running-app lock did not protect uninstall");
            }
            SdAppRegistry.uninstall(name);
            if(!SdAppRegistry.installed().isEmpty()||sentinel.exists()||launcher.exists()||new File(args[3]+"/desktop/"+SdAppRegistry.desktopId(name)+".desktop").exists()||activation.exists())throw new AssertionError("Uninstall left package state");
            System.err.println("API29_REGISTRY=PASS|install=signed|launcher=distinct-executable|update=version-and-data-preserved|busy_uninstall=rejected|uninstall=removed");Runtime.getRuntime().halt(0);
        }
        if(args.length>4&&args[4].equals("services")){
            final java.util.concurrent.atomic.AtomicInteger changes=new java.util.concurrent.atomic.AtomicInteger();
            android.database.IContentObserver observer=new android.database.IContentObserver.Stub(){public void onChange(boolean self,android.net.Uri uri,int user){changes.incrementAndGet();}};
            android.content.IContentService content=SdContentService.service();int user=android.os.Process.myUid()/100000;
            android.net.Uri parent=android.net.Uri.parse("content://settings/global"),child=android.net.Uri.parse("content://settings/global/saildroid-test");
            content.registerContentObserver(parent,true,observer,user,29);
            content.notifyChange(child,null,false,0,user,29,"org.saildroid.manager");
            if(changes.get()!=1)throw new AssertionError("Descendant notification missing");
            content.notifyChange(child,observer,false,0,user,29,"org.saildroid.manager");
            if(changes.get()!=1)throw new AssertionError("Self notification should be excluded");
            content.unregisterContentObserver(observer);content.notifyChange(child,null,false,0,user,29,"org.saildroid.manager");
            if(changes.get()!=1)throw new AssertionError("Unregistered observer still notified");
            content.registerContentObserver(parent,false,observer,user,29);content.notifyChange(child,null,false,0,user,29,"org.saildroid.manager");
            if(changes.get()!=1)throw new AssertionError("Exact subscription received child notification");
            content.notifyChange(parent,null,false,0,user,29,"org.saildroid.manager");if(changes.get()!=2)throw new AssertionError("Exact notification missing");
            boolean rejected=false;try{content.registerContentObserver(parent,true,observer,user+99,29);}catch(SecurityException expected){rejected=true;}if(!rejected)throw new AssertionError("Cross-user subscription accepted");
            rejected=false;try{android.os.Debug.getUnreachableMemory(10,false);}catch(UnsupportedOperationException expected){rejected=true;}if(!rejected)throw new AssertionError("Unavailable heap walk reported success");
            File sample=new File(args[3],"fd-owner-test");try(java.io.FileOutputStream output=new java.io.FileOutputStream(sample)){output.write(42);}
            android.os.ParcelFileDescriptor descriptor=android.os.ParcelFileDescriptor.open(sample,android.os.ParcelFileDescriptor.MODE_READ_ONLY);
            if(owner(descriptor.getFileDescriptor())==0)throw new AssertionError("Parcel descriptor has no owner");
            int raw=descriptor.detachFd();android.os.ParcelFileDescriptor adopted=android.os.ParcelFileDescriptor.adoptFd(raw);
            java.io.FileDescriptor original=adopted.getFileDescriptor();
            try(java.io.InputStream input=new android.os.ParcelFileDescriptor.AutoCloseInputStream(adopted)){if(input.read()!=42)throw new AssertionError("Transferred descriptor lost its file");}
            if(original.valid()||owner(original)!=0)throw new AssertionError("Closed descriptor retained ownership");
            System.err.println("API29_SERVICES=PASS|observer_delivery=2|self=excluded|unregister=verified|cross_user=rejected|heap_walk=unsupported|pfd=transfer-read-close");Runtime.getRuntime().halt(0);
        }
        if(args.length>4&&args[4].equals("stats")){
            int status=android.util.StatsLogInternal.write(177,"org.saildroid.manager",1);
            System.err.println("API29_GESTURE_STATS=PASS|transport_status="+status);Runtime.getRuntime().halt(0);
        }
        if(args.length>4&&args[4].equals("uninstall")){
            SdAppRegistry.uninstall("com.tencent.mobileqq");if(!SdAppRegistry.installed().isEmpty())throw new AssertionError("Uninstall left an installed record");
            if(new File(args[3]+"/desktop/"+SdAppRegistry.desktopId("com.tencent.mobileqq")+".desktop").exists())throw new AssertionError("Uninstall left a desktop entry");
            System.err.println("API29_UNINSTALL=PASS|records=0|desktop=false");Runtime.getRuntime().halt(0);
        }
        JSONObject record=SdAppRegistry.install(new File(args[2]),new SdAppRegistry.Progress(){public void update(String text){System.err.println("REGISTRY_PROGRESS="+text);}});
        if(!"com.tencent.mobileqq".equals(record.getString("package")))throw new AssertionError("Wrong package");
        if(record.getJSONArray("signers").length()==0||record.isNull("launchActivity"))throw new AssertionError("Missing real signer or launcher");
        File icon=new File(record.getString("icon"));android.graphics.Bitmap bitmap=android.graphics.BitmapFactory.decodeFile(icon.getPath());
        if(bitmap==null||bitmap.getWidth()!=128||bitmap.getHeight()!=128)throw new AssertionError("Real APK icon was not decoded");bitmap.recycle();
        if(!new File(args[3]+"/desktop/"+SdAppRegistry.desktopId("com.tencent.mobileqq")+".desktop").isFile()||SdAppRegistry.installed().size()!=1)throw new AssertionError("Installation catalog or desktop differs");
        System.err.println("API29_INSTALL=PASS|package="+record.getString("package")+"|label="+record.getString("label")+"|version="+record.optString("versionName")+"|launcher="+record.getString("launchActivity"));
        Runtime.getRuntime().halt(0);
    }
}
