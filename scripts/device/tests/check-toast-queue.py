#!/usr/bin/env python3
"""Check toast queue ordering and lifecycle with deterministic Binder/Handler fixtures."""
from pathlib import Path
import subprocess
import tempfile


SOURCES = {
    'android/os/RemoteException.java': 'package android.os; public class RemoteException extends Exception {}',
    'android/os/IBinder.java': '''package android.os;
public interface IBinder {
    interface DeathRecipient { void binderDied(); }
    void linkToDeath(DeathRecipient recipient, int flags) throws RemoteException;
    boolean unlinkToDeath(DeathRecipient recipient, int flags);
}''',
    'android/os/Binder.java': '''package android.os;
public class Binder implements IBinder {
    public DeathRecipient recipient;
    public void linkToDeath(DeathRecipient value, int flags) throws RemoteException { recipient = value; }
    public boolean unlinkToDeath(DeathRecipient value, int flags) {
        if (recipient != value) throw new AssertionError("Recipient differs");
        recipient = null;
        return true;
    }
    public void die() { recipient.binderDied(); }
}''',
    'android/os/Looper.java': 'package android.os; public class Looper { public static Looper getMainLooper() { return new Looper(); } }',
    'android/os/Handler.java': '''package android.os;
import java.util.LinkedHashMap;
public class Handler {
    static long time;
    static LinkedHashMap<Runnable, Long> tasks = new LinkedHashMap<Runnable, Long>();
    public Handler(Looper looper) {}
    public void removeCallbacks(Runnable task) { tasks.remove(task); }
    public boolean postDelayed(Runnable task, long delay) { tasks.put(task, time + delay); return true; }
    public static void advance(long delay) {
        time += delay;
        for (Runnable task : tasks.keySet().toArray(new Runnable[0])) {
            if (tasks.containsKey(task) && tasks.get(task) <= time) { tasks.remove(task); task.run(); }
        }
    }
    public static int pending() { return tasks.size(); }
}''',
    'android/widget/Toast.java': 'package android.widget; public class Toast { public static final int LENGTH_SHORT = 0, LENGTH_LONG = 1; }',
    'android/app/ITransientNotification.java': '''package android.app;
import android.os.*;
public interface ITransientNotification {
    IBinder asBinder();
    void show(IBinder token) throws RemoteException;
    void hide() throws RemoteException;
}''',
    'ToastQueueProbe.java': '''import android.app.ITransientNotification;
import android.os.*;
public class ToastQueueProbe {
    static class Callback extends Binder implements ITransientNotification {
        int shown, hidden;
        boolean fail;
        public IBinder asBinder() { return this; }
        public void show(IBinder token) throws RemoteException {
            if (token == null) throw new AssertionError("Missing window token");
            if (fail) throw new RemoteException();
            shown++;
        }
        public void hide() { hidden++; }
    }
    static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        Callback first = new Callback(), second = new Callback();
        SdToastQueue.enqueue(first, 0); SdToastQueue.enqueue(second, 1);
        check(first.shown == 1 && second.shown == 0);
        Handler.advance(1000); SdToastQueue.enqueue(first, 1); Handler.advance(2000);
        check(first.hidden == 0); Handler.advance(1500);
        check(first.hidden == 1 && second.shown == 1);
        SdToastQueue.cancel(second); check(second.hidden == 1 && Handler.pending() == 0);
        Callback active = new Callback(), queued = new Callback();
        SdToastQueue.enqueue(active, 0); SdToastQueue.enqueue(queued, 0);
        SdToastQueue.cancel(queued); check(queued.shown == 0 && queued.hidden == 0);
        active.die(); check(active.hidden == 0 && Handler.pending() == 0);
        Callback failed = new Callback(); failed.fail = true;
        SdToastQueue.enqueue(failed, 0); check(failed.recipient == null && Handler.pending() == 0);
        Callback[] many = new Callback[50];
        for (int i = 0; i < many.length; i++) { many[i] = new Callback(); SdToastQueue.enqueue(many[i], 0); }
        try { SdToastQueue.enqueue(new Callback(), 0); throw new AssertionError("Limit missing"); }
        catch (IllegalStateException expected) {}
        for (Callback callback : many) SdToastQueue.cancel(callback);
        check(Handler.pending() == 0);
        System.out.println("TOAST_QUEUE=PASS|ordering=true|duration_reset=true|cancel=true|death=true|send_failure=true|limit=true|cleanup=true");
    }
}''',
}


def main():
    with tempfile.TemporaryDirectory(prefix='saildroid-toast-queue-') as directory:
        root = Path(directory)
        inputs = []
        for name, text in SOURCES.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
            inputs.append(path)
        inputs.append(Path(__file__).parents[1] / 'SdToastQueue.java')
        classes = root / 'classes'
        classes.mkdir()
        subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-d', str(classes), *map(str, inputs)], check=True)
        subprocess.run(['java', '-cp', str(classes), 'ToastQueueProbe'], check=True, timeout=20)


if __name__ == '__main__':
    main()
