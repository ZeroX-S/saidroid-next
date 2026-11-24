import android.net.sip.ISipSession;
import android.net.sip.ISipSessionListener;
import android.net.sip.SipProfile;
import android.os.DeadObjectException;
import android.os.RemoteException;
import java.util.ArrayDeque;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;

/** Keep callbacks ordered and outside the SIP transaction monitor. */
final class SdSipSessionListenerProxy extends ISipSessionListener.Stub {
    private static final ExecutorService workers = Executors.newCachedThreadPool(new ThreadFactory() {
        public Thread newThread(Runnable task) {
            Thread thread = new Thread(task, "SailDroid-SIP-callback");
            thread.setDaemon(true);
            return thread;
        }
    });
    private final ArrayDeque<Runnable> queue = new ArrayDeque<Runnable>();
    private ISipSessionListener listener;
    private boolean delivering;

    synchronized void setListener(ISipSessionListener value) { listener = value; }
    synchronized ISipSessionListener getListener() { return listener; }

    private interface Event { void send(ISipSessionListener target) throws RemoteException; }

    private synchronized void send(final Event event) {
        final ISipSessionListener target = listener;
        if (target == null) return;
        queue.add(new Runnable() {
            public void run() {
                try { event.send(target); }
                catch (DeadObjectException ended) {
                    synchronized (SdSipSessionListenerProxy.this) {
                        if (listener == target) listener = null;
                    }
                } catch (Exception failure) {
                    System.err.println("SDSIP=callback_failed|type=" + failure.getClass().getName());
                }
            }
        });
        if (delivering) return;
        delivering = true;
        workers.execute(new Runnable() {
            public void run() {
                for (;;) {
                    Runnable next;
                    synchronized (SdSipSessionListenerProxy.this) {
                        next = queue.poll();
                        if (next == null) { delivering = false; return; }
                    }
                    next.run();
                }
            }
        });
    }

    public void onCalling(final ISipSession session) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onCalling(session); } });
    }
    public void onRinging(final ISipSession session, final SipProfile caller, final String description) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onRinging(session, caller, description); } });
    }
    public void onRingingBack(final ISipSession session) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onRingingBack(session); } });
    }
    public void onCallEstablished(final ISipSession session, final String description) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onCallEstablished(session, description); } });
    }
    public void onCallEnded(final ISipSession session) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onCallEnded(session); } });
    }
    public void onCallBusy(final ISipSession session) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onCallBusy(session); } });
    }
    public void onCallTransferring(final ISipSession session, final String description) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onCallTransferring(session, description); } });
    }
    public void onError(final ISipSession session, final int code, final String message) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onError(session, code, message); } });
    }
    public void onCallChangeFailed(final ISipSession session, final int code, final String message) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onCallChangeFailed(session, code, message); } });
    }
    public void onRegistering(final ISipSession session) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onRegistering(session); } });
    }
    public void onRegistrationDone(final ISipSession session, final int duration) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onRegistrationDone(session, duration); } });
    }
    public void onRegistrationFailed(final ISipSession session, final int code, final String message) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onRegistrationFailed(session, code, message); } });
    }
    public void onRegistrationTimeout(final ISipSession session) {
        send(new Event() { public void send(ISipSessionListener target) throws RemoteException { target.onRegistrationTimeout(session); } });
    }
}
