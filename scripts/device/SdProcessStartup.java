import android.os.IBinder;
import android.os.RemoteException;
import android.os.SystemClock;

public final class SdProcessStartup {
    static final long TIMEOUT_MS=120000;
    private SdProcessStartup(){}
    static IBinder awaitEndpoint(String name,String failure)throws RemoteException,InterruptedException{
        long deadline=SystemClock.uptimeMillis()+TIMEOUT_MS;
        while(true){
            IBinder endpoint=SdKernelServices.registry().checkService(name);
            if(endpoint!=null&&endpoint.isBinderAlive())return endpoint;
            if(SystemClock.uptimeMillis()>=deadline)throw new IllegalStateException(failure);
            Thread.sleep(50);
        }
    }
}
