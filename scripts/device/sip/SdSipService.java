import android.app.PendingIntent;
import android.content.Intent;
import android.net.sip.ISipService;
import android.net.sip.ISipSession;
import android.net.sip.ISipSessionListener;
import android.net.sip.SipErrorCode;
import android.net.sip.SipManager;
import android.net.sip.SipProfile;
import android.net.sip.SipSession;
import android.net.sip.SipSessionAdapter;
import android.os.Binder;
import android.os.IBinder;
import android.os.RemoteException;
import android.os.SystemClock;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ScheduledFuture;

/** SIP signaling shared by the hosted APK's processes on its private Binder. */
public final class SdSipService extends ISipService.Stub {
    private static final int REGISTRATION_SECONDS = 3600;
    private static final int MAX_PROFILES = 16;
    private static final int MAX_SESSIONS = 64;
    private static final Client client = new Client();
    private static SdSipService local;
    private final SdSipScheduler scheduler = new SdSipScheduler();
    private final SdSipWakeLock wakeLock = new SdSipWakeLock(scheduler);
    private final Map<String, Profile> profiles = new HashMap<String, Profile>();
    private final Map<String, Session> pending = new HashMap<String, Session>();
    private SdAppPermissions permissions;

    public static IBinder binder() { return client; }
    public static boolean available() { return android.os.Build.VERSION.SDK_INT == 28; }
    static void permissionChanged() {
        try { client.getListOfProfiles(SdApkPackage.NAME); }
        catch (SecurityException revoked) { }
        catch (RemoteException ended) { System.err.println("SDSIP=permission_cleanup_process_exited"); }
    }

    private synchronized void authorize(String packageName) {
        if (Binder.getCallingUid() != android.os.Process.myUid() || !SdApkPackage.NAME.equals(packageName)) {
            throw new SecurityException("SIP package or UID differs from the hosted APK");
        }
        try {
            if (permissions == null) permissions = new SdAppPermissions(SdApkPackage.APK, SdApkPackage.NAME);
            if (!permissions.holds("android.permission.USE_SIP")) {
                for (Profile record : new ArrayList<Profile>(profiles.values())) closeProfile(record);
                throw new SecurityException("SIP permission required");
            }
            if (!permissions.holds("android.permission.INTERNET")) throw new SecurityException("SIP Internet permission required");
        } catch (SecurityException denied) {
            throw denied;
        } catch (Exception failure) {
            throw new IllegalStateException("Cannot read SIP application permissions", failure);
        }
    }

    private static SipProfile copy(SipProfile profile) {
        try { return new SipProfile.Builder(profile).setPassword(null).build(); }
        catch (Exception failure) { throw new IllegalArgumentException("Invalid SIP profile", failure); }
    }

    private synchronized Profile profile(SipProfile requested, boolean opening) {
        if (requested == null) throw new NullPointerException("SIP profile required");
        String uri = requested.getUriString();
        Profile record = profiles.get(uri);
        boolean changed = record != null && ((requested.getPassword() != null && !Objects.equals(record.password, requested.getPassword()))
                || (opening && (!Objects.equals(record.local.getProxyAddress(), requested.getProxyAddress())
                || !record.local.getProtocol().equals(requested.getProtocol()) || record.local.getPort() != requested.getPort()
                || !Objects.equals(record.local.getAuthUserName(), requested.getAuthUserName())
                || !Objects.equals(record.local.getDisplayName(), requested.getDisplayName())
                || record.local.getSendKeepAlive() != requested.getSendKeepAlive()
                || record.local.getAutoRegistration() != requested.getAutoRegistration())));
        if (changed) {
            for (Session session : record.sessions.values()) {
                if (session.raw.getState() != SipSession.State.READY_TO_CALL) {
                    throw new IllegalStateException("Close active SIP transactions before changing credentials");
                }
            }
            closeProfile(record);
            record = null;
        }
        if (record == null) {
            if (profiles.size() >= MAX_PROFILES) throw new IllegalStateException("SIP profile limit reached");
            record = new Profile(requested);
            profiles.put(uri, record);
        }
        return record;
    }

    @Override public synchronized void open(SipProfile profile, String packageName) {
        authorize(packageName);
        profile(profile, true).connect();
    }

    @Override public synchronized void open3(SipProfile profile, PendingIntent incoming, ISipSessionListener listener,
                                             String packageName) {
        authorize(packageName);
        if (incoming == null) throw new NullPointerException("Incoming SIP PendingIntent required");
        try { SdPendingIntents.requireSipOwner(incoming, SdApkPackage.NAME); }
        catch (RemoteException ended) { throw new IllegalStateException("Incoming SIP process exited", ended); }
        Profile record = profile(profile, true);
        record.incoming = incoming;
        record.registration.setListener(listener);
        record.auto = profile.getAutoRegistration();
        record.connect();
        if (record.group != null) record.group.openToReceiveCalls(record.events);
        if (record.auto) record.registerAutomatically();
    }

    @Override public synchronized void close(String uri, String packageName) {
        authorize(packageName);
        Profile record = profiles.get(uri);
        if (record != null) closeProfile(record);
    }

    private void closeProfile(final Profile record) {
        profiles.remove(record.local.getUriString());
        record.closed = true;
        record.cancelRenewal();
        if (record.expiry != null) { record.expiry.cancel(false); record.expiry = null; }
        record.stopKeepAlive();
        wakeLock.release(record.receiveOwner);
        record.registration.setListener(null);
        for (Session session : new ArrayList<Session>(record.sessions.values())) {
            pending.values().remove(session);
            if (!session.registrationOperation && !session.automatic) {
                session.callback.onCallEnded(session);
                session.raw.endCall();
            }
            session.detach();
            wakeLock.release(session);
        }
        record.sessions.clear();
        if (record.group == null) return;
        if (record.registeredUntil > SystemClock.elapsedRealtime()) record.deregister();
        scheduler.after(4000, new Runnable() {
            public void run() {
                synchronized (SdSipService.this) {
                    record.group.dispose();
                    record.sessions.clear();
                    wakeLock.release(record);
                }
            }
        });
        System.err.println("SDSIP=profile_closed|profiles=" + profiles.size());
    }

    @Override public synchronized boolean isOpened(String uri, String packageName) {
        authorize(packageName);
        return profiles.containsKey(uri);
    }

    @Override public synchronized boolean isRegistered(String uri, String packageName) {
        authorize(packageName);
        Profile record = profiles.get(uri);
        return record != null && record.registeredUntil > SystemClock.elapsedRealtime();
    }

    @Override public synchronized void setRegistrationListener(String uri, ISipSessionListener listener, String packageName) {
        authorize(packageName);
        Profile record = profiles.get(uri);
        if (record == null) return;
        record.registration.setListener(listener);
        if (record.autoSession != null && record.autoSession.raw.getState() == SipSession.State.REGISTERING) {
            record.registration.onRegistering(record.autoSession);
        } else if (record.registeredUntil > SystemClock.elapsedRealtime()) {
            record.registration.onRegistrationDone(record.autoSession,
                    (int) ((record.registeredUntil - SystemClock.elapsedRealtime()) / 1000));
        } else if (record.error != SipErrorCode.NO_ERROR) {
            record.registration.onRegistrationFailed(record.autoSession, record.error, record.errorMessage);
        }
    }

    @Override public synchronized ISipSession createSession(SipProfile profile, ISipSessionListener listener, String packageName) {
        authorize(packageName);
        Profile record = profile(profile, false);
        if (!record.connect()) return null;
        Session session = record.wrap(record.group.createSession(record.events));
        record.sessions.remove(session.raw.asBinder());
        session.setListener(listener);
        return session;
    }

    @Override public synchronized ISipSession getPendingSession(String callId, String packageName) {
        authorize(packageName);
        Session session = pending.remove(callId);
        if (session == null || session.owner.closed || session.raw.getState() != SipSession.State.INCOMING_CALL) return null;
        session.taken = true;
        return session;
    }

    @Override public synchronized SipProfile[] getListOfProfiles(String packageName) {
        authorize(packageName);
        ArrayList<SipProfile> result = new ArrayList<SipProfile>();
        for (Profile record : profiles.values()) result.add(copy(record.local));
        return result.toArray(new SipProfile[result.size()]);
    }

    private final class Profile {
        final SipProfile local;
        final String password;
        final Map<IBinder, Session> sessions = new IdentityHashMap<IBinder, Session>();
        final SdSipSessionListenerProxy registration = new SdSipSessionListenerProxy();
        final Events events = new Events(this, null);
        final Object receiveOwner = new Object();
        SdSipSessionGroup group;
        Session autoSession;
        PendingIntent incoming;
        ScheduledFuture<?> renewal;
        ScheduledFuture<?> expiry;
        SdSipSessionGroup.SipSessionImpl keepAlive;
        boolean auto;
        volatile boolean closed;
        long registeredUntil;
        int retrySeconds = 5;
        int error;
        String errorMessage;

        Profile(SipProfile requested) {
            local = copy(requested);
            local.setCallingUid(android.os.Process.myUid());
            password = requested.getPassword() == null ? "" : requested.getPassword();
        }

        boolean connect() {
            if (closed) return false;
            try {
                if (group == null) group = new SdSipSessionGroup(local, password, scheduler, wakeLock);
                else if (group.isClosed()) group.reset();
                if (incoming != null) group.openToReceiveCalls(events);
                return !group.isClosed();
            } catch (javax.sip.SipException unavailable) {
                error = SipErrorCode.SERVER_UNREACHABLE;
                errorMessage = "Cannot reach SIP server";
                registration.onRegistrationFailed(autoSession, error, errorMessage);
                if (auto) retry();
                return false;
            }
        }

        Session wrap(ISipSession raw) {
            if (raw == null) throw new IllegalStateException("SIP session backend unavailable");
            Session session = sessions.get(raw.asBinder());
            if (session != null) return session;
            if (sessions.size() >= MAX_SESSIONS) throw new IllegalStateException("SIP session limit reached");
            session = new Session(this, (SdSipSessionGroup.SipSessionImpl) raw);
            sessions.put(raw.asBinder(), session);
            session.raw.setListener(new Events(this, session));
            return session;
        }

        void cancelRenewal() {
            if (renewal != null) { renewal.cancel(false); renewal = null; }
        }

        void renewAfter(long milliseconds) {
            cancelRenewal();
            renewal = scheduler.after(milliseconds, new Runnable() {
                public void run() {
                    synchronized (SdSipService.this) { if (!closed && auto) registerAutomatically(); }
                }
            });
        }

        void retry() {
            if (closed || !auto) return;
            renewAfter(retrySeconds * 1000L);
            retrySeconds = Math.min(300, retrySeconds * 2);
        }

        void registerAutomatically() {
            cancelRenewal();
            try { authorize(SdApkPackage.NAME); }
            catch (SecurityException revoked) { return; }
            if (!connect()) return;
            if (autoSession == null) {
                autoSession = wrap(group.createSession(events));
                autoSession.automatic = true;
            }
            if (autoSession.raw.getState() != SipSession.State.READY_TO_CALL) return;
            wakeLock.acquire(this);
            autoSession.raw.register(REGISTRATION_SECONDS);
        }

        void stopKeepAlive() {
            if (keepAlive != null) { keepAlive.stopKeepAliveProcess(); keepAlive = null; }
        }

        void maintainRegistration(final int seconds) {
            if (expiry != null) { expiry.cancel(false); expiry = null; }
            if (seconds <= 0) {
                stopKeepAlive();
                wakeLock.release(receiveOwner);
                return;
            }
            if (incoming != null) wakeLock.acquire(receiveOwner);
            expiry = scheduler.after(seconds * 1000L, new Runnable() {
                public void run() {
                    synchronized (SdSipService.this) {
                        if (registeredUntil <= SystemClock.elapsedRealtime()) {
                            stopKeepAlive();
                            wakeLock.release(receiveOwner);
                        }
                    }
                }
            });
            if (!auto || !local.getSendKeepAlive() || keepAlive != null) return;
            keepAlive = (SdSipSessionGroup.SipSessionImpl) group.createSession(null);
            try {
                keepAlive.startKeepAliveProcess(15, new SdSipSessionGroup.KeepAliveProcessCallback() {
                    public void onResponse(boolean portChanged) {
                        synchronized (SdSipService.this) {
                            if (portChanged && !closed) { stopKeepAlive(); group.resetExternalAddress(); registerAutomatically(); }
                        }
                    }
                    public void onError(int code, String message) {
                        synchronized (SdSipService.this) { stopKeepAlive(); retry(); }
                    }
                });
            } catch (javax.sip.SipException failure) { stopKeepAlive(); retry(); }
        }

        void deregister() {
            Session session = wrap(group.createSession(events));
            session.deregistration = true;
            session.raw.unregister();
        }
    }

    private final class Session extends ISipSession.Stub implements IBinder.DeathRecipient {
        final Profile owner;
        final SdSipSessionGroup.SipSessionImpl raw;
        final SdSipSessionListenerProxy callback = new SdSipSessionListenerProxy();
        IBinder listenerBinder;
        boolean automatic;
        boolean deregistration;
        boolean registrationOperation;
        boolean taken;

        Session(Profile owner, SdSipSessionGroup.SipSessionImpl raw) { this.owner = owner; this.raw = raw; }

        private void check() {
            authorize(SdApkPackage.NAME);
            if (owner.closed) throw new IllegalStateException("SIP profile is closed");
        }

        private void checkIdentity() {
            if (Binder.getCallingUid() != android.os.Process.myUid()) throw new SecurityException("SIP session UID differs");
        }

        private void activate() {
            if (owner.sessions.size() >= MAX_SESSIONS && !owner.sessions.containsKey(raw.asBinder())) {
                throw new IllegalStateException("SIP active session limit reached");
            }
            owner.sessions.put(raw.asBinder(), this);
            linkListener();
        }

        @Override public String getLocalIp() { checkIdentity(); return raw.getLocalIp(); }
        @Override public SipProfile getLocalProfile() { checkIdentity(); return copy(owner.local); }
        @Override public SipProfile getPeerProfile() { checkIdentity(); SipProfile peer = raw.getPeerProfile(); return peer == null ? null : copy(peer); }
        @Override public int getState() { checkIdentity(); return owner.closed ? SipSession.State.READY_TO_CALL : raw.getState(); }
        @Override public boolean isInCall() { checkIdentity(); return !owner.closed && raw.isInCall(); }
        @Override public String getCallId() { checkIdentity(); return raw.getCallId(); }

        @Override public void setListener(ISipSessionListener listener) {
            synchronized (SdSipService.this) {
                if (listener == null) checkIdentity();
                else check();
                detach();
                callback.setListener(listener);
                if (owner.sessions.containsKey(raw.asBinder()) || raw.getState() != SipSession.State.READY_TO_CALL) linkListener();
            }
        }

        void detach() {
            unlinkListener();
            callback.setListener(null);
        }

        void unlinkListener() {
            if (listenerBinder != null) listenerBinder.unlinkToDeath(this, 0);
            listenerBinder = null;
        }

        void linkListener() {
            ISipSessionListener listener = callback.getListener();
            if (listenerBinder != null || listener == null) return;
            listenerBinder = listener.asBinder();
            try { listenerBinder.linkToDeath(this, 0); }
            catch (RemoteException ended) { binderDied(); throw new IllegalStateException("SIP callback process exited", ended); }
        }

        @Override public void binderDied() {
            synchronized (SdSipService.this) {
                detach();
                pending.values().remove(this);
                if (!owner.closed) raw.endCall();
                wakeLock.release(this);
            }
        }

        @Override public void register(int seconds) {
            synchronized (SdSipService.this) {
                check();
                if (seconds < 0) throw new IllegalArgumentException("SIP registration expiry out of range");
                registrationOperation = true;
                deregistration = false;
                activate();
                if (seconds == 0) { deregistration = true; raw.unregister(); }
                else raw.register(seconds);
            }
        }
        @Override public void unregister() {
            synchronized (SdSipService.this) {
                check();
                owner.cancelRenewal();
                deregistration = true;
                registrationOperation = true;
                activate();
                raw.unregister();
            }
        }
        @Override public void makeCall(SipProfile callee, String description, int seconds) {
            synchronized (SdSipService.this) {
                check();
                if (callee == null || description == null) throw new NullPointerException("SIP peer and SDP required");
                activate();
                registrationOperation = false;
                raw.makeCall(copy(callee), description, seconds);
            }
        }
        @Override public void answerCall(String description, int seconds) {
            synchronized (SdSipService.this) {
                check();
                if (description == null) throw new NullPointerException("SIP SDP required");
                raw.answerCall(description, seconds);
            }
        }
        @Override public void endCall() {
            synchronized (SdSipService.this) { check(); raw.endCall(); }
        }
        @Override public void changeCall(String description, int seconds) {
            synchronized (SdSipService.this) {
                check();
                if (description == null) throw new NullPointerException("SIP SDP required");
                raw.changeCall(description, seconds);
            }
        }
    }

    private final class Events extends SipSessionAdapter {
        final Profile owner;
        final Session origin;
        Events(Profile owner, Session origin) { this.owner = owner; this.origin = origin; }
        private Session session(ISipSession raw) {
            return origin != null && origin.raw.asBinder() == raw.asBinder() ? origin : owner.wrap(raw);
        }

        @Override public void onCalling(ISipSession raw) {
            synchronized (SdSipService.this) { if (!owner.closed) { Session call = session(raw); call.callback.onCalling(call); } }
        }
        @Override public void onRingingBack(ISipSession raw) {
            synchronized (SdSipService.this) { if (!owner.closed) { Session call = session(raw); call.callback.onRingingBack(call); } }
        }
        @Override public void onRinging(ISipSession raw, SipProfile caller, String description) {
            synchronized (SdSipService.this) {
                if (owner.closed) { rawEnd(raw); return; }
                final Session call = session(raw);
                if (call.taken || call.raw.isInCall()) { call.callback.onRinging(call, caller, description); return; }
                if (owner.incoming == null || pending.size() >= 16) { rawEnd(raw); return; }
                final String id = call.raw.getCallId();
                pending.put(id, call);
                Intent intent = SipManager.createIncomingCallBroadcast(id, description);
                intent.putExtra(SipManager.EXTRA_LOCAL_URI, owner.local.getUriString());
                try {
                    SdPendingIntents.sendSip(owner.incoming, SdApkPackage.NAME, intent);
                    System.err.println("SDSIP=incoming_call_dispatched");
                } catch (RemoteException | RuntimeException canceled) {
                    pending.remove(id);
                    rawEnd(raw);
                }
                scheduler.after(60000, new Runnable() {
                    public void run() {
                        synchronized (SdSipService.this) {
                            if (pending.get(id) == call) { pending.remove(id); call.raw.endCall(); }
                        }
                    }
                });
            }
        }
        private void rawEnd(ISipSession raw) {
            try { raw.endCall(); } catch (RemoteException ended) { }
        }
        @Override public void onCallEstablished(ISipSession raw, String description) {
            synchronized (SdSipService.this) {
                if (owner.closed) { rawEnd(raw); return; }
                Session call = session(raw);
                pending.values().remove(call);
                wakeLock.acquire(call);
                call.callback.onCallEstablished(call, description);
                System.err.println("SDSIP=call_established");
            }
        }
        private Session ended(ISipSession raw) {
            Session call = session(raw);
            pending.values().remove(call);
            owner.sessions.remove(raw.asBinder());
            wakeLock.release(call);
            call.unlinkListener();
            return call;
        }
        @Override public void onCallEnded(ISipSession raw) {
            synchronized (SdSipService.this) { Session call = ended(raw); if (!owner.closed) call.callback.onCallEnded(call); }
        }
        @Override public void onCallBusy(ISipSession raw) {
            synchronized (SdSipService.this) { Session call = ended(raw); if (!owner.closed) call.callback.onCallBusy(call); }
        }
        @Override public void onError(ISipSession raw, int code, String message) {
            synchronized (SdSipService.this) {
                Session call = session(raw);
                if (code != SipErrorCode.IN_PROGRESS) ended(raw);
                if (!owner.closed) call.callback.onError(call, code, message);
            }
        }
        @Override public void onCallChangeFailed(ISipSession raw, int code, String message) {
            synchronized (SdSipService.this) { if (!owner.closed) { Session call = session(raw); call.callback.onCallChangeFailed(call, code, message); } }
        }
        @Override public void onCallTransferring(ISipSession raw, String description) {
            synchronized (SdSipService.this) {
                if (!owner.closed && origin != null) {
                    Session call = session(raw);
                    origin.callback.onCallTransferring(call, description);
                }
            }
        }
        @Override public void onRegistering(ISipSession raw) {
            synchronized (SdSipService.this) {
                if (owner.closed) return;
                Session registration = session(raw);
                wakeLock.acquire(owner);
                registration.callback.onRegistering(registration);
                if (registration.automatic) owner.registration.onRegistering(registration);
            }
        }
        @Override public void onRegistrationDone(ISipSession raw, int duration) {
            synchronized (SdSipService.this) {
                Session registration = session(raw);
                wakeLock.release(owner);
                owner.error = SipErrorCode.NO_ERROR;
                owner.errorMessage = null;
                owner.registeredUntil = duration > 0 ? SystemClock.elapsedRealtime() + duration * 1000L : 0;
                if (owner.closed) { if (duration > 0) owner.deregister(); return; }
                owner.maintainRegistration(duration);
                registration.callback.onRegistrationDone(registration, duration);
                if (registration.automatic) owner.registration.onRegistrationDone(registration, duration);
                owner.retrySeconds = 5;
                if (owner.auto && duration > 0) owner.renewAfter(Math.max(1000, duration * 800L));
                if (!registration.automatic) { owner.sessions.remove(raw.asBinder()); registration.unlinkListener(); }
                System.err.println("SDSIP=registration_done|seconds=" + Math.max(0, duration));
            }
        }
        private void registrationFailed(ISipSession raw, int code, String message, boolean timeout) {
            synchronized (SdSipService.this) {
                Session registration = session(raw);
                wakeLock.release(owner);
                if (owner.closed) return;
                owner.error = code;
                owner.errorMessage = message;
                if (code == SipErrorCode.SOCKET_ERROR || code == SipErrorCode.DATA_CONNECTION_LOST) {
                    owner.stopKeepAlive();
                    owner.group.close();
                    owner.registeredUntil = 0;
                    wakeLock.release(owner.receiveOwner);
                }
                if (timeout) {
                    registration.callback.onRegistrationTimeout(registration);
                    if (registration.automatic) owner.registration.onRegistrationTimeout(registration);
                } else {
                    registration.callback.onRegistrationFailed(registration, code, message);
                    if (registration.automatic) owner.registration.onRegistrationFailed(registration, code, message);
                }
                if (code != SipErrorCode.INVALID_CREDENTIALS && code != SipErrorCode.CROSS_DOMAIN_AUTHENTICATION) owner.retry();
                if (!registration.automatic) { owner.sessions.remove(raw.asBinder()); registration.unlinkListener(); }
                System.err.println("SDSIP=registration_failed|code=" + code);
            }
        }
        @Override public void onRegistrationFailed(ISipSession raw, int code, String message) {
            registrationFailed(raw, code, message, false);
        }
        @Override public void onRegistrationTimeout(ISipSession raw) {
            registrationFailed(raw, SipErrorCode.TIME_OUT, "SIP registration timed out", true);
        }
    }

    /** Resolve the shared endpoint again after its owning process exits. */
    private static final class Client extends ISipService.Stub {
        private ISipService endpoint;
        private synchronized ISipService service() throws RemoteException {
            if (!SdKernelServices.enabled()) {
                if (local == null) local = new SdSipService();
                return local;
            }
            if (endpoint != null && endpoint.asBinder().isBinderAlive()) return endpoint;
            String name = "saidroid.sip." + SdApkPackage.NAME;
            IBinder shared = SdKernelServices.registry().checkService(name);
            if (shared == null) {
                SdSipService candidate = new SdSipService();
                try {
                    SdKernelServices.registry().addService(name, candidate, false, 0);
                    shared = candidate;
                } catch (IllegalStateException raced) {
                    shared = SdKernelServices.registry().checkService(name);
                    if (shared == null) throw raced;
                }
            }
            endpoint = ISipService.Stub.asInterface(shared);
            return endpoint;
        }
        @Override public void open(SipProfile profile, String owner) throws RemoteException { service().open(profile, owner); }
        @Override public void open3(SipProfile profile, PendingIntent incoming, ISipSessionListener listener, String owner) throws RemoteException { service().open3(profile, incoming, listener, owner); }
        @Override public void close(String uri, String owner) throws RemoteException { service().close(uri, owner); }
        @Override public boolean isOpened(String uri, String owner) throws RemoteException { return service().isOpened(uri, owner); }
        @Override public boolean isRegistered(String uri, String owner) throws RemoteException { return service().isRegistered(uri, owner); }
        @Override public void setRegistrationListener(String uri, ISipSessionListener listener, String owner) throws RemoteException { service().setRegistrationListener(uri, listener, owner); }
        @Override public ISipSession createSession(SipProfile profile, ISipSessionListener listener, String owner) throws RemoteException { return service().createSession(profile, listener, owner); }
        @Override public ISipSession getPendingSession(String id, String owner) throws RemoteException { return service().getPendingSession(id, owner); }
        @Override public SipProfile[] getListOfProfiles(String owner) throws RemoteException { return service().getListOfProfiles(owner); }
    }

    static String obfuscateSipUri(String uri) { return "[SIP account]"; }
}
