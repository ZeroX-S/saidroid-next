import android.app.AppOpsManager;
import android.os.*;
import com.android.internal.app.*;
import java.lang.reflect.*;
import java.util.*;
/** Playback operations and explicitly authorized camera, microphone and storage. */
public final class SdCameraAppOps implements InvocationHandler {
    private final Binder binder=new Binder();private final Set<IBinder> watchers=new HashSet<IBinder>();private final IAppOpsService service;
    private SdCameraAppOps(){service=(IAppOpsService)Proxy.newProxyInstance(IAppOpsService.class.getClassLoader(),new Class<?>[]{IAppOpsService.class},this);binder.attachInterface(service,"com.android.internal.app.IAppOpsService");}
    public static void install(){SdServiceManagerStub.put("appops",new SdCameraAppOps().binder);}
    private boolean owner(Object uid,Object pkg){return ((Integer)uid)==android.os.Process.myUid()&&SdApkPackage.NAME.equals(pkg);}
    private int mode(int operation,int uid,String packageName)throws Exception{
        if(!owner(uid,packageName))return AppOpsManager.MODE_ERRORED;
        if(operation==AppOpsManager.OP_PLAY_AUDIO)return AppOpsManager.MODE_ALLOWED;
        if(operation!=AppOpsManager.OP_CAMERA&&operation!=AppOpsManager.OP_RECORD_AUDIO&&operation!=AppOpsManager.OP_READ_EXTERNAL_STORAGE&&operation!=AppOpsManager.OP_WRITE_EXTERNAL_STORAGE)return AppOpsManager.MODE_IGNORED;
        String permission=AppOpsManager.opToPermission(operation);
        return permission!=null&&new SdAppPermissions(SdApkPackage.APK,SdApkPackage.NAME).holds(permission)?AppOpsManager.MODE_ALLOWED:AppOpsManager.MODE_IGNORED;
    }
    @Override public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String name=method.getName();if(name.equals("asBinder"))return binder;if(name.equals("toString"))return "SailDroid process-local playback operations";if(name.equals("hashCode"))return System.identityHashCode(proxy);if(name.equals("equals"))return proxy==args[0];
        if(name.equals("checkOperation")||name.equals("noteOperation"))return mode((Integer)args[0],(Integer)args[1],(String)args[2]);
        if(name.equals("checkPackage"))return owner(args[0],args[1])?AppOpsManager.MODE_ALLOWED:AppOpsManager.MODE_ERRORED;
        if(name.equals("permissionToOpCode"))return AppOpsManager.permissionToOpCode((String)args[0]);
        if(name.equals("noteProxyOperation")){
            if(!SdApkPackage.NAME.equals(args[1]))return AppOpsManager.MODE_ERRORED;
            return mode((Integer)args[0],(Integer)args[2],(String)args[3]);
        }
        if(name.equals("checkAudioOperation")){
            if ((Integer)args[0] == AppOpsManager.OP_RECORD_AUDIO) return mode((Integer)args[0], (Integer)args[2], (String)args[3]);
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
