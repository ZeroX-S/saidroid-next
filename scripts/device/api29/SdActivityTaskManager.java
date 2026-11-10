import android.app.IActivityTaskManager;
import android.content.Intent;
import android.os.*;
import java.lang.reflect.*;

/** API 29 task endpoint for the actual Activity stack in this host window. */
public final class SdActivityTaskManager implements InvocationHandler {
    private static final SdActivityTaskManager instance=new SdActivityTaskManager();
    private final Binder binder=new Binder();private final IActivityTaskManager service;
    private SdActivityTaskManager(){service=(IActivityTaskManager)Proxy.newProxyInstance(IActivityTaskManager.class.getClassLoader(),new Class<?>[]{IActivityTaskManager.class},this);binder.attachInterface(service,"android.app.IActivityTaskManager");}
    public static IBinder binder(){return instance.binder;}
    @Override public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String n=method.getName();if(n.equals("asBinder"))return binder;if(n.equals("toString"))return "SailDroid Activity tasks";if(n.equals("hashCode"))return System.identityHashCode(proxy);if(n.equals("equals"))return proxy==args[0];
        if(n.equals("startActivity")||n.equals("startActivityAsUser")){
            Intent selected=null;for(Object a:args)if(a instanceof Intent){selected=new Intent((Intent)a);break;}
            if(selected==null)throw new IllegalArgumentException("Activity Intent required");
            SdActivityHost.requestStart(selected,(IBinder)args[4],(String)args[5],(Integer)args[6]);return android.app.ActivityManager.START_SUCCESS;
        }
        if(n.equals("finishActivity"))return SdActivityHost.requestFinish((IBinder)args[0],(Integer)args[1],(Intent)args[2]);
        if(n.equals("getTaskForActivity")){
            IBinder token=(IBinder)args[0];SdActivityHost.requireActivity(token);
            if(Boolean.TRUE.equals(args[1])&&!SdActivityHost.isRoot(token))return -1;
            return SdServices.activityManager().invoke(proxy,method,args);
        }
        if(n.equals("onBackPressedOnTaskRoot")){
            SdActivityHost.requireActivity((IBinder)args[0]);
            android.app.IRequestFinishCallback callback=(android.app.IRequestFinishCallback)args[1];
            if(callback==null)throw new NullPointerException("Finish callback required");
            // This host has no floating single-task SystemUI container to intercept Back.
            callback.requestFinish();
            System.err.println("SDACTIVITY=back_finish_callback|delivered=true|scope=hosted-task");return null;
        }
        if(n.equals("finishSubActivity")){SdActivityHost.requestFinishSubActivities((IBinder)args[0],(String)args[1],(Integer)args[2]);return null;}
        if(n.equals("getDeviceConfigurationInfo")){
            android.content.res.Configuration current=SdActivityHost.displayConfiguration();
            android.content.pm.ConfigurationInfo info=new android.content.pm.ConfigurationInfo();info.reqTouchScreen=current.touchscreen;info.reqKeyboardType=current.keyboard;info.reqNavigation=current.navigation;
            info.reqGlEsVersion=android.os.SystemProperties.getInt("ro.opengles.version",0);return info;
        }
        if(n.equals("isTopOfTask"))return SdActivityHost.isTop((IBinder)args[0]);
        if(n.equals("setRequestedOrientation")){SdActivityHost.requestOrientation((IBinder)args[0],(Integer)args[1]);return null;}
        if(n.equals("getRequestedOrientation"))return SdActivityHost.requestedOrientation((IBinder)args[0]);
        if(n.equals("overridePendingTransition")){
            SdActivityHost.requireActivity((IBinder)args[0]);if(!SdApkPackage.NAME.equals(args[1]))throw new SecurityException("Transition owner differs");
            // Animation is a window presentation preference, not permission to
            // start the next Activity. The native host owns its transition;
            // Android resource animations are therefore disabled for this host.
            System.err.println("SDACTIVITY=transition_requested|enter="+args[2]+"|exit="+args[3]+"|animation=disabled-by-host-policy");return null;
        }
        if(n.equals("isInMultiWindowMode")||n.equals("isInPictureInPictureMode")){SdActivityHost.requireActivity((IBinder)args[0]);return false;}
        if(n.equals("isActivityStartAllowedOnDisplay"))return (Integer)args[0]==SdDisplayShim.DISPLAY_ID;
        if(n.equals("getLaunchedFromUid")){SdActivityHost.requireActivity((IBinder)args[0]);return android.os.Process.myUid();}
        if(n.equals("getLaunchedFromPackage")){SdActivityHost.requireActivity((IBinder)args[0]);return SdApkPackage.NAME;}
        if(n.equals("getActivityClassForToken"))return SdActivityHost.component((IBinder)args[0]);
        return SdServices.activityManager().invoke(proxy,method,args);
    }
}
