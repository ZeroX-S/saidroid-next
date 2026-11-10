import android.os.*;
import java.lang.reflect.*;

/** Host display/saver queries. No Android wake-lock or sleep-control backend is advertised. */
public final class SdPower implements InvocationHandler {
    private static final SdPower instance=new SdPower();
    private final Binder binder=new Binder();private final IPowerManager service;
    private SdPower(){service=(IPowerManager)Proxy.newProxyInstance(IPowerManager.class.getClassLoader(),new Class<?>[]{IPowerManager.class},this);binder.attachInterface(service,"android.os.IPowerManager");}
    public static IBinder binder(){return instance.binder;}
    public static boolean interactive(){String state=SdHostState.string("get_display_status");if(state.equals("on")||state.equals("dim")||state.equals("power up"))return true;if(state.equals("off")||state.equals("lpm_on")||state.equals("lpm_off")||state.equals("power down"))return false;throw new IllegalStateException("Unknown MCE display state: "+state);}
    public static boolean powerSave(){return SdHostState.bool("get_psm_state");}
    @Override public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String name=method.getName();if(name.equals("asBinder"))return binder;if(name.equals("toString"))return "Sailfish display and power state";if(name.equals("hashCode"))return System.identityHashCode(proxy);if(name.equals("equals"))return proxy==args[0];
        if(name.equals("isInteractive"))return interactive();
        if(name.equals("isPowerSaveMode"))return powerSave();
        if(name.equals("getPowerSaveState"))return new PowerSaveState.Builder().setGlobalBatterySaverEnabled(powerSave()).setBatterySaverEnabled(false).build();
        if(name.equals("isWakeLockLevelSupported"))return false;
        if(name.equals("isDeviceIdleMode")||name.equals("isLightDeviceIdleMode"))return false; // This runtime owns no Android Doze policy engine.
        throw SdRuntimeDiagnostics.unsupported("Host power service",method);
    }
}
