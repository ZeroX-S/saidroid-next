import android.media.*;
import android.os.*;
import java.lang.reflect.*;
import java.util.*;
import org.json.*;

/** Query the running host audio server; Android playback/mixing remains separate. */
public final class SdAudio implements InvocationHandler {
    private final Binder binder=new Binder();
    private final IAudioService service;
    private static final SdAudio instance=new SdAudio();
    private static JSONObject snapshot;private static long sampled;private static volatile int portGeneration=1;
    private static native void nativeInstall();
    private SdAudio(){service=(IAudioService)Proxy.newProxyInstance(IAudioService.class.getClassLoader(),new Class<?>[]{IAudioService.class},this);binder.attachInterface(service,"android.media.IAudioService");}
    public static IBinder binder(){return instance.binder;}
    public static void install(){System.load(System.getenv("ANDROID_ROOT")+"/lib/libsdhostapi.so");nativeInstall();}
    private static synchronized JSONObject snapshot()throws Exception{
        long now=SystemClock.uptimeMillis();if(snapshot==null||now-sampled>250){snapshot=new JSONObject(org.saildroid.host.HostApi.audioSnapshot());sampled=now;}return snapshot;
    }
    private static JSONObject output()throws Exception{
        JSONArray outputs=snapshot().getJSONArray("outputs");for(int i=0;i<outputs.length();i++)if(outputs.getJSONObject(i).getBoolean("default"))return outputs.getJSONObject(i);throw new IllegalStateException("Host default audio output unavailable");
    }
    public static int primaryOutputSamplingRate()throws Exception{
        int rate=output().getInt("rate");
        if(rate<=0)throw new IllegalStateException("Host default output has no sampling rate");
        System.err.println("SDAUDIO=primary_output_rate|hz="+rate+"|source=pulseaudio-default-sink");
        return rate;
    }
    public static int primaryOutputFrameCount(){
        System.err.println("SDAUDIO=primary_output_frames|value=unavailable|android_property=null");
        return 0;
    }
    static int volume()throws Exception{return output().getBoolean("muted")?0:Math.max(0,Math.min(100,(int)Math.round(output().getDouble("volume")*100)));}
    public static boolean bluetoothScoRoute(JSONObject output)throws Exception{
        String api=output.getString("device_api");
        String protocol=output.getString("bluetooth_protocol").toLowerCase(Locale.ROOT);
        String profile=output.getString("bluez5_profile").toLowerCase(Locale.ROOT);
        boolean bluetooth=api.equals("bluez")||api.equals("bluez5");
        boolean sco=protocol.equals("sco")||protocol.equals("headset_head_unit")
                ||protocol.equals("handsfree_head_unit")||protocol.equals("headset_audio_gateway")
                ||protocol.equals("handsfree_audio_gateway")||protocol.equals("hsp")||protocol.equals("hfp");
        sco=sco||profile.equals("headset-head-unit")||profile.equals("handsfree-head-unit")
                ||profile.equals("headset-audio-gateway")||profile.equals("handsfree-audio-gateway")
                ||profile.equals("hsp_hs")||profile.equals("hfp_hf")||profile.equals("hsp_ag")||profile.equals("hfp_ag");
        return bluetooth&&sco;
    }
    public static boolean bluetoothScoOn()throws Exception{
        JSONObject route=output();boolean on=bluetoothScoRoute(route);
        System.err.println("SDAUDIO=bluetooth_sco|on="+on+"|source=pulseaudio-default-sink");
        return on;
    }
    public static boolean streamActive(int stream,int lookback)throws Exception{
        JSONArray outputs=snapshot().getJSONArray("outputs");for(int i=0;i<outputs.length();i++)if(outputs.getJSONObject(i).getBoolean("active"))return true;return false;
    }
    public static boolean microphoneMuted()throws Exception{
        JSONArray inputs=snapshot().getJSONArray("inputs");for(int i=0;i<inputs.length();i++)if(inputs.getJSONObject(i).getBoolean("default"))return inputs.getJSONObject(i).getBoolean("muted");return true;
    }
    public static int listPorts(ArrayList<Object> ports,int[] generation)throws Exception{
        if(ports==null||generation==null||generation.length!=1)throw new IllegalArgumentException("Audio port list arguments");
        JSONObject data=snapshot();int serial=1;
        Class<?> handle=Class.forName("android.media.AudioHandle"),gain=Class.forName("android.media.AudioGain"),port=Class.forName("android.media.AudioDevicePort");Constructor<?> hc=handle.getDeclaredConstructor(int.class);hc.setAccessible(true);Object gains=Array.newInstance(gain,0);
        Constructor<?> pc=port.getDeclaredConstructor(handle,String.class,int[].class,int[].class,int[].class,int[].class,gains.getClass(),int.class,String.class);pc.setAccessible(true);
        for(String direction:new String[]{"outputs","inputs"}){
            JSONArray rows=data.getJSONArray(direction);
            for(int i=0;i<rows.length();i++){
                JSONObject row=rows.getJSONObject(i);boolean input=direction.equals("inputs");int id=row.getInt("id")+(input?0x10000:1);
                String name=row.getString("name");int channels=row.getInt("channels");int type=input?0x80000004:2;
                // The host route is a physical PulseAudio sink/source, not an
                // Android mixer port. Profiles expose their actual channel count.
                Object value=pc.newInstance(hc.newInstance(id),row.getString("description"),new int[]{row.getInt("rate")},new int[0],new int[]{(1<<channels)-1},new int[]{AudioFormat.ENCODING_PCM_16BIT},gains,type,name);ports.add(value);serial=31*serial+name.hashCode()+channels;
            }
        }
        portGeneration=serial==0?1:serial;generation[0]=portGeneration;return 0;
    }
    public static int listPatches(ArrayList<Object> patches,int[] generation){if(patches==null||generation==null||generation.length!=1)return -22;generation[0]=portGeneration;return 0;}
    public static void setupEvents(final Object reference){
        // Android supplies a WeakReference. A daemon polls the actual host
        // inventory and notifies the framework only when its routes change.
        final java.lang.ref.WeakReference<?> owner=(java.lang.ref.WeakReference<?>)reference;
        Thread thread=new Thread(new Runnable(){public void run(){String previous=null;try{
            Method post=Class.forName("android.media.AudioPortEventHandler").getDeclaredMethod("postEventFromNative",Object.class,int.class,int.class,int.class,Object.class);post.setAccessible(true);
            while(owner.get()!=null){String now=snapshot().toString();if(previous!=null&&!previous.equals(now))post.invoke(null,reference,1,0,0,null);previous=now;Thread.sleep(2000);}
        }catch(Exception failure){System.err.println("SDAUDIO=route_monitor_unavailable|type="+failure.getClass().getName());}}},"SailDroid-audio-routes");thread.setDaemon(true);thread.start();
    }
    @Override public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
        String name=method.getName();if(name.equals("asBinder"))return binder;if(name.equals("toString"))return "PulseAudio read-only Android audio service";if(name.equals("hashCode"))return System.identityHashCode(proxy);if(name.equals("equals"))return proxy==args[0];
        if(name.equals("getStreamVolume")||name.equals("getLastAudibleStreamVolume")){int value=volume();System.err.println("SDAUDIO=volume|index="+value+"|source=pulseaudio|range=0-100");return value;}
        if(name.equals("getStreamMaxVolume"))return 100;
        if(name.equals("getStreamMinVolume"))return 0;
        if(name.equals("isStreamMute")||name.equals("isMasterMute"))return output().getBoolean("muted");
        if(name.equals("isMusicActive"))return streamActive(3,0);
        if(name.equals("getRingerModeExternal")||name.equals("getRingerModeInternal"))return org.saildroid.host.HostApi.ringerMode();
        if(name.equals("isMicrophoneMuted"))return microphoneMuted();
        if(name.equals("isBluetoothScoOn"))return bluetoothScoOn();
        if(name.equals("abandonAudioFocus")){
            if(args==null||args.length!=4||!SdApkPackage.NAME.equals(args[3]))throw new SecurityException("Audio focus caller differs from application");
            // This backend cannot grant Android focus requests, so there is
            // no accepted Android owner to remove. Match Android's successful
            // abandon of an absent client; do not acquire/change host focus.
            System.err.println("SDAUDIO=focus_abandon|owners=0|host_focus=unchanged|result=1");
            return AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
        }
        throw SdRuntimeDiagnostics.unsupported("Host audio service",method);
    }
}
