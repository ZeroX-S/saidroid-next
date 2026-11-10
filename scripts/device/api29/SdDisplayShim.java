import android.hardware.display.DisplayManagerGlobal;
import android.hardware.display.IDisplayManager;
import android.hardware.display.IDisplayManagerCallback;
import android.view.DisplayInfo;
import android.os.Binder;
import android.os.IBinder;
import java.lang.reflect.*;
import java.util.*;

/** API 29 display service for the actual process-owned Wayland output. */
public final class SdDisplayShim {
    public static final int WIDTH=1080,HEIGHT=2160,DENSITY=420,DISPLAY_ID=0;
    private SdDisplayShim(){}
    public static DisplayInfo makeDisplayInfo(){
        DisplayInfo d=new DisplayInfo();d.name="SailDroid";d.uniqueId="saildroid:wayland";
        d.address=android.view.DisplayAddress.fromPhysicalDisplayId(0);
        d.appWidth=d.logicalWidth=d.smallestNominalAppWidth=d.largestNominalAppWidth=WIDTH;
        d.appHeight=d.logicalHeight=d.smallestNominalAppHeight=d.largestNominalAppHeight=HEIGHT;
        d.logicalDensityDpi=DENSITY;d.physicalXDpi=d.physicalYDpi=DENSITY;
        d.type=android.view.Display.TYPE_BUILT_IN;d.state=android.view.Display.STATE_ON;d.ownerUid=android.os.Process.myUid();
        d.supportedModes=new android.view.Display.Mode[]{new android.view.Display.Mode(1,WIDTH,HEIGHT,60.0f)};d.modeId=d.defaultModeId=1;
        d.supportedColorModes=new int[]{0};d.colorMode=0;d.appVsyncOffsetNanos=0;d.presentationDeadlineNanos=16666666L;return d;
    }
    public static final class LocalDisplayManager implements InvocationHandler {
        private final Binder binder=new Binder();private final IDisplayManager service;
        private final IdentityHashMap<IBinder,IDisplayManagerCallback> callbacks=new IdentityHashMap<IBinder,IDisplayManagerCallback>();
        public LocalDisplayManager(){service=(IDisplayManager)Proxy.newProxyInstance(IDisplayManager.class.getClassLoader(),new Class<?>[]{IDisplayManager.class},this);binder.attachInterface(service,"android.hardware.display.IDisplayManager");}
        public IBinder asBinder(){return binder;}public IDisplayManager service(){return service;}
        @Override public Object invoke(Object proxy,Method method,Object[] a){
            String n=method.getName();if(n.equals("asBinder"))return binder;if(n.equals("toString"))return "SailDroid Wayland display";if(n.equals("hashCode"))return System.identityHashCode(proxy);if(n.equals("equals"))return proxy==a[0];
            if(n.equals("getDisplayInfo"))return (Integer)a[0]==DISPLAY_ID?makeDisplayInfo():null;
            if(n.equals("getDisplayIds"))return new int[]{DISPLAY_ID};
            if(n.equals("registerCallback")){IDisplayManagerCallback callback=(IDisplayManagerCallback)a[0];callbacks.put(callback.asBinder(),callback);return null;}
            if(n.equals("getStableDisplaySize"))return new android.graphics.Point(WIDTH,HEIGHT);
            if(n.equals("isUidPresentOnDisplay"))return (Integer)a[0]==android.os.Process.myUid()&&(Integer)a[1]==DISPLAY_ID;
            if(n.equals("getPreferredWideGamutColorSpaceId"))return android.graphics.ColorSpace.Named.SRGB.ordinal();
            throw SdRuntimeDiagnostics.unsupported("Wayland display",method);
        }
    }
    private static final LocalDisplayManager local=new LocalDisplayManager();
    public static IBinder binder(){return local.asBinder();}
    public static String install()throws Exception{
        Constructor<DisplayManagerGlobal> constructor=DisplayManagerGlobal.class.getDeclaredConstructor(IDisplayManager.class);constructor.setAccessible(true);
        Field instance=DisplayManagerGlobal.class.getDeclaredField("sInstance");instance.setAccessible(true);instance.set(null,constructor.newInstance(local.service()));return "API29 display connected";
    }
    public static String installWindowManager()throws Exception{Field f=Class.forName("android.view.WindowManagerGlobal").getDeclaredField("sWindowManagerService");f.setAccessible(true);f.set(null,SdWindowManager.service());return "API29 window service connected";}
    public static String installPackageManager()throws Exception{Field f=Class.forName("android.app.ActivityThread").getDeclaredField("sPackageManager");f.setAccessible(true);f.set(null,SdPackageManagerService.service());return "API29 package service connected";}
}
