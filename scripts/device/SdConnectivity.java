import android.net.*;
import android.os.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;

/** Read-only view of host Linux links and routes. */
public final class SdConnectivity implements InvocationHandler {
    interface HostProvider { List<Link> read() throws IOException; }

    private static final SdConnectivity INSTANCE = new SdConnectivity();
    private static final long POLL_MS = 1000;
    private static final int MAX_REGISTRATIONS = 100;
    private final Binder binder = new Binder();
    private final IConnectivityManager service;
    private final HostProvider provider;
    private final Object state = new Object();
    private final Map<Integer, Subscription> registrations = new LinkedHashMap<Integer, Subscription>();
    private ScheduledThreadPoolExecutor worker;
    private ScheduledFuture<?> nextPoll;
    private int nextRequest = 1;

    private static final class LinuxLinks implements HostProvider {
        private final SdHostNetworkObservation host = new SdHostNetworkObservation();
        public List<Link> read() throws IOException {
            SdConnectivitySnapshot snapshot = host.read();
            List<Link> links = new ArrayList<Link>();
            for (SdConnectivitySnapshot.Link observed : snapshot.links.values()) {
                Link link = new Link();
                link.iface = java.net.NetworkInterface.getByName(observed.name);
                if (link.iface == null || link.iface.getIndex() != observed.index)
                    throw new IOException("Host interface changed during observation");
                link.type = observed.type;
                link.defaultRoute = snapshot.active != null && snapshot.active == observed.id;
                link.networkId = link.defaultRoute ? 0 : observed.id;
                link.observedProperties = observed.properties;
                link.observedCapabilities = observed.capabilities;
                links.add(link);
            }
            return links;
        }
    }

    private static final class NetworkThreads implements ThreadFactory {
        public Thread newThread(Runnable task) {
            Thread thread = new Thread(task, "saildroid-connectivity");
            thread.setDaemon(true);
            return thread;
        }
    }

    private final class Sample implements Runnable {
        final ScheduledThreadPoolExecutor owner;
        Sample(ScheduledThreadPoolExecutor owner) { this.owner = owner; }
        public void run() { tick(owner); }
    }

    private SdConnectivity() {
        this(new LinuxLinks());
    }

    SdConnectivity(HostProvider provider) {
        this.provider = provider;
        service = (IConnectivityManager) java.lang.reflect.Proxy.newProxyInstance(IConnectivityManager.class.getClassLoader(),
                new Class<?>[]{IConnectivityManager.class}, this);
        binder.attachInterface(service, "android.net.IConnectivityManager");
    }

    public static IBinder binder() { return INSTANCE.binder; }

    private static final class Link {
        java.net.NetworkInterface iface;
        int type;
        boolean defaultRoute;
        int networkId;
        LinkProperties observedProperties;
        NetworkCapabilities observedCapabilities;

        Network network() { return new Network(networkId); }

        NetworkInfo info() {
            NetworkInfo result = new NetworkInfo(type, 0,
                    type == ConnectivityManager.TYPE_WIFI ? "WIFI" : type == ConnectivityManager.TYPE_MOBILE ? "MOBILE" : "ETHERNET", "");
            result.setIsAvailable(true);
            result.setDetailedState(NetworkInfo.DetailedState.CONNECTED, null, iface.getName());
            return result;
        }

        LinkProperties properties() {
            if (observedProperties != null) return new LinkProperties(observedProperties);
            LinkProperties value = new LinkProperties();
            value.setInterfaceName(iface.getName());
            for (java.net.InterfaceAddress address : iface.getInterfaceAddresses()) {
                if (address.getAddress() != null)
                    value.addLinkAddress(new LinkAddress(address.getAddress(), address.getNetworkPrefixLength()));
            }
            return value;
        }

        NetworkCapabilities capabilities() {
            if (observedCapabilities != null) return new NetworkCapabilities(observedCapabilities);
            NetworkCapabilities value = new NetworkCapabilities();
            value.addTransportType(type == ConnectivityManager.TYPE_WIFI ? NetworkCapabilities.TRANSPORT_WIFI
                    : type == ConnectivityManager.TYPE_MOBILE ? NetworkCapabilities.TRANSPORT_CELLULAR : NetworkCapabilities.TRANSPORT_ETHERNET);
            value.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_RESTRICTED);
            value.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED);
            if (defaultRoute) value.addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
            if (type != ConnectivityManager.TYPE_MOBILE) value.addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
            return value;
        }

        String identity() { return iface.getIndex() + "/" + iface.getName() + "/" + networkId; }
    }

    private static List<Link> links() throws IOException {
        Set<String> defaults = new HashSet<String>();
        String preferred = null;
        long bestMetric = Long.MAX_VALUE;
        try (BufferedReader input = new BufferedReader(new FileReader("/proc/net/route"))) {
            String line;
            while ((line = input.readLine()) != null) {
                String[] fields = line.trim().split("\\s+");
                if (fields.length < 8 || !fields[1].equals("00000000") || !fields[7].equals("00000000")) continue;
                if ((Integer.parseInt(fields[3], 16) & 1) == 0) continue;
                defaults.add(fields[0]);
                long metric = Long.parseLong(fields[6]);
                if (metric < bestMetric) { bestMetric = metric; preferred = fields[0]; }
            }
        }
        List<Link> result = new ArrayList<Link>();
        Enumeration<java.net.NetworkInterface> all = java.net.NetworkInterface.getNetworkInterfaces();
        if (all != null) while (all.hasMoreElements()) {
            java.net.NetworkInterface iface = all.nextElement();
            if (!iface.isUp() || iface.isLoopback() || !iface.getInetAddresses().hasMoreElements()) continue;
            Link link = new Link();
            link.iface = iface;
            link.networkId = iface.getIndex();
            String name = iface.getName();
            link.type = name.startsWith("wlan") || name.startsWith("wl") ? ConnectivityManager.TYPE_WIFI
                    : name.startsWith("rmnet") || name.startsWith("wwan") ? ConnectivityManager.TYPE_MOBILE : ConnectivityManager.TYPE_ETHERNET;
            link.defaultRoute = defaults.contains(name);
            link.observedProperties = link.properties();
            link.observedCapabilities = link.capabilities();
            if (name.equals(preferred)) result.add(0, link);
            else result.add(link);
        }
        // Network zero uses the host's selected default route and resolver.
        // Other links retain their identities and explicit-network DNS restrictions.
        Link selected = active(result);
        if (selected != null) selected.networkId = 0;
        return result;
    }

    private static Link active(List<Link> links) {
        for (Link link : links) if (link.defaultRoute) return link;
        return null;
    }

    private final class Subscription implements IBinder.DeathRecipient {
        final NetworkRequest request;
        final Messenger messenger;
        final IBinder token;
        final long deadline;
        Map<String, Link> matched = new LinkedHashMap<String, Link>();
        boolean linked;
        boolean available;

        Subscription(NetworkRequest request, Messenger messenger, IBinder token, int timeout) {
            this.request = request;
            this.messenger = messenger;
            this.token = token;
            deadline = timeout == 0 ? Long.MAX_VALUE : SystemClock.elapsedRealtime() + timeout;
        }

        public void binderDied() { remove(this); }
    }

    private static void validateCapabilities(NetworkCapabilities caps) {
        if (caps.getNetworkSpecifier() != null)
            throw new UnsupportedOperationException("Host network specifiers unavailable");
        Set<UidRange> uids = caps.getUids();
        if (uids != null) for (UidRange range : uids) {
            if (range.start != android.os.Process.myUid() || range.stop != android.os.Process.myUid())
                throw new SecurityException("Cross-UID network requests unavailable");
        }
    }

    private NetworkRequest register(NetworkCapabilities caps, Messenger messenger, IBinder token,
            NetworkRequest.Type type, int timeout, int legacyType) throws RemoteException {
        if (messenger == null || token == null) throw new NullPointerException("Network callback transport missing");
        if (timeout < 0) throw new IllegalArgumentException("Negative network request timeout");
        NetworkCapabilities copy = caps == null ? new NetworkCapabilities() : new NetworkCapabilities(caps);
        validateCapabilities(copy);
        copy.setSingleUid(android.os.Process.myUid());
        synchronized (state) {
            if (registrations.size() >= MAX_REGISTRATIONS)
                throw new ServiceSpecificException(ConnectivityManager.Errors.TOO_MANY_REQUESTS);
            if (nextRequest == Integer.MAX_VALUE) throw new IllegalStateException("Network request identity exhausted");
            NetworkRequest request = new NetworkRequest(copy, legacyType, nextRequest++, type);
            Subscription registration = new Subscription(request, messenger, token, timeout);
            registrations.put(request.requestId, registration);
            try { token.linkToDeath(registration, 0); registration.linked = true; }
            catch (RemoteException failure) { remove(registration); throw failure; }
            if (registrations.get(request.requestId) != registration)
                throw new RemoteException("Network callback token died during registration");
            if (worker == null) {
                worker = new ScheduledThreadPoolExecutor(1, new NetworkThreads());
                worker.setRemoveOnCancelPolicy(true);
            }
            System.err.println("SDCONNECTIVITY=registered|request=" + request.requestId + "|type=" + type + "|caps=" + copy);
            scheduleLocked(0);
            // ConnectivityManager holds its callbacks-map lock across this call.
            // Its handler cannot consume the initial event before registering this copy.
            return new NetworkRequest(request);
        }
    }

    private void scheduleLocked(long delay) {
        if (worker == null || registrations.isEmpty()) return;
        if (nextPoll != null) {
            if (delay != 0) return;
            nextPoll.cancel(false);
        }
        final ScheduledThreadPoolExecutor owner = worker;
        nextPoll = owner.schedule(new Sample(owner), delay, TimeUnit.MILLISECONDS);
    }

    private void remove(Subscription registration) {
        synchronized (state) {
            if (registrations.get(registration.request.requestId) != registration) return;
            registrations.remove(registration.request.requestId);
            registration.matched.clear();
            if (registration.linked) {
                registration.linked = false;
                try { registration.token.unlinkToDeath(registration, 0); } catch (NoSuchElementException ignored) { }
            }
            if (registrations.isEmpty() && worker != null) {
                if (nextPoll != null) nextPoll.cancel(false);
                nextPoll = null;
                worker.shutdown();
                worker = null;
            }
        }
    }

    private void release(NetworkRequest request) {
        if (request == null) throw new NullPointerException("NetworkRequest missing");
        synchronized (state) {
            Subscription registration = registrations.get(request.requestId);
            if (registration == null) return;
            if (!registration.request.equals(request)) throw new SecurityException("Network request identity mismatch");
            remove(registration);
        }
    }

    private Map<String, Link> matching(Subscription registration, List<Link> observed) {
        Map<String, Link> result = new LinkedHashMap<String, Link>();
        Link selected = active(observed);
        if (registration.request.type == NetworkRequest.Type.TRACK_DEFAULT) {
            if (selected != null) result.put(selected.identity(), selected);
            return result;
        }
        NetworkCapabilities caps = registration.request.networkCapabilities;
        if (registration.request.type == NetworkRequest.Type.REQUEST && selected != null
                && caps.satisfiedByNetworkCapabilities(selected.capabilities())) {
            result.put(selected.identity(), selected);
            return result;
        }
        for (Link link : observed) if (caps.satisfiedByNetworkCapabilities(link.capabilities())) {
            result.put(link.identity(), link);
            if (registration.request.type == NetworkRequest.Type.REQUEST) break;
        }
        return result;
    }

    private void tick(ScheduledThreadPoolExecutor owner) {
        synchronized (state) {
            if (worker != owner || registrations.isEmpty()) return;
            nextPoll = null;
        }
        List<Link> observed = null;
        try { observed = provider.read(); }
        catch (IOException failure) { System.err.println("SDCONNECTIVITY=sample_failed|error=" + failure); }
        synchronized (state) {
            if (worker != owner) return;
            long delay = POLL_MS;
            for (Subscription registration : new ArrayList<Subscription>(registrations.values())) {
                if (observed != null) {
                    Map<String, Link> matched = matching(registration, observed);
                    for (Map.Entry<String, Link> old : new LinkedHashMap<String, Link>(registration.matched).entrySet()) {
                        if (!matched.containsKey(old.getKey())) send(registration, ConnectivityManager.CALLBACK_LOST, old.getValue());
                    }
                    for (Map.Entry<String, Link> entry : matched.entrySet()) {
                        Link link = entry.getValue();
                        Link old = registration.matched.get(entry.getKey());
                        if (old == null) send(registration, ConnectivityManager.CALLBACK_AVAILABLE, link);
                        else {
                            if (!old.capabilities().equals(link.capabilities())) send(registration, ConnectivityManager.CALLBACK_CAP_CHANGED, link);
                            LinkProperties before = old.properties(), after = link.properties();
                            if (!before.equals(after) || !before.getLinkAddresses().equals(after.getLinkAddresses()))
                                send(registration, ConnectivityManager.CALLBACK_IP_CHANGED, link);
                        }
                    }
                    registration.matched = matched;
                    registration.available |= !matched.isEmpty();
                }
                if (!registration.available && registration.deadline != Long.MAX_VALUE) {
                    long remaining = registration.deadline - SystemClock.elapsedRealtime();
                    if (remaining <= 0) {
                        send(registration, ConnectivityManager.CALLBACK_UNAVAIL, null);
                        remove(registration);
                    } else delay = Math.min(delay, remaining);
                }
            }
            scheduleLocked(delay);
        }
    }

    // Called under state so release/death cannot race a queued notification.
    private void send(Subscription registration, int type, Link link) {
        if (registrations.get(registration.request.requestId) != registration) return;
        Bundle bundle = new Bundle();
        bundle.putParcelable("NetworkRequest", new NetworkRequest(registration.request));
        if (link != null) {
            bundle.putParcelable("Network", link.network());
            if (type == ConnectivityManager.CALLBACK_AVAILABLE || type == ConnectivityManager.CALLBACK_CAP_CHANGED)
                bundle.putParcelable("NetworkCapabilities", link.capabilities());
            if (type == ConnectivityManager.CALLBACK_AVAILABLE || type == ConnectivityManager.CALLBACK_IP_CHANGED)
                bundle.putParcelable("LinkProperties", link.properties());
        }
        Message message = Message.obtain();
        message.what = type;
        message.setData(bundle);
        try {
            registration.messenger.send(message);
            System.err.println("SDCONNECTIVITY=event|request=" + registration.request.requestId + "|what=" + type
                    + "|network=" + (link == null ? "none" : link.network()));
        } catch (RemoteException dead) { remove(registration); }
    }

    @Override public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        String name = method.getName();
        if (name.equals("asBinder")) return binder;
        if (name.equals("toString")) return "SailDroid host connectivity";
        if (name.equals("hashCode")) return System.identityHashCode(proxy);
        if (name.equals("equals")) return proxy == args[0];
        if (name.equals("requestNetwork")) return register((NetworkCapabilities) args[0], (Messenger) args[1], (IBinder) args[3],
                args[0] == null ? NetworkRequest.Type.TRACK_DEFAULT : NetworkRequest.Type.REQUEST, (Integer) args[2], (Integer) args[4]);
        if (name.equals("listenForNetwork")) {
            if (args[0] == null) throw new NullPointerException("NetworkCapabilities missing");
            return register((NetworkCapabilities) args[0], (Messenger) args[1], (IBinder) args[2], NetworkRequest.Type.LISTEN, 0, ConnectivityManager.TYPE_NONE);
        }
        if (name.equals("releaseNetworkRequest")) { release((NetworkRequest) args[0]); return null; }
        if (name.equals("getGlobalProxy") || name.equals("getProxyForNetwork")) return null;
        if (name.equals("isTetheringSupported")) return false;
        if (name.equals("isNetworkSupported")) {
            int type = (Integer) args[0];
            return type == ConnectivityManager.TYPE_WIFI || type == ConnectivityManager.TYPE_MOBILE || type == ConnectivityManager.TYPE_ETHERNET;
        }
        List<Link> links = provider.read();
        Link selected = active(links);
        if (name.equals("getNetworkInfoForUid")) {
            if ((Integer) args[1] != android.os.Process.myUid()) throw new SecurityException("Cross-user network query unavailable");
            for (Link link : links) if (link.network().equals(args[0])) return link.info();
            return null;
        }
        if (name.equals("getActiveNetworkForUid") || name.equals("getActiveNetworkInfoForUid")) {
            if ((Integer) args[0] != android.os.Process.myUid()) throw new SecurityException("Cross-user network query unavailable");
            if (selected == null) return null;
            return name.equals("getActiveNetworkForUid") ? selected.network() : selected.info();
        }
        if (name.equals("getActiveNetwork")) return selected == null ? null : selected.network();
        if (name.equals("getActiveNetworkInfo")) return selected == null ? null : selected.info();
        if (name.equals("getActiveLinkProperties")) return selected == null ? null : selected.properties();
        if (name.equals("isActiveNetworkMetered")) return selected == null
                || !selected.capabilities().hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
        if (name.equals("getAllNetworks")) {
            Network[] result = new Network[links.size()];
            for (int i = 0; i < links.size(); i++) result[i] = links.get(i).network();
            return result;
        }
        if (name.equals("getAllNetworkInfo")) {
            NetworkInfo[] result = new NetworkInfo[links.size()];
            for (int i = 0; i < links.size(); i++) result[i] = links.get(i).info();
            return result;
        }
        if (name.equals("getNetworkInfo") || name.equals("getNetworkForType") || name.equals("getLinkPropertiesForType")) {
            for (Link link : links) if (link.type == (Integer) args[0])
                return name.equals("getNetworkInfo") ? link.info() : name.equals("getNetworkForType") ? link.network() : link.properties();
            return null;
        }
        if (name.equals("getNetworkInfoForNetwork") || name.equals("getLinkProperties") || name.equals("getNetworkCapabilities")) {
            for (Link link : links) if (link.network().equals(args[0]))
                return name.equals("getNetworkInfoForNetwork") ? link.info() : name.equals("getLinkProperties") ? link.properties() : link.capabilities();
            return null;
        }
        throw SdRuntimeDiagnostics.unsupported("Host connectivity", method);
    }
}
