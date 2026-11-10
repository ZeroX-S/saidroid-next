import android.os.Binder;
import android.os.IBinder;
import android.view.IWindowManager;
import android.graphics.Point;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

/** Window manager for the process's one Wayland display and local window session. */
public final class SdWindowManager implements InvocationHandler {
    private static final SdWindowManager instance=new SdWindowManager();
    private final Binder binder=new Binder();
    private final IWindowManager service;
    private SdWindowManager(){service=(IWindowManager)Proxy.newProxyInstance(IWindowManager.class.getClassLoader(),new Class<?>[]{IWindowManager.class},this);binder.attachInterface(service,"android.view.IWindowManager");}
    public static IWindowManager service(){return instance.service;}
    public static IBinder binder(){return instance.binder;}
    @Override public Object invoke(Object p,Method m,Object[] a)throws Throwable{
        String name=m.getName();
        if(name.equals("asBinder"))return binder;
        if(name.equals("toString"))return "SailDroid local WindowManager";
        if(name.equals("hashCode"))return System.identityHashCode(p);
        if(name.equals("equals"))return p==a[0];
        if(name.equals("openSession")){
            ((android.view.IWindowSessionCallback)a[0]).onAnimatorScaleChanged(1.0f);
            return SdWindowSession.service();
        }
        if(name.equals("getInitialDisplaySize")||name.equals("getBaseDisplaySize")){
            if((Integer)a[0]!=SdDisplayShim.DISPLAY_ID)throw new IllegalArgumentException("Unknown display");
            ((Point)a[1]).set(SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT);return null;
        }
        if(name.equals("getInitialDisplayDensity")||name.equals("getBaseDisplayDensity"))return SdDisplayShim.DENSITY;
        if(name.equals("setInTouchMode")){SdWindowSession.setInTouchMode((Boolean)a[0]);return null;}
        if(name.equals("getCurrentAnimatorScale"))return 1.0f;
        if(name.equals("getAnimationScale"))return 1.0f;
        if(name.equals("getAnimationScales"))return new float[]{1,1,1};
        if(name.equals("hasNavigationBar"))return false; // Host gestures are outside the Android client area.
        if(name.equals("isSafeModeEnabled"))return false;
        if(name.equals("isKeyguardLocked")||name.equals("inKeyguardRestrictedInputMode"))return SdKeyguard.locked();
        if(name.equals("getRotation"))return android.view.Surface.ROTATION_0;
        throw SdRuntimeDiagnostics.unsupported("Local WindowManager",m);
    }
}
