import android.app.AppOpsManager;
import android.os.*;
import com.android.internal.app.*;
import java.lang.reflect.*;
import java.util.*;
/** Process-local PLAY_AUDIO policy for the implemented PulseAudio playback path. */
public final class SdCameraAppOps implements InvocationHandler {
    private final Binder binder=new Binder();private final Set<IBinder> watchers=new HashSet<IBinder>();private final IAppOpsService service;
    private SdCameraAppOps(){service=(IAppOpsService)Proxy.newProxyInstance(IAppOpsService.class.getClassLoader(),new Class<?>[]{IAppOpsService.class},this);binder.attachInterface(service,"com.android.internal.app.IAppOpsService");}
    public static void install(){SdServiceManagerStub.put("appops",new SdCameraAppOps().binder);}
    private boolean owner(Object uid,Object pkg){return ((Integer)uid)==android.os.Process.myUid()&&SdApkPackage.NAME.equals(pkg);}
    @Override public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String name=method.getName();if(name.equals("asBinder"))return binder;if(name.equals("toString"))return "SailDroid process-local playback operations";if(name.equals("hashCode"))return System.identityHashCode(proxy);if(name.equals("equals"))return proxy==args[0];
        if(name.equals("checkAudioOperation")){
            if(((Integer)args[0])!=AppOpsManager.OP_PLAY_AUDIO)throw SdRuntimeDiagnostics.unsupported("Camera playback operation",method);
            int mode=owner(args[2],args[3])?AppOpsManager.MODE_ALLOWED:AppOpsManager.MODE_ERRORED;
            System.err.println("SDCAMERA=play_audio_policy|mode="+mode+"|backend=pulseaudio|scope=bound-application");return mode;
        }
        if(name.equals("startWatchingMode")){
            if(((Integer)args[0])!=AppOpsManager.OP_PLAY_AUDIO||!SdApkPackage.NAME.equals(args[1]))throw new SecurityException("Unsupported operation watch owner");
            IAppOpsCallback callback=(IAppOpsCallback)args[2];if(callback==null)throw new NullPointerException("Operation callback required");watchers.add(callback.asBinder());return null;
        }
        if(name.equals("stopWatchingMode")){if(args[0]!=null)watchers.remove(((IAppOpsCallback)args[0]).asBinder());return null;}
        throw SdRuntimeDiagnostics.unsupported("Application operations",method);
    }
}
