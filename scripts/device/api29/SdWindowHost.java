import android.os.Handler;
import android.os.Looper;
import android.os.Message;

/** Process-owned Wayland host. Shell events never wait for Android lifecycle work. */
public final class SdWindowHost {
    private static Handler main;
    private static boolean installed,started;
    private static volatile long focusSerial;
    private static volatile boolean focused;
    private static native void nativeInstall();
    private static native boolean nativeStart(String title,String appId,int width,int height);
    private static native void nativeRequestFrame();
    private static native void nativePresent(int[] pixels,int width,int height);
    private static native void nativeStop();
    private static native void nativeCoverFrame(int[] pixels,int width,int height);
    private static native int nativeClientHeight();
    private static native void nativeHardwareInitialize();
    public static native long nativeHardwareRetain(long pointer);
    public static native void nativeHardwareZ(long pointer,int z);
    public static native void nativeHardwareLayout(long pointer,int x,int y,int width,int height,boolean visible);
    private static boolean hardwareSelected="1".equals(System.getenv("SAILDROID_HWUI"));
    private static native void nativeSelectHardware(boolean enabled);
    public static boolean hardware(){return hardwareSelected;}
    public static void appOptedOutOfHardware(){
        if(installed)throw new IllegalStateException("Window backend has already been selected");
        if(hardwareSelected)System.err.println("SDHWUI=app_opt_out|selected=software-wayland");
        hardwareSelected=false;
    }
    public static native long nativeHardwareSurface(int id,int width,int height);
    public static native void nativeHardwareRelease(long pointer);
    public static synchronized void install(String library) {
        if(installed)return;
        System.load(library);nativeSelectHardware(hardwareSelected);nativeInstall();if(hardware()){nativeHardwareInitialize();SdTexture.install();}installed=true;
    }
    public static synchronized void start(String title,String appId) {
        if(started)return;
        if(!installed)throw new IllegalStateException("Window native backend is not installed");
        android.text.Hyphenator.init();
        main=new Handler(Looper.getMainLooper());
        if(!nativeStart(title,appId,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT)) {
            throw new IllegalStateException("Wayland window could not be created");
        }
        started=true;
    }
    public static void requestFrame(){if(!started)throw new IllegalStateException("Wayland host is not running");nativeRequestFrame();}
    public static boolean isStarted(){return started;}
    public static int clientHeight(){return started?nativeClientHeight():SdDisplayShim.HEIGHT;}
    public static void present(int[] pixels){if(!started)throw new IllegalStateException("Wayland host is not running");nativePresent(pixels,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT);}
    /** Direct path: a ByteBuffer over the spare wl_shm buffer, or null when the
        direct copy is off or both buffers are busy. */
    public static java.nio.ByteBuffer directAcquire(){if(!started)throw new IllegalStateException("Wayland host is not running");return nativeDirectAcquire();}
    public static boolean directCommit(){if(!started)return false;return nativeDirectCommit();}
    private static native java.nio.ByteBuffer nativeDirectAcquire();
    private static native boolean nativeDirectCommit();
    public static void stop(){if(started){nativeStop();started=false;}}
    private static void postEvent(Runnable callback){Message event=Message.obtain(main,callback);event.setAsynchronous(true);main.sendMessage(event);}
    private static void onNativeFrame(long timestamp){SdDisplayFrames.onFrame(timestamp);}
    private static void onNativeInput(final int action,final int id,final float x,final float y,final long timestamp){
        postEvent(new Runnable(){@Override public void run(){SdWindowSession.input(action,id,x,y,timestamp);}});
    }
    private static void onNativeFocus(final boolean value){
        focused=value;final long serial=++focusSerial;
        postEvent(new Runnable(){@Override public void run(){if(serial==focusSerial)dispatchCoverFocus(serial,focused);}});
    }
    private static void onNativeVisibility(final int value){postEvent(new Runnable(){public void run(){SdWindowSession.visibility(value);}});}
    private static boolean onNativeOpenUri(final String value){
        if(!"org.saildroid.manager".equals(SdApkPackage.NAME))return false;
        final android.net.Uri uri=android.net.Uri.parse(value);
        if(!"file".equals(uri.getScheme())||uri.getAuthority()!=null&&!uri.getAuthority().isEmpty())return false;
        postEvent(new Runnable(){public void run(){SdActivityHost.openInstallerFile(uri);}});return true;
    }
    private static void onNativeClosed(){if(main!=null)postEvent(new Runnable(){@Override public void run(){
        System.err.println("SDWINDOW=closed");SdActivityHost.closeTask();
    }});}
    private static boolean coverFocused;
    private static void dispatchCoverFocus(final long serial,boolean active){
        final SdCoverSnapshot.Frame cover=coverFocused&&!active&&hardware()?SdCoverSnapshot.capture():null;
        coverFocused=active;
        SdWindowSession.focus(active);
        if(cover!=null)main.postDelayed(new Runnable(){public void run(){
            if(serial==focusSerial&&!focused)nativeCoverFrame(cover.pixels,cover.width,cover.height);
        }},180);
    }
}
