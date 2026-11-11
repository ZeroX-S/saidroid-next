import android.os.Handler;
import android.os.Looper;
import android.os.MessageQueue;
import android.os.Message;
import java.lang.ref.WeakReference;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.HashMap;

/** Display callbacks are delivered from actual Wayland frame acknowledgements. */
public final class SdDisplayFrames {
    private static final HashMap<Long, Receiver> receivers = new HashMap<Long, Receiver>();
    private static long next = 1;
    private static long schedules,callbacks;
    public static synchronized void dumpState(){int pending=0;for(Receiver receiver:receivers.values())if(receiver.pending)pending++;System.err.println("SDDIAGNOSTICS=display|receivers="+receivers.size()+"|pending="+pending+"|scheduled="+schedules+"|callbacks="+callbacks);}
    private static final Method dispatch;
    static {
        try {
            dispatch = Class.forName("android.view.DisplayEventReceiver")
                    .getDeclaredMethod("dispatchVsync", long.class, int.class, int.class);
            dispatch.setAccessible(true);
        } catch (Exception failure) { throw new ExceptionInInitializerError(failure); }
    }
    private static final class Receiver {
        final long id;
        final WeakReference<?> target;
        final Handler handler;
        boolean pending;
        int frame;
        Receiver(long id, WeakReference<?> target) {
            this.id=id;this.target=target;this.handler=new Handler(Looper.myLooper());
        }
    }
    public static synchronized long initialize(WeakReference<?> target, MessageQueue queue) {
        if (Looper.myLooper()==null || queue!=Looper.myQueue()) {
            throw new IllegalStateException("Display receiver must belong to this thread's MessageQueue");
        }
        long id=next++;
        receivers.put(id,new Receiver(id,target));
        return id;
    }
    public static synchronized void dispose(long id) { receivers.remove(id); }
    public static synchronized void schedule(long id) {
        Receiver receiver=receivers.get(id);
        if(receiver==null)throw new IllegalStateException("Display receiver was disposed");
        receiver.pending=true;
        schedules++;
        SdWindowHost.requestFrame();
    }
    public static void onFrame(final long timestamp) {
        /* 遍历之前把 null 的 LayoutParams 补上：应用若在 addView 路径上漏了参数，
           measure 阶段会 NPE 并把整个进程带走（见 SdViewRepair 的注释与真机证据）。 */
        SdViewRepair.repair();
        ArrayList<Receiver> pending=new ArrayList<Receiver>();
        synchronized(SdDisplayFrames.class) {
            callbacks++;
            for(Receiver receiver:receivers.values())if(receiver.pending){receiver.pending=false;pending.add(receiver);}
        }
        for(final Receiver receiver:pending){
          Message message=Message.obtain(receiver.handler,new Runnable(){
            @Override public void run(){
                synchronized(SdDisplayFrames.class){if(receivers.get(receiver.id)!=receiver)return;}
                Object target=receiver.target.get();
                if(target==null){dispose(receiver.id);return;}
                try{dispatch.invoke(target,timestamp,SdDisplayShim.DISPLAY_ID,++receiver.frame);}
                catch(Exception failure){throw new IllegalStateException("Wayland frame callback failed",failure);}
            }
          });
          // A ViewRoot traversal inserts a synchronization barrier. Native
          // display callbacks are asynchronous events and must cross it.
          message.setAsynchronous(true);
          receiver.handler.sendMessage(message);
        }
        /* Opt-in compose coalescing: SdSurfaceStore only uses this when
           SAILDROID_COMPOSE_ON_VSYNC is set, otherwise it is a no-op. */
        SdSurfaceStore.onVsync();
    }
}
