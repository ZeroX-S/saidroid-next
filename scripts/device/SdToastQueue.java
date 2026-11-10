import android.app.ITransientNotification;
import android.os.Binder;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.RemoteException;
import android.widget.Toast;
import java.util.ArrayList;

/** App-local toast windows use the existing WindowSession surfaces. */
final class SdToastQueue {
    private static final ArrayList<Entry> queue = new ArrayList<Entry>();
    private static Handler handler;

    private static Handler handler() {
        if (handler == null) handler = new Handler(Looper.getMainLooper());
        return handler;
    }

    private static final class Entry implements Runnable, IBinder.DeathRecipient {
        final ITransientNotification callback;
        final IBinder token = new Binder();
        int duration;

        Entry(ITransientNotification callback, int duration) {
            this.callback = callback;
            this.duration = duration;
        }

        public void run() { remove(this, true); }

        public void binderDied() {
            synchronized (SdToastQueue.class) { remove(this, false); }
        }
    }

    static synchronized void enqueue(ITransientNotification callback, int duration) throws RemoteException {
        if (callback == null) throw new NullPointerException("Toast callback missing");
        for (Entry entry : queue) {
            if (entry.callback.asBinder().equals(callback.asBinder())) {
                entry.duration = duration;
                if (entry == queue.get(0)) schedule(entry);
                return;
            }
        }
        if (queue.size() >= 50) throw new IllegalStateException("Too many queued toasts");
        Entry entry = new Entry(callback, duration);
        callback.asBinder().linkToDeath(entry, 0);
        queue.add(entry);
        if (queue.size() == 1) showNext();
    }

    static synchronized void cancel(ITransientNotification callback) {
        if (callback == null) throw new NullPointerException("Toast callback missing");
        for (Entry entry : new ArrayList<Entry>(queue)) {
            if (entry.callback.asBinder().equals(callback.asBinder())) remove(entry, true);
        }
    }

    private static void schedule(Entry entry) {
        handler().removeCallbacks(entry);
        handler().postDelayed(entry, entry.duration == Toast.LENGTH_LONG ? 3500 : 2000);
    }

    private static void showNext() {
        while (!queue.isEmpty()) {
            Entry entry = queue.get(0);
            try {
                entry.callback.show(entry.token);
                schedule(entry);
                System.err.println("SDTOAST=shown|duration=" + entry.duration);
                return;
            } catch (RemoteException dead) { discard(entry); }
        }
    }

    private static synchronized void remove(Entry entry, boolean hide) {
        if (!queue.contains(entry)) return;
        boolean active = queue.get(0) == entry;
        if (active && hide) {
            try { entry.callback.hide(); }
            catch (RemoteException dead) { /* The dead client owns no live local view. */ }
        }
        discard(entry);
        if (active) showNext();
    }

    private static void discard(Entry entry) {
        handler().removeCallbacks(entry);
        queue.remove(entry);
        entry.callback.asBinder().unlinkToDeath(entry, 0);
    }
}
