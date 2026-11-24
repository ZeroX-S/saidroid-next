import android.os.*;
import android.system.*;
import java.lang.reflect.*;
import java.lang.ref.WeakReference;
import java.io.*;
import java.util.*;

/** Real API29 JNI / private-kernel Binder regression; no UI or fabricated events. */
public final class SensorServiceProbe {
    private static Object call(Class<?> type,String name,Class<?>[] types,Object...args)throws Exception{
        Method method=type.getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(null,args);
    }
    private static Parcel request(String descriptor){Parcel data=Parcel.obtain();data.writeInterfaceToken(descriptor);return data;}
    private static IBinder connection(IBinder sensor)throws Exception{
        Parcel data=request("android.gui.SensorServer"),reply=Parcel.obtain();
        // Native String8 (length + UTF8 + NUL + padding), followed by mode and String16.
        byte[] name="sensor-probe\0".getBytes("UTF-8");data.writeInt(name.length-1);
        int start=data.dataPosition();data.setDataSize(start+((name.length+3)&~3));
        byte[] bytes=data.marshall();System.arraycopy(name,0,bytes,start,name.length);data.unmarshall(bytes,0,bytes.length);data.setDataPosition(bytes.length);
        data.writeInt(0);data.writeString("org.saildroid.sensorprobe");
        try{if(!sensor.transact(2,data,reply,0))throw new AssertionError("Connection rejected");IBinder result=reply.readStrongBinder();if(result==null)throw new AssertionError("No event connection");return result;}finally{data.recycle();reply.recycle();}
    }
    private static void destroy(IBinder connection)throws Exception{
        Parcel data=Parcel.obtain(),reply=Parcel.obtain();try{if(!connection.transact(6,data,reply,0))throw new AssertionError("Destroy rejected");}finally{data.recycle();reply.recycle();}
    }
    public static void main(String[] args){try{
        SdRuntime.initializeFramework(false);Looper.prepareMainLooper();SdBridge.startBinderPool();
        if(args[0].equals("server")){
            if(!SdBridge.becomeBinderContextManager(new SdBinderRegistry()))throw new AssertionError("Context claim failed");
            try(FileWriter ready=new FileWriter(args[1])){ready.write(Integer.toString(android.os.Process.myPid()));}
            Looper.loop();return;
        }
        android.os.IServiceManager registry=SdKernelServices.registry();
        registry.addService("saidroid.process.sensorprobe."+android.os.Process.myPid(),new Binder(),false,0);
        IBinder sensor=registry.getService("sensorservice");if(sensor==null||!sensor.isBinderAlive())throw new AssertionError("Sensor service absent");
        if(args[0].equals("leak")){for(int i=0;i<8;i++)connection(sensor);System.err.println("SENSOR_PROBE=abandoned|channels=8");Runtime.getRuntime().halt(0);}
        // API29's native-compatible addService proxy ignores exception replies.
        // Check the service identity rather than expecting a Java exception.
        try{registry.addService("sensorservice",new Binder(),false,0);}catch(SecurityException expected){}
        if(!sensor.equals(registry.getService("sensorservice")))throw new AssertionError("Platform service overwrite accepted");
        for(int i=0;i<40;i++){
            IBinder channel=connection(sensor);Parcel data=request("android.gui.SensorEventConnection"),reply=Parcel.obtain();
            try{
                if(!channel.transact(1,data,reply,0))throw new AssertionError("No channel FD");
                ParcelFileDescriptor fd=reply.readFileDescriptor();if(fd==null)throw new AssertionError("Missing real FD");
                try{byte[] buffer=new byte[104];try{Os.read(fd.getFileDescriptor(),buffer,0,buffer.length);throw new AssertionError("Unexpected sensor data/EOF");}catch(ErrnoException expected){if(expected.errno!=OsConstants.EAGAIN)throw expected;}}finally{fd.close();}
            }finally{data.recycle();reply.recycle();destroy(channel);}
        }
        Class<?> manager=Class.forName("android.hardware.SystemSensorManager");
        call(manager,"nativeClassInit",new Class<?>[0]);
        long pointer=(Long)call(manager,"nativeCreate",new Class<?>[]{String.class},"org.saildroid.sensorprobe");if(pointer==0)throw new AssertionError("Native manager absent");
        Constructor<android.hardware.Sensor> constructor=android.hardware.Sensor.class.getDeclaredConstructor();constructor.setAccessible(true);
        boolean hasSensor=(Boolean)call(manager,"nativeGetSensorAtIndex",new Class<?>[]{long.class,android.hardware.Sensor.class,int.class},pointer,constructor.newInstance(),0);
        ArrayList<android.hardware.Sensor> dynamic=new ArrayList<android.hardware.Sensor>();
        call(manager,"nativeGetDynamicSensors",new Class<?>[]{long.class,List.class},pointer,dynamic);
        if(hasSensor||!dynamic.isEmpty()||(Boolean)call(manager,"nativeIsDataInjectionEnabled",new Class<?>[]{long.class},pointer))throw new AssertionError("Invented sensor capability");
        Class<?> queue=Class.forName("android.hardware.SystemSensorManager$BaseEventQueue");
        for(int i=0;i<8;i++){
            long handle=(Long)call(queue,"nativeInitBaseEventQueue",new Class<?>[]{long.class,WeakReference.class,MessageQueue.class,String.class,int.class,String.class},pointer,new WeakReference<Object>(null),Looper.myQueue(),"sensor-probe",0,"org.saildroid.sensorprobe");
            if(handle==0)throw new AssertionError("Native event queue unavailable");
            try{
                int enable=(Integer)call(queue,"nativeEnableSensor",new Class<?>[]{long.class,int.class,int.class,int.class},handle,123456,10000,0);
                int flush=(Integer)call(queue,"nativeFlushSensor",new Class<?>[]{long.class},handle);
                if(enable>=0||flush>=0)throw new AssertionError("Unsupported sensor accepted");
            }finally{call(queue,"nativeDestroySensorEventQueue",new Class<?>[]{long.class},handle);}
        }
        System.err.println("SENSOR_PROBE=PASS|raw_channels=40|native_queues=8|static_dynamic_sensors=0|injection=false|invalid_handles=rejected|platform_overwrite=refused|uid="+android.os.Process.myUid());Runtime.getRuntime().halt(0);
    }catch(Throwable failure){failure.printStackTrace();Runtime.getRuntime().halt(9);}}
}
