#!/usr/bin/env python3
"""Exercise API28 host network subscriptions with deterministic host observations."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


PROBE = r'''
import android.net.*;
import android.os.*;
import java.io.IOException;
import java.lang.reflect.Field;
import java.net.NetworkInterface;
import java.util.*;
import java.util.concurrent.TimeUnit;

public class ConnectivityCallbacksProbe {
    static class Source implements SdConnectivity.HostProvider {
        volatile List<SdConnectivity.Link> value = Collections.emptyList();
        volatile boolean failing;
        public List<SdConnectivity.Link> read() throws IOException {
            if (failing) throw new IOException("fixture read failure");
            return value;
        }
    }
    static class Token extends Binder {
        IBinder.DeathRecipient recipient;
        boolean reject;
        public void linkToDeath(IBinder.DeathRecipient value, int flags) throws RemoteException {
            if (reject) throw new RemoteException("fixture dead token");
            recipient = value;
        }
        public boolean unlinkToDeath(IBinder.DeathRecipient value, int flags) {
            if (recipient != value) throw new AssertionError("Death recipient mismatch");
            recipient = null;
            return true;
        }
        void die() { recipient.binderDied(); }
    }
    static SdConnectivity.Link link(NetworkInterface iface, int id, boolean internet, boolean metered, int prefix) throws Exception {
        SdConnectivity.Link link = new SdConnectivity.Link();
        link.iface = iface; link.networkId = id; link.type = ConnectivityManager.TYPE_WIFI; link.defaultRoute = internet;
        link.observedCapabilities = new NetworkCapabilities();
        link.observedCapabilities.addTransportType(NetworkCapabilities.TRANSPORT_WIFI);
        if (internet) link.observedCapabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
        if (!metered) link.observedCapabilities.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
        link.observedProperties = new LinkProperties();
        link.observedProperties.setInterfaceName(iface.getName());
        link.observedProperties.addLinkAddress(new LinkAddress(java.net.InetAddress.getByAddress(new byte[]{(byte)192, 0, 2, 1}), prefix));
        return link;
    }
    static Message event(Messenger messenger, int what) throws Exception {
        Message message = messenger.messages.poll(4, TimeUnit.SECONDS);
        if (message == null || message.what != what) throw new AssertionError("Expected event " + what + ", got " + (message == null ? "none" : message.what));
        if (message.getData().getParcelable("NetworkRequest") == null) throw new AssertionError("Missing callback request");
        if (what == ConnectivityManager.CALLBACK_AVAILABLE && (message.getData().getParcelable("Network") == null
                || message.getData().getParcelable("NetworkCapabilities") == null || message.getData().getParcelable("LinkProperties") == null))
            throw new AssertionError("Incomplete API28 available event");
        return message;
    }
    static void quiet(Messenger messenger) throws Exception {
        if (messenger.messages.poll(1300, TimeUnit.MILLISECONDS) != null) throw new AssertionError("Unexpected duplicate/post-release event");
    }
    public static void main(String[] args) throws Exception {
        NetworkInterface iface = NetworkInterface.getNetworkInterfaces().nextElement();
        Source source = new Source(); SdConnectivity backend = new SdConnectivity(source);
        Field serviceField = SdConnectivity.class.getDeclaredField("service"); serviceField.setAccessible(true);
        IConnectivityManager service = (IConnectivityManager) serviceField.get(backend);
        NetworkCapabilities caps = new NetworkCapabilities(); caps.addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
        source.value = Arrays.asList(link(iface, 0, true, false, 24), link(iface, 2, true, false, 24));
        Messenger requestEvents = new Messenger(), listenEvents = new Messenger(), defaultEvents = new Messenger();
        Token requestToken = new Token(), listenToken = new Token(), defaultToken = new Token();
        NetworkRequest request = service.requestNetwork(caps, requestEvents, 5000, requestToken, ConnectivityManager.TYPE_NONE);
        NetworkRequest listen = service.listenForNetwork(caps, listenEvents, listenToken);
        NetworkRequest track = service.requestNetwork(null, defaultEvents, 0, defaultToken, ConnectivityManager.TYPE_NONE);
        if (request.type != NetworkRequest.Type.REQUEST || listen.type != NetworkRequest.Type.LISTEN || track.type != NetworkRequest.Type.TRACK_DEFAULT)
            throw new AssertionError("Request modes incorrect");
        if (request.requestId == listen.requestId || request.requestId == track.requestId) throw new AssertionError("Duplicate request identity");
        event(requestEvents, ConnectivityManager.CALLBACK_AVAILABLE);
        event(defaultEvents, ConnectivityManager.CALLBACK_AVAILABLE);
        event(listenEvents, ConnectivityManager.CALLBACK_AVAILABLE); event(listenEvents, ConnectivityManager.CALLBACK_AVAILABLE);
        quiet(requestEvents);
        source.value = Arrays.asList(link(iface, 0, true, true, 25), link(iface, 2, true, false, 24));
        event(requestEvents, ConnectivityManager.CALLBACK_CAP_CHANGED); event(requestEvents, ConnectivityManager.CALLBACK_IP_CHANGED);
        defaultEvents.messages.clear(); listenEvents.messages.clear();
        source.failing = true; quiet(requestEvents); source.failing = false;
        source.value = Collections.emptyList(); event(requestEvents, ConnectivityManager.CALLBACK_LOST);
        source.value = Arrays.asList(link(iface, 0, true, false, 24)); event(requestEvents, ConnectivityManager.CALLBACK_AVAILABLE);
        service.releaseNetworkRequest(request); service.releaseNetworkRequest(request); quiet(requestEvents);
        listenToken.die(); defaultToken.die();
        Messenger timeoutEvents = new Messenger(); NetworkCapabilities impossible = new NetworkCapabilities();
        impossible.addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR);
        service.requestNetwork(impossible, timeoutEvents, 100, new Token(), ConnectivityManager.TYPE_NONE);
        event(timeoutEvents, ConnectivityManager.CALLBACK_UNAVAIL); quiet(timeoutEvents);
        Token dead = new Token(); dead.reject = true;
        try { service.listenForNetwork(caps, new Messenger(), dead); throw new AssertionError("Dead token accepted"); }
        catch (RemoteException expected) { }
        Messenger broken = new Messenger(); broken.fail = true;
        service.listenForNetwork(caps, broken, new Token()); Thread.sleep(250);
        Field registrations = SdConnectivity.class.getDeclaredField("registrations"); registrations.setAccessible(true);
        Field worker = SdConnectivity.class.getDeclaredField("worker"); worker.setAccessible(true);
        Field state = SdConnectivity.class.getDeclaredField("state"); state.setAccessible(true);
        synchronized (state.get(backend)) {
            if (!((Map<?, ?>) registrations.get(backend)).isEmpty() || worker.get(backend) != null) throw new AssertionError("Subscription/worker leaked");
        }
        System.out.println("CONNECTIVITY_CALLBACKS=PASS|request_listen_default=true|dedup=true|changes=true|loss_recovery=true|timeout=true|death_release=true|worker_cleanup=true");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--classes', type=Path, required=True, action='append')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('check-text-services.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory(prefix='saildroid-connectivity-') as temporary:
        root = Path(temporary)
        definitions = [
            # Expose the private link representation only to this isolated fixture.
            ('SdConnectivity.java', Path(__file__).parents[1].joinpath('SdConnectivity.java').read_text().replace('private static final class Link', 'static final class Link')),
            ('android/system/OsConstants.java', 'package android.system; public class OsConstants { public static final int RT_SCOPE_HOST=254, RT_SCOPE_LINK=253, RT_SCOPE_SITE=200, RT_SCOPE_UNIVERSE=0, IFA_F_DADFAILED=8, IFA_F_DEPRECATED=32, IFA_F_TENTATIVE=64, IFA_F_OPTIMISTIC=4; }'),
            ('android/os/Binder.java', fixture.BINDER.replace('public void linkToDeath(DeathRecipient recipient, int flags)', 'public void linkToDeath(DeathRecipient recipient, int flags) throws RemoteException')),
            ('android/os/Process.java', 'package android.os; public class Process { public static int myUid() { return 100000; } }'),
            ('android/os/SystemClock.java', 'package android.os; public class SystemClock { public static long elapsedRealtime() { return System.nanoTime()/1000000; } }'),
            ('android/os/SystemProperties.java', 'package android.os; public class SystemProperties { public static boolean getBoolean(String k, boolean v) { return v; } }'),
            ('android/os/Bundle.java', 'package android.os; import java.util.*; public class Bundle { private final Map<String,Parcelable> values = new HashMap<String,Parcelable>(); public void putParcelable(String k, Parcelable v) { values.put(k,v); } public Parcelable getParcelable(String k) { return values.get(k); } }'),
            ('android/os/Message.java', 'package android.os; public class Message { public int what; private Bundle data; public static Message obtain() { return new Message(); } public void setData(Bundle v) { data=v; } public Bundle getData() { return data; } }'),
            ('android/os/Messenger.java', 'package android.os; import java.util.concurrent.*; public class Messenger { public final BlockingQueue<Message> messages = new LinkedBlockingQueue<Message>(); public boolean fail; public void send(Message m) throws RemoteException { if(fail) throw new RemoteException("fixture transport dead"); messages.add(m); } }'),
            ('SdRuntimeDiagnostics.java', 'public class SdRuntimeDiagnostics { public static UnsupportedOperationException unsupported(String o, java.lang.reflect.Method m) { return new UnsupportedOperationException(o+" "+m); } }'),
            ('ConnectivityCallbacksProbe.java', PROBE),
        ]
        sources = []
        for name, code in definitions:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        classes = root / 'classes'
        classes.mkdir()
        classpath = os.pathsep.join(map(str, [*args.classes, args.framework]))
        subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-classpath', classpath,
                        '-d', str(classes), *map(str, sources)], check=True)
        subprocess.run(['java', '-classpath', str(classes) + os.pathsep + classpath, 'ConnectivityCallbacksProbe'], check=True, timeout=45)


if __name__ == '__main__':
    main()
