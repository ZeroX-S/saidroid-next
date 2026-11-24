import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.os.Bundle;
import android.os.IBinder;
import android.os.Parcel;
import android.os.RemoteException;
import android.os.SystemClock;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Unordered explicit broadcasts to real receivers in the hosted APK. */
public final class SdManifestReceivers {
    private static final ExecutorService worker = createWorkerPool();
    private static final ConcurrentHashMap<String, Object> processGates = new ConcurrentHashMap<String, Object>();
    private SdManifestReceivers() {}

    private static ExecutorService createWorkerPool() {
        ThreadPoolExecutor pool = new ThreadPoolExecutor(4, 4, 30L, TimeUnit.SECONDS,
                new LinkedBlockingQueue<Runnable>());
        pool.allowCoreThreadTimeOut(true);
        return pool;
    }

    private static Object gateForProcess(String processName) {
        Object gate = processGates.get(processName);
        if (gate == null) {
            Object created = new Object();
            Object existing = processGates.putIfAbsent(processName, created);
            gate = existing != null ? existing : created;
        }
        return gate;
    }

    private static ActivityInfo resolve(Intent intent) {
        ComponentName component = intent.getComponent();
        if (component == null) throw new IllegalArgumentException("Explicit receiver component required");
        if (!SdApkPackage.NAME.equals(component.getPackageName()) ||
                (intent.getPackage() != null && !SdApkPackage.NAME.equals(intent.getPackage())))
            throw new SecurityException("Manifest receiver is outside the hosted APK");
        ActivityInfo info = SdApkPackage.receiverInfo(component, 0);
        if (info == null || !info.applicationInfo.enabled) return null;
        return info;
    }

    public static void send(Intent source, int result, String resultData, Bundle extras,
                            String[] requiredPermissions, int user) throws Exception {
        SdServices.activityManager().checkManifestReceiverUser(user);
        final Intent intent = new Intent(source);
        final ActivityInfo info = resolve(intent);
        if (info == null) {
            System.err.println("SDBROADCAST=manifest_not_delivered|reason=not-declared-or-disabled");
            return;
        }
        if (!SdServices.activityManager().allowManifestReceiver(info, requiredPermissions, user)) {
            System.err.println("SDBROADCAST=manifest_not_delivered|reason=permission|class="+info.name);
            return;
        }
        if (SdApkPackage.processName().equals(info.processName)) {
            deliverLocal(intent, result, resultData, extras, requiredPermissions, user);
            return;
        }
        if (!SdKernelServices.enabled())
            throw new UnsupportedOperationException("Receiver processes require private Binder");
        final Bundle copiedExtras = extras == null ? null : new Bundle(extras);
        final String[] copiedPermissions = requiredPermissions == null ? null : requiredPermissions.clone();
        worker.execute(new Runnable() {
            public void run() {
                synchronized (gateForProcess(info.processName)) {
                    try {
                        String name = SdKernelServices.processName(SdApkPackage.NAME, info.processName);
                        IBinder endpoint = SdKernelServices.registry().checkService(name);
                        if (endpoint != null && !endpoint.isBinderAlive()) endpoint = null;
                        if (endpoint == null) {
                            org.saildroid.host.HostApi.startReceiverProcess(SdApkPackage.NAME, info.name, info.processName);
                            endpoint = SdProcessStartup.awaitEndpoint(name, "Receiver process startup deadline");
                        }
                        Parcel data = Parcel.obtain(), reply = Parcel.obtain();
                        try {
                            data.writeInterfaceToken(SdServiceEndpoint.DESCRIPTOR);
                            data.writeString(SdApkPackage.NAME);
                            intent.writeToParcel(data, 0);
                            data.writeInt(result); data.writeString(resultData); data.writeBundle(copiedExtras);
                            data.writeStringArray(copiedPermissions); data.writeInt(user);
                            if (!endpoint.transact(SdServiceEndpoint.MANIFEST_RECEIVER, data, reply, 0))
                                throw new RemoteException("Receiver endpoint rejected transaction");
                            reply.readException();
                        } finally { data.recycle(); reply.recycle(); }
                    } catch (Exception failure) {
                        if (failure instanceof InterruptedException) Thread.currentThread().interrupt();
                        System.err.println("SDBROADCAST=manifest_dispatch_failed|class="+info.name
                                +"|type="+failure.getClass().getName());
                        failure.printStackTrace();
                    }
                }
            }
        });
    }

    public static void deliverLocal(Intent intent, int result, String resultData, Bundle extras,
                                    String[] requiredPermissions, int user) throws Exception {
        SdServices.activityManager().checkManifestReceiverUser(user);
        ActivityInfo info = resolve(intent);
        if (info == null) throw new IllegalArgumentException("Receiver is not enabled in the hosted APK");
        if (!SdApkPackage.processName().equals(info.processName))
            throw new SecurityException("Receiver does not belong to this process");
        if (!SdServices.activityManager().allowManifestReceiver(info, requiredPermissions, user)) return;
        SdServices.activityManager().scheduleManifestReceiver(intent, info, result, resultData, extras, user);
    }
}
