import android.app.ActivityManager;
import android.app.ActivityThread;
import android.app.Application;
import android.app.PendingIntent;
import android.content.Context;
import android.content.IIntentReceiver;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.AudioManager;
import android.net.rtp.AudioCodec;
import android.net.rtp.AudioGroup;
import android.net.rtp.AudioStream;
import android.net.rtp.RtpStream;
import android.net.sip.SipAudioCall;
import android.net.sip.SipErrorCode;
import android.net.sip.SipManager;
import android.net.sip.SipProfile;
import android.net.sip.SipRegistrationListener;
import android.net.sip.SipSession;
import android.os.Bundle;
import android.os.Looper;
import android.os.Process;
import java.io.File;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.json.JSONArray;

/** Fixture setup is private. Every SIP operation uses the public SDK client. */
public final class SipContracts {
    private static final String PACKAGE = "org.saildroid.compat.sip";
    private static final String ACTION = PACKAGE + ".INCOMING";
    private static String host;
    private static int port;
    private static int controlPort;
    private static File folder;
    private static Context context;
    private static SipManager manager;
    private static final Set<String> opened = new LinkedHashSet<String>();
    private static final ArrayList<PendingIntent> tokens = new ArrayList<PendingIntent>();
    private static final LinkedBlockingQueue<Intent> incoming = new LinkedBlockingQueue<Intent>();
    private static int tests;

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void passed(String name) {
        tests++;
        System.out.println("COMPAT_EVENT=sip." + name + "|PASS|public=SipManager");
    }
    private static void field(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
    private static SipProfile local(String name, String transport, boolean auto) throws Exception {
        SipProfile profile = new SipProfile.Builder(name, host).setPort(port).setProtocol(transport)
                .setAuthUserName("fixture-auth").setPassword("fixture-password").setAutoRegistration(auto).build();
        opened.add(profile.getUriString());
        return profile;
    }
    private static SipProfile peer(String name) throws Exception {
        return new SipProfile.Builder(name, host).setPort(port).build();
    }
    private static String sdp(String attribute) {
        return "v=0\r\no=fixture 1 1 IN IP4 127.0.0.1\r\ns=SIP fixture\r\n"
                + "c=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 5004 RTP/AVP 0 8 101\r\n"
                + "a=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\na=rtpmap:101 telephone-event/8000\r\n"
                + attribute;
    }
    private static JSONObject control(String path, JSONObject request) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL("http://" + host + ':' + controlPort + path).openConnection();
        connection.setConnectTimeout(3000);
        connection.setReadTimeout(3000);
        if (request != null) {
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            byte[] data = request.toString().getBytes("UTF-8");
            connection.setFixedLengthStreamingMode(data.length);
            try (java.io.OutputStream output = connection.getOutputStream()) { output.write(data); }
        }
        try (java.io.InputStream input = connection.getInputStream()) {
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[1024];
            int count;
            while ((count = input.read(buffer)) >= 0) bytes.write(buffer, 0, count);
            return new JSONObject(bytes.toString("UTF-8"));
        } finally { connection.disconnect(); }
    }

    private static final class Registration implements SipRegistrationListener {
        final LinkedBlockingQueue<String> events = new LinkedBlockingQueue<String>();
        volatile int error;
        public void onRegistering(String uri) { events.add("registering"); }
        public void onRegistrationDone(String uri, long expiry) { events.add("done"); }
        public void onRegistrationFailed(String uri, int code, String message) { error = code; events.add("failed"); }
        void await(String wanted) throws Exception {
            long deadline = System.currentTimeMillis() + 12000;
            String event;
            do {
                event = events.poll(Math.max(1, deadline - System.currentTimeMillis()), TimeUnit.MILLISECONDS);
                check(event != null, "Registration callback missing " + wanted);
                if (!event.equals(wanted)) check(event.equals("registering"), "Registration failed while waiting for " + wanted + " code=" + error);
            } while (!event.equals(wanted));
        }
    }

    private static final class Call extends SipSession.Listener {
        final LinkedBlockingQueue<String> events = new LinkedBlockingQueue<String>();
        volatile int error;
        volatile String description;
        public void onCalling(SipSession session) { events.add("calling"); }
        public void onRingingBack(SipSession session) { events.add("ringing"); }
        public void onCallEstablished(SipSession session, String sdp) { description = sdp; events.add("established"); }
        public void onCallEnded(SipSession session) { events.add("ended"); }
        public void onCallBusy(SipSession session) { events.add("busy"); }
        public void onError(SipSession session, int code, String message) { error = code; events.add("error"); }
        public void onCallChangeFailed(SipSession session, int code, String message) { error = code; events.add("change-failed"); }
        void await(String wanted) throws Exception {
            long deadline = System.currentTimeMillis() + 10000;
            String event;
            do {
                event = events.poll(Math.max(1, deadline - System.currentTimeMillis()), TimeUnit.MILLISECONDS);
                check(event != null, "Call callback missing " + wanted);
                if (!event.equals(wanted)) check(event.equals("calling") || event.equals("ringing"),
                        "Unexpected call event " + event + " while waiting for " + wanted + " code=" + error);
            } while (!event.equals(wanted));
        }
    }

    private static void initialize(String mode, String[] arguments) throws Exception {
        host = arguments[1];
        port = Integer.parseInt(arguments[2]);
        controlPort = Integer.parseInt(arguments[3]);
        folder = new File(arguments[4]);
        System.setProperty("saidroid.package", PACKAGE);
        System.setProperty("saidroid.apk", new File(folder, "contracts.apk").toString());
        System.setProperty("saidroid.data", new File(folder, "app-data").toString());
        System.setProperty("saidroid.native", new File(folder, "empty-libs").toString());
        if (arguments.length > 5) System.setProperty("saidroid.binder.driver", arguments[5]);
        if (mode.equals("ipc-owner")) {
            System.setProperty("saidroid.service", PACKAGE + ".OwnerService");
            System.setProperty("saidroid.process", PACKAGE + ":sip_owner");
        }
        String driver = System.getProperty("saidroid.binder.driver");
        check(SdBridge.configurePrivateBinder(driver == null ? "/home/art/runtime/binder/binder" : driver),
                "Private Binder configuration failed");
        check(SdBridge.registerFrameworkNatives() == 97, "Private Binder JNI registration differs");
        Looper.prepareMainLooper();
        SdAudio.install();
        SdServices.installAll();
        SdServices.bindApplication(SdApkPackage.applicationInfo());
        if (mode.equals("registry")) {
            check(SdBridge.becomeBinderContextManager(new SdBinderRegistry()), "Private registry claim failed");
            SdBridge.startBinderPool();
            return;
        }
        SdAppPermissions permissions = new SdAppPermissions(SdApkPackage.APK, PACKAGE);
        HashMap<String, Boolean> grants = new HashMap<String, Boolean>();
        grants.put("android.permission.USE_SIP", true);
        permissions.decide(grants);
        Constructor<ActivityThread> constructor = ActivityThread.class.getDeclaredConstructor();
        constructor.setAccessible(true);
        ActivityThread thread = constructor.newInstance();
        field(thread, "mInstrumentation", new android.app.Instrumentation());
        Field current = ActivityThread.class.getDeclaredField("sCurrentActivityThread");
        current.setAccessible(true);
        current.set(null, thread);
        android.app.LoadedApk loaded = thread.getPackageInfoNoCheck(SdApkPackage.applicationInfo(),
                android.content.res.CompatibilityInfo.DEFAULT_COMPATIBILITY_INFO);
        java.lang.reflect.Method createContext = Class.forName("android.app.ContextImpl").getDeclaredMethod(
                "createAppContext", ActivityThread.class, android.app.LoadedApk.class);
        createContext.setAccessible(true);
        context = (Context) createContext.invoke(null, thread, loaded);
        Application application = android.app.Instrumentation.newApplication(Application.class, context);
        field(loaded, "mApplication", application);
        field(thread, "mInitialApplication", application);
        if (driver != null) { SdBridge.startBinderPool(); SdServiceEndpoint.publish(); }
        manager = SipManager.newInstance(context);
        check(manager != null && SipManager.isApiSupported(context), "SIP feature was not advertised");
    }

    private static PendingIntent receiveToken(int request) throws Exception {
        PendingIntent token = PendingIntent.getBroadcast(context, request, new Intent(ACTION).setPackage(PACKAGE), PendingIntent.FLAG_UPDATE_CURRENT);
        tokens.add(token);
        return token;
    }

    private static void registration(String transport) throws Exception {
        SipProfile profile = local("manual-" + transport.toLowerCase(), transport, false);
        Registration listener = new Registration();
        manager.register(profile, 30, listener);
        listener.await("done");
        check(manager.isOpened(profile.getUriString()) && manager.isRegistered(profile.getUriString()), "Manual registration state differs");
        for (SipProfile current : manager.getListOfProfiles()) check(current.getPassword() == null, "SIP password was exposed");
        passed("register-" + transport.toLowerCase() + "-digest");
        manager.unregister(profile, listener);
        listener.await("done");
        check(!manager.isRegistered(profile.getUriString()), "Deregistration left a registered profile");
        manager.close(profile.getUriString());
        check(!manager.isOpened(profile.getUriString()), "Close left an opened profile");
        passed("unregister-" + transport.toLowerCase());
    }

    private static void outgoing(SipProfile profile, String target, String result, int timeout) throws Exception {
        Call listener = new Call();
        SipSession session = manager.createSipSession(profile, listener);
        check(session != null && session.getLocalIp() != null, "SIP session IP missing");
        session.makeCall(peer(target), sdp(""), timeout);
        if (target.equals("cancel") || target.equals("late-answer")) { listener.await("ringing"); session.endCall(); }
        listener.await(result);
        if (result.equals("established")) {
            check(session.isInCall() && session.getState() == SipSession.State.IN_CALL, "Call state differs");
            check(listener.description.contains("m=audio") && session.getPeerProfile() != null, "Peer SDP/profile missing");
            check(session.getLocalProfile().getPassword() == null, "Session password was exposed");
            session.changeCall(sdp("a=sendonly\r\n"), 5);
            listener.await("established");
            session.changeCall(sdp("a=x-reject\r\n"), 5);
            listener.await("change-failed");
            check(session.isInCall() && session.getState() == SipSession.State.IN_CALL, "Failed SDP update destroyed the call");
            session.changeCall(sdp(""), 5);
            listener.await("established");
            session.endCall();
            listener.await("ended");
        } else if (target.contains("timeout")) check(listener.error == SipErrorCode.TIME_OUT, "Call timeout code differs");
        Thread.sleep(100);
        check(!session.isInCall(), "Terminal call still reports in-call");
        check(!listener.events.contains("established"), "Canceled call was established by a late answer");
        passed("call-" + target);
    }

    private static void incomingCalls() throws Exception {
        IIntentReceiver receiver = new IIntentReceiver.Stub() {
            public void performReceive(Intent intent, int code, String data, Bundle extras, boolean ordered, boolean sticky, int user) {
                incoming.add(new Intent(intent));
            }
        };
        ActivityManager.getService().registerReceiver(null, PACKAGE, receiver, new IntentFilter(ACTION), null, Process.myUid() / 100000, 0);
        try {
            SipProfile profile = local("alice", "UDP", true);
            Registration registration = new Registration();
            PendingIntent token = receiveToken(1);
            manager.open(profile, token, registration);
            registration.await("done");
            registration.await("done");
            check(manager.isRegistered(profile.getUriString()), "Automatic renewal lost registration");
            passed("automatic-renewal");
            JSONObject request = new JSONObject().put("user", "alice");
            String id = control("/incoming", request).getString("call_id");
            Intent intent = incoming.poll(5, TimeUnit.SECONDS);
            check(intent != null && SipManager.isIncomingCallIntent(intent) && id.equals(SipManager.getCallId(intent)), "Incoming PendingIntent missing");
            SipSession session = manager.getSessionFor(intent);
            check(session != null && manager.getSessionFor(intent) == null, "Incoming session was not consumed exactly once");
            check("incoming".equals(session.getPeerProfile().getUserName()), "Incoming peer differs");
            Call listener = new Call();
            session.setListener(listener);
            session.answerCall(sdp(""), 5);
            listener.await("established");
            control("/bye", new JSONObject().put("call_id", id));
            listener.await("ended");
            passed("incoming-answer-peer-bye");
            control("/incoming", request);
            intent = incoming.poll(5, TimeUnit.SECONDS);
            check(intent != null, "Rejected incoming Intent missing");
            session = manager.getSessionFor(intent);
            listener = new Call();
            session.setListener(listener);
            session.endCall();
            listener.await("ended");
            passed("incoming-reject");
            token.cancel();
            control("/incoming", request);
            check(incoming.poll(400, TimeUnit.MILLISECONDS) == null, "Canceled PendingIntent received a call");
            passed("canceled-incoming-token");
            manager.close(profile.getUriString());
        } finally { ActivityManager.getService().unregisterReceiver(receiver); }
    }

    private static void concurrentCalls(SipProfile profile) throws Exception {
        Call first = new Call();
        Call second = new Call();
        SipSession active = manager.createSipSession(profile, first);
        SipSession busy = manager.createSipSession(profile, second);
        active.makeCall(peer("peer"), sdp(""), 5);
        busy.makeCall(peer("busy"), sdp(""), 5);
        first.await("established");
        second.await("busy");
        check(active.isInCall() && !busy.isInCall(), "Concurrent SIP sessions affected each other");
        active.endCall();
        first.await("ended");
        passed("concurrent-calls");
    }

    private static void keepAlive() throws Exception {
        int before = control("/metrics", null).optInt("options");
        SipProfile profile = new SipProfile.Builder(local("keep-alive", "UDP", true)).setSendKeepAlive(true).build();
        Registration registration = new Registration();
        manager.open(profile, receiveToken(3), registration);
        registration.await("done");
        long deadline = System.currentTimeMillis() + 19000;
        while (control("/metrics", null).optInt("options") <= before && System.currentTimeMillis() < deadline) Thread.sleep(100);
        check(control("/metrics", null).optInt("options") > before, "SIP OPTIONS keepalive was not transmitted");
        manager.close(profile.getUriString());
        passed("options-keepalive");
    }

    private static void permissionRevocation() throws Exception {
        SdAppPermissions permissions = new SdAppPermissions(SdApkPackage.APK, PACKAGE);
        HashMap<String, Boolean> grants = new HashMap<String, Boolean>();
        grants.put("android.permission.USE_SIP", false);
        permissions.decide(grants);
        try {
            manager.getListOfProfiles();
            throw new AssertionError("Revoked SIP permission was accepted");
        } catch (SecurityException expected) {
            passed("permission-revocation");
        } finally {
            grants.put("android.permission.USE_SIP", true);
            permissions.decide(grants);
        }
        check(manager.getListOfProfiles().length == 0, "Revocation retained SIP profiles");
    }

    private static JSONObject mediaEvidence(int minimumPackets) throws Exception {
        long deadline = System.currentTimeMillis() + 5000;
        JSONObject evidence;
        do {
            evidence = control("/rtp", null);
            if (evidence.optInt("received_0") + evidence.optInt("received_8") >= minimumPackets
                    && evidence.optInt("playback_400hz_amplitude") > 300) return evidence;
            Thread.sleep(100);
        } while (System.currentTimeMillis() < deadline);
        throw new AssertionError("RTP media evidence missing " + evidence);
    }

    private static void rtpCodec(AudioCodec codec) throws Exception {
        control("/rtp/reset", new JSONObject());
        int rtpPort = control("/rtp", null).getInt("rtp_port");
        AudioStream stream = new AudioStream(java.net.InetAddress.getByName(host));
        AudioGroup group = new AudioGroup();
        try {
            stream.associate(java.net.InetAddress.getByName(host), rtpPort);
            stream.setCodec(codec);
            stream.setDtmfType(101);
            stream.join(group);
            group.setMode(AudioGroup.MODE_NORMAL);
            JSONObject evidence = mediaEvidence(16);
            check(evidence.optInt("microphone_non_silent") > 8, "RTP microphone tone was missing " + evidence);
            check(group.getStreams().length == 1, "RTP group membership differs");
            passed("rtp-" + codec.rtpmap.toLowerCase().replace('/', '-'));
            group.sendDtmf(5);
            Thread.sleep(350);
            check(control("/rtp", null).optInt("dtmf_5_end") > 0, "RFC2833 DTMF end packet missing");
            passed("rtp-dtmf-" + codec.type);
            control("/rtp/malformed", new JSONObject());
            int packets = control("/rtp", null).optInt("received_" + codec.type);
            evidence = mediaEvidence(packets + 8);
            check(evidence.optInt("malformed_batches") == 1, "Malformed RTP fixture was not sent");
            passed("rtp-malformed-" + codec.type);
            group.setMode(AudioGroup.MODE_MUTED);
            Thread.sleep(300);
            int nonSilent = control("/rtp", null).optInt("microphone_non_silent");
            Thread.sleep(800);
            evidence = control("/rtp", null);
            check(evidence.optInt("microphone_non_silent") == nonSilent && evidence.optInt("playback_400hz_amplitude") > 300,
                    "RTP mute failed " + evidence);
            check(evidence.optInt("capture_streams") == 1, "Muted RTP retained microphone capture");
            passed("rtp-mute-" + codec.type);
            group.setMode(AudioGroup.MODE_ON_HOLD);
            Thread.sleep(100);
            check(control("/rtp", null).optInt("playback_streams") == 0, "Held RTP retained playback");
            group.setMode(AudioGroup.MODE_ECHO_SUPPRESSION);
            check(group.getMode() == AudioGroup.MODE_ECHO_SUPPRESSION, "RTP echo-suppression mode differs");
            Thread.sleep(300);
            check(control("/rtp", null).optInt("capture_streams") == 2, "Resumed RTP capture missing");
            passed("rtp-hold-resume-" + codec.type);
            stream.join(null);
            stream.setMode(RtpStream.MODE_RECEIVE_ONLY);
            stream.join(group);
            Thread.sleep(300);
            nonSilent = control("/rtp", null).optInt("microphone_non_silent");
            Thread.sleep(800);
            check(control("/rtp", null).optInt("microphone_non_silent") == nonSilent, "Receive-only RTP sent microphone data");
            passed("rtp-receive-only-" + codec.type);
            stream.join(null);
            stream.setMode(RtpStream.MODE_SEND_ONLY);
            stream.join(group);
            Thread.sleep(1400);
            evidence = control("/rtp", null);
            check(evidence.optInt("microphone_non_silent") > nonSilent && evidence.optInt("playback_rms") < 50,
                    "Send-only RTP mode differs " + evidence);
            passed("rtp-send-only-" + codec.type);
        } finally {
            group.clear();
            stream.release();
        }
    }

    private static final class AudioCall extends SipAudioCall.Listener {
        final LinkedBlockingQueue<String> events = new LinkedBlockingQueue<String>();
        volatile int error;
        public void onCallEstablished(SipAudioCall call) { events.add("established"); }
        public void onCallHeld(SipAudioCall call) { events.add("held"); }
        public void onCallEnded(SipAudioCall call) { events.add("ended"); }
        public void onError(SipAudioCall call, int code, String message) { error = code; events.add("error"); }
        void await(String wanted) throws Exception {
            String actual = events.poll(10, TimeUnit.SECONDS);
            check(wanted.equals(actual), "SipAudioCall callback differs " + actual + " wanted=" + wanted + " code=" + error);
        }
    }

    private static void audioCall() throws Exception {
        control("/rtp/reset", new JSONObject());
        AudioCall listener = new AudioCall();
        SipAudioCall call = manager.makeAudioCall(local("audio-call", "UDP", false), peer("peer"), listener, 5);
        try {
            listener.await("established");
            call.startAudio();
            check(listener.error == 0 && call.isInCall() && call.getAudioStream().getGroup() != null,
                    "SipAudioCall startAudio failed code=" + listener.error);
            mediaEvidence(8);
            call.toggleMute();
            check(call.isMuted(), "SipAudioCall mute state differs");
            call.toggleMute();
            call.holdCall(5);
            listener.await("held");
            check(call.isOnHold(), "SipAudioCall hold state differs");
            call.continueCall(5);
            listener.await("established");
            check(!call.isOnHold(), "SipAudioCall resume state differs");
            call.startAudio();
            call.sendDtmf(4);
            Thread.sleep(350);
            check(control("/rtp", null).optInt("dtmf_4_end") > 0, "SipAudioCall DTMF was not transmitted");
            call.endCall();
            listener.await("ended");
            passed("audio-call-public-entry");
        } finally { call.close(); }
    }

    private static void media() throws Exception {
        JSONObject snapshot = new JSONObject(org.saildroid.host.HostApi.audioSnapshot());
        JSONArray inputs = snapshot.getJSONArray("inputs");
        boolean selected = false;
        for (int index = 0; index < inputs.length(); index++) {
            JSONObject input = inputs.getJSONObject(index);
            if (input.getString("name").equals("saildroid_sip_capture")) {
                check(!input.getBoolean("physical"), "Controlled source unexpectedly reports hardware");
                input.put("physical", true);
                selected = true;
            }
        }
        check(selected, "Controlled PulseAudio source missing");
        Field cached = SdAudio.class.getDeclaredField("snapshot");
        Field sampled = SdAudio.class.getDeclaredField("sampled");
        cached.setAccessible(true);
        sampled.setAccessible(true);
        Object previous = cached.get(null);
        long previousSampled = sampled.getLong(null);
        // Only the inaccessible boot-owned fixture authorizes its virtual source.
        cached.set(null, snapshot);
        sampled.setLong(null, android.os.SystemClock.uptimeMillis() + 60000);
        HashMap<String, Boolean> grants = new HashMap<String, Boolean>();
        grants.put("android.permission.RECORD_AUDIO", true);
        SdAppPermissions permissions = new SdAppPermissions(SdApkPackage.APK, PACKAGE);
        try {
            permissions.decide(grants);
            check(SipManager.isVoipSupported(context), "RTP backend feature missing");
            rtpCodec(AudioCodec.PCMU);
            rtpCodec(AudioCodec.PCMA);
            audioCall();
            int descriptors = new File("/proc/self/fd").list().length;
            for (int index = 0; index < 12; index++) {
                AudioStream stream = new AudioStream(java.net.InetAddress.getByName(host));
                AudioGroup group = new AudioGroup();
                stream.setCodec(AudioCodec.PCMU);
                stream.associate(java.net.InetAddress.getByName(host), control("/rtp", null).getInt("rtp_port"));
                stream.join(group);
                group.clear();
                stream.release();
            }
            check(new File("/proc/self/fd").list().length <= descriptors + 2, "RTP teardown leaked file descriptors");
            check(control("/rtp", null).optInt("playback_streams") == 0, "RTP teardown retained PulseAudio playback");
            passed("rtp-teardown");
            System.out.println("SIP_MEDIA_SOURCE=controlled-pipe-source|physical_microphone=false");
        } finally {
            grants.put("android.permission.RECORD_AUDIO", false);
            permissions.decide(grants);
            cached.set(null, previous);
            sampled.setLong(null, previousSampled);
        }
    }

    private static void suite() throws Exception {
        passed("feature-and-manager");
        AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        audio.setMode(AudioManager.MODE_IN_COMMUNICATION);
        check(audio.getMode() == AudioManager.MODE_IN_COMMUNICATION, "Communication mode was rejected");
        audio.setMode(AudioManager.MODE_NORMAL);
        check(audio.getMode() == AudioManager.MODE_NORMAL, "Communication mode was not released");
        passed("communication-mode");
        registration("UDP");
        registration("TCP");
        SipProfile bad = new SipProfile.Builder(local("bad-password", "UDP", false)).setPassword("incorrect-fixture-password").build();
        Registration failure = new Registration();
        manager.register(bad, 30, failure);
        failure.await("failed");
        check(failure.error == SipErrorCode.INVALID_CREDENTIALS, "Authentication failure code differs " + failure.error);
        passed("invalid-credentials");
        SipProfile profile = local("signal", "UDP", false);
        outgoing(profile, "peer", "established", -1);
        outgoing(profile, "authenticated", "established", 5);
        outgoing(profile, "pcma", "established", 5);
        outgoing(profile, "busy", "busy", 5);
        outgoing(profile, "decline", "error", 5);
        outgoing(profile, "cancel", "ended", 5);
        outgoing(profile, "late-answer", "ended", 5);
        outgoing(profile, "timeout", "error", 1);
        outgoing(profile, "ring-timeout", "error", 1);
        concurrentCalls(profile);
        incomingCalls();
        control("/fail-registration", new JSONObject());
        SipProfile retry = local("retry", "UDP", true);
        Registration registration = new Registration();
        manager.open(retry, receiveToken(2), registration);
        registration.await("failed");
        registration.await("done");
        check(manager.isRegistered(retry.getUriString()), "Automatic registration retry failed");
        passed("registration-retry");
        SipProfile closing = local("close-race", "UDP", false);
        SipSession queued = manager.createSipSession(closing, new Call());
        queued.makeCall(peer("cancel"), sdp(""), 5);
        manager.close(closing.getUriString());
        check(!manager.isOpened(closing.getUriString()), "Concurrent close left a profile");
        passed("queued-call-close");
        keepAlive();
        permissionRevocation();
        System.out.println("SIP_DEVICE_AUDIO=physical_microphone_available|value=" + SipManager.isVoipSupported(context));
    }

    public static void run(String[] arguments) throws Exception {
        String mode = arguments[0];
        try {
            initialize(mode, arguments);
            if (mode.equals("registry")) {
                Files.write(new File(folder, "registry-ready").toPath(), new byte[]{1});
                while (!new File(folder, "registry-stop").exists()) Thread.sleep(50);
            } else if (mode.equals("ipc-owner")) {
                manager.open(local("alice", "UDP", true));
                Files.write(new File(folder, "ipc-owner-ready").toPath(), new byte[]{1});
                while (!new File(folder, "ipc-owner-stop").exists()) Thread.sleep(50);
            } else if (mode.equals("media")) {
                media();
            } else {
                if (mode.equals("ipc-client")) {
                    check(manager.isOpened(local("alice", "UDP", true).getUriString()), "Shared owner profile missing");
                    passed("ipc-owner-profile");
                }
                suite();
            }
        } finally {
            if (manager != null) for (String uri : opened) manager.close(uri);
            for (PendingIntent token : tokens) token.cancel();
            Thread.sleep(4500);
        }
        System.out.println("COMPAT_SUITE=sip|tests=" + tests);
    }
}
