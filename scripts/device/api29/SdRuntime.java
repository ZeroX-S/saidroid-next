import android.app.ActivityThread;
import android.content.pm.ApplicationInfo;
import android.content.pm.ProviderInfo;
import android.content.res.CompatibilityInfo;
import android.content.res.Configuration;
import android.os.Bundle;
import android.os.Looper;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;

/** Product entry point: bind the real installed app, then run its main Activity. */
public final class SdRuntime {
    public static void ensureUiHost(){
        if(SdWindowHost.isStarted())return;
        SdRuntimeControl.stop();
        SdWindowHost.install(System.getProperty("saidroid.window.library",System.getenv("ANDROID_ROOT")+"/lib/libsdwindow.so"));
        SdWindowHost.start(SdApkPackage.NAME,"org.saildroid.app.p"+packageHash());
        org.saildroid.host.HostApi.activateSelf();
    }
    private static String packageHash(){
        try{byte[] value=java.security.MessageDigest.getInstance("SHA-256").digest(SdApkPackage.NAME.getBytes("UTF-8"));StringBuilder out=new StringBuilder();for(int i=0;i<10;i++)out.append(String.format(java.util.Locale.US,"%02x",value[i]&255));return out.toString();}
        catch(Exception failure){throw new IllegalStateException(failure);}
    }
    private static void set(Object object,String name,Object value)throws Exception{Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);field.set(object,value);}
    public static void initializeFramework(boolean application)throws Exception{
        System.load(System.getProperty("saidroid.bridge.library","/home/art/lib/libsdbridge.so"));
        String nativeRuntime=System.getProperty("saidroid.native.runtime",System.getenv("ANDROID_ROOT")+"/android-libs");
        if(!SdBridge.loadBionicLibrary(nativeRuntime+"/libandroid_runtime.so",nativeRuntime))throw new IllegalStateException("Android native bootstrap failed");
        SdCryptoProvider.install();
        SdWebViewProvider.install();
        String driver=System.getProperty("saidroid.binder.driver");
        if(driver!=null&&!SdBridge.configurePrivateBinder(driver))throw new IllegalStateException("Private Binder setup failed");
        if(SdBridge.registerFrameworkNatives()<1)throw new IllegalStateException("Android native registration failed");if(application)selectHeadlessChoreographer();
        SdTls.install();
        if(application){
        if(!SdBridge.installClassLoaderNamespaces())throw new IllegalStateException("Application native namespace backend unavailable");
        SdClassLoaderNamespaces.installNativePathListener();
        if(!SdBridge.installGraphicsEnvironment())throw new IllegalStateException("Graphics configuration backend unavailable");
        }
        if(Boolean.getBoolean("saidroid.vmExitDiagnostics")){SdBridge.installExitDiagnostics();SdRuntimeDiagnostics.captureUncaught();}
        if(android.graphics.Typeface.DEFAULT==null)throw new IllegalStateException("Android system font map unavailable");
        if(android.os.Build.VERSION.SDK_INT!=29)throw new IllegalStateException("SailDroid requires its actual API 29 framework");
        // Public hardware fields share the immutable component property source.
        // Capture the framework values before any application code is loaded.
        System.err.println("SDHARDWARE=framework|manufacturer="+android.os.Build.MANUFACTURER
            +"|brand="+android.os.Build.BRAND+"|model="+android.os.Build.MODEL
            +"|product="+android.os.Build.PRODUCT+"|device="+android.os.Build.DEVICE);
    }
    public static void main(String[] args){
        try{
            SdStartup.phase("framework_start");initializeFramework(true);SdStartup.phase("framework_ready");
            SdAudio.install();SdServices.installAll();Looper.prepareMainLooper();SdStartup.phase("services_ready");
            SdStartup.phase("apk_metadata_start");
            int targetSdk=SdApkPackage.applicationInfo().targetSdkVersion;
            if(targetSdk<1)throw new IllegalStateException("APK target SDK is invalid");
            // Android normally sets this during process/application binding.
            // Set it before loading any APK code: this setter updates both
            // libcore's Java state and ART's native hidden-API target policy.
            dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(targetSdk);
            if(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion()!=targetSdk)
                throw new IllegalStateException("ART target SDK did not match the real APK");
            System.err.println("SDRUNTIME=sdk_policy|target="+targetSdk+"|source=parsed-apk-manifest|before_apk_classloader=true");
            boolean debuggable=(SdApkPackage.applicationInfo().flags&ApplicationInfo.FLAG_DEBUGGABLE)!=0;
            if(debuggable!=Boolean.getBoolean("saidroid.package.debuggable")||debuggable!=dalvik.system.VMRuntime.getRuntime().isJavaDebuggable())
                throw new SecurityException("Runtime debugging policy differs from actual APK manifest; refresh installed metadata");
            if((SdApkPackage.applicationInfo().flags&ApplicationInfo.FLAG_HARDWARE_ACCELERATED)==0)
                SdWindowHost.appOptedOutOfHardware();
            if(SdWindowHost.hardware()){
                android.graphics.HardwareRenderer.setIsolatedProcess(true);
                System.err.println("SDHWUI=enabled|pipeline=android-hwui-gles-wayland|cpu_readback=0");
            }else android.view.ThreadedRenderer.disable(true);
            SdStartup.phase("apk_metadata_ready");
            // Publish Android's actual process identity before the Wayland
            // surface maps, so Sailfish can merge its cold-start Cover too.
            android.os.Process.setArgV0(SdApkPackage.processName());
            boolean serviceProcess=System.getProperty("saidroid.service")!=null||System.getProperty("saidroid.activity")!=null||System.getProperty("saidroid.provider")!=null||System.getProperty("saidroid.receiver")!=null;
            if(SdKernelServices.enabled())SdBridge.startBinderPool();
            if(!serviceProcess&&!SdInstrumentation.requested()){SdWindowHost.install(System.getProperty("saidroid.window.library",System.getenv("ANDROID_ROOT")+"/lib/libsdwindow.so"));String desktopId=System.getenv("SAILDROID_DESKTOP_ID");SdWindowHost.start(SdApkPackage.NAME,desktopId!=null?desktopId:"saildroid-"+SdApkPackage.NAME);}
            // This is an application process. systemMain() initializes Android's
            // system-process renderer and is not its application attach path.
            Constructor<ActivityThread> threadConstructor=ActivityThread.class.getDeclaredConstructor();threadConstructor.setAccessible(true);
            ActivityThread thread=threadConstructor.newInstance();
            Method attach=ActivityThread.class.getDeclaredMethod("attach",boolean.class,long.class);attach.setAccessible(true);attach.invoke(thread,false,0L);SdStartup.phase("thread_attached");
            System.err.println("SDRUNTIME=application_thread_attached");
            if(Boolean.getBoolean("saidroid.vmDiagnostics"))System.err.println("VM_CODE_MAPS_START\n"+new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get("/proc/self/maps")),"UTF-8")+"VM_CODE_MAPS_END");
            Configuration hostConfiguration=SdActivityHost.displayConfiguration();
            android.util.DisplayMetrics metrics=new android.util.DisplayMetrics();metrics.setToDefaults();
            metrics.widthPixels=SdDisplayShim.WIDTH;metrics.heightPixels=SdDisplayShim.HEIGHT;metrics.densityDpi=SdDisplayShim.DENSITY;metrics.density=metrics.scaledDensity=SdDisplayShim.DENSITY/160f;metrics.xdpi=metrics.ydpi=SdDisplayShim.DENSITY;
            android.content.res.Resources.getSystem().updateConfiguration(hostConfiguration,metrics);
            ApplicationInfo app=SdApkPackage.applicationInfo();SdServices.bindApplication(app);
            android.app.LoadedApk loaded=thread.getPackageInfoNoCheck(app,CompatibilityInfo.DEFAULT_COMPATIBILITY_INFO);
            SdBridge.addBionicLibraryPath(app.nativeLibraryDir);
            SdClassLoaderNamespaces.registerApplicationCodeCache(app);
            SdStartup.phase("apk_classloader_start");ClassLoader loader=loaded.getClassLoader();SdStartup.phase("apk_classloader_ready");
            // Application native libraries initialize from their own declaring classes.
            // Do not preload app-specific libraries through Runtime's legacy loader API.
            Class<?> binding=Class.forName("android.app.ActivityThread$AppBindData");
            Constructor<?> constructor=binding.getDeclaredConstructor();constructor.setAccessible(true);Object data=constructor.newInstance();
            set(data,"appInfo",app);set(data,"info",loaded);set(data,"processName",SdApkPackage.processName());set(data,"compatInfo",CompatibilityInfo.DEFAULT_COMPATIBILITY_INFO);
            set(data,"config",hostConfiguration);
            ArrayList<ProviderInfo> providers=new ArrayList<ProviderInfo>();
            for(android.content.pm.PackageParser.Provider provider:SdApkPackage.parsed().providers){
                String process=SdApkPackage.providerProcess(provider.info);if(!process.equals(SdApkPackage.processName()))continue;
                ProviderInfo info=new ProviderInfo(provider.info);info.processName=process;info.applicationInfo=app;info.metaData=provider.metaData;providers.add(info);
            }
            set(data,"providers",providers);
            if(SdInstrumentation.requested())SdInstrumentation.bind(data);
            if(SdInstrumentation.requested())SdRuntimeControl.start();
            if(serviceProcess){if(!SdKernelServices.enabled())throw new IllegalStateException("Secondary service process requires private Binder");SdRuntimeControl.start();}
            if(SdKernelServices.enabled())SdServiceEndpoint.publish();
            Field core=ActivityThread.class.getDeclaredField("mCoreSettings");core.setAccessible(true);core.set(thread,new Bundle());
            Method bind=ActivityThread.class.getDeclaredMethod("handleBindApplication",binding);bind.setAccessible(true);SdStartup.phase("application_bind_start");bind.invoke(thread,data);SdStartup.phase("application_bind_ready");
            System.err.println("SDRUNTIME=application_ready|package="+app.packageName);
            if(serviceProcess){org.saildroid.host.HostApi.ready();System.err.println("SDRUNTIME=service_process_ready|process="+SdApkPackage.processName()+"|pid="+android.os.Process.myPid());Looper.loop();return;}
            if(SdInstrumentation.requested()){org.saildroid.host.HostApi.ready();System.err.println("SDINSTRUMENTATION=running|target="+app.packageName);Looper.loop();return;}
            SdActivityHost.launchMainActivity(app.sourceDir);
            System.err.println("SDRUNTIME=activity_queued|package="+app.packageName);
            final String capture=System.getProperty("saidroid.capture.path");
            if(capture!=null)new android.os.Handler(Looper.getMainLooper()).postDelayed(new Runnable(){public void run(){
                try{SdSurfaceStore.saveSnapshot(capture);System.err.println("SDCAPTURE=saved");}
                catch(Exception failure){System.err.println("SDCAPTURE=failed|type="+failure.getClass().getName());}
            }},1500);
            Looper.loop();
        }catch(Throwable failure){while(failure.getCause()!=null)failure=failure.getCause();failure.printStackTrace();
            /* 崩在框架里（例如测量阶段读到 null LayoutParams）时，栈里只有框架类名，
               定位不到是哪个子 View。halt(10) 之前把整棵 View 树打出来，这是唯一
               还没丢掉现场的时刻。2026-10-27 QQBrowserActivity 的 MarginLayoutParams NPE 就靠这个。 */
            try{SdViewDump.dump();}catch(Throwable ignored){}
            System.err.println("SDRUNTIME=failed|type="+failure.getClass().getName());Runtime.getRuntime().halt(10);}
    }
    private static void selectHeadlessChoreographer()throws Exception{
        if((System.getProperty("saidroid.service")==null&&System.getProperty("saidroid.provider")==null)
                ||System.getProperty("saidroid.activity")!=null||System.getProperty("saidroid.receiver")!=null
                ||System.getProperty("saidroid.instrumentation.request")!=null)return;
        android.os.SystemProperties.set("debug.choreographer.vsync","false");
        if(android.os.SystemProperties.getBoolean("debug.choreographer.vsync",true))
            throw new IllegalStateException("Headless Choreographer property selection failed");
        Class<?> type=Class.forName("android.view.Choreographer");
        Field flag=type.getDeclaredField("USE_VSYNC");flag.setAccessible(true);
        if(flag.getBoolean(null))throw new IllegalStateException("Headless Choreographer was already initialized with vsync");
        System.err.println("SDCHOREOGRAPHER=non-vsync|scope=process-lifetime|origin=service-provider|source=android-handler|presentation=false");
    }
}
