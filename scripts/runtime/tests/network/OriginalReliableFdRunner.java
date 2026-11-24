import java.lang.reflect.InvocationTargetException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Explicit original reliable-FD methods with a real VM main Looper. */
public final class OriginalReliableFdRunner {
    public static void main(String[] args)throws Exception{
        NativeNetworkRegistrationContract.bootstrap(false,args[1]);
        int sdk=Integer.parseInt(args[4]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion()!=sdk)
            throw new AssertionError("Actual SDK not bound");
        CountDownLatch ready=new CountDownLatch(1);
        Thread main=new Thread(new Runnable(){public void run(){
            android.os.Looper.prepareMainLooper();ready.countDown();android.os.Looper.loop();
        }},"private-fd-main-looper");
        main.start();if(!ready.await(5,TimeUnit.SECONDS))throw new AssertionError("Real Looper did not start");
        ClassLoader loader=new dalvik.system.PathClassLoader(args[2],Object.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?> type=Class.forName("android.os.cts.ParcelFileDescriptorTest",true,loader);
        String[] methods={"testPipeNormal","testPipeError_Discouraged","testPipeError",
                "testFileNormal","testFileError","testFileDetach",
                "testSocketErrorAfterClose","testSocketMultipleCheck"};
        int failures=0;
        for(String name:methods){
            try{type.getMethod(name).invoke(type.newInstance());System.out.println("ORIGINAL_RELIABLE_FD|test="+name+"|result=PASS");}
            catch(InvocationTargetException failure){failures++;System.out.println("ORIGINAL_RELIABLE_FD|test="+name+"|result=FAIL");failure.getCause().printStackTrace();}
        }
        System.out.println("ORIGINAL_RELIABLE_FD_VM|tests=8|failures="+failures+"|targetSdk="+sdk);
        System.out.flush();System.err.flush();System.exit(failures==0?0:1);
    }
}
