import java.net.*;
import java.util.*;
import java.util.concurrent.*;
import javax.net.ssl.*;

/** Independent ALPN/data/hostname contract over the actual unchanged APK's certificate fixture. */
public final class TlsApplicationProtocolContract {
    private static int checks;
    private static void check(boolean value, String reason) {
        checks++; if (!value) throw new AssertionError(reason);
    }
    public static void run(ClassLoader loader) throws Exception {
        SSLParameters values = new SSLParameters();
        check(values.getApplicationProtocols().length == 0, "default protocols");
        String[] input = {"h2", "http/1.1"}; values.setApplicationProtocols(input);
        input[0] = "mutated-input";
        check(Arrays.equals(values.getApplicationProtocols(), new String[]{"h2", "http/1.1"}), "input array copy");
        String[] output = values.getApplicationProtocols(); output[0] = "mutated-output";
        check("h2".equals(values.getApplicationProtocols()[0]), "output array copy");
        for (String[] bad : new String[][]{null, {null}, {""}, {"http/1.1", ""}}) {
            try { values.setApplicationProtocols(bad); throw new AssertionError("invalid protocols accepted"); }
            catch (IllegalArgumentException expected) { checks++; }
            check(Arrays.equals(values.getApplicationProtocols(), new String[]{"h2", "http/1.1"}), "failed setter changed state");
        }
        Class<?> fixtureType = Class.forName("libcore.javax.net.ssl.TestSSLContext", true, loader);
        for (int round = 0; round < 2; round++) {
            Object fixture = fixtureType.getMethod("create").invoke(null);
            SSLContext clientContext = (SSLContext) fixtureType.getField("clientContext").get(fixture);
            SSLContext serverContext = (SSLContext) fixtureType.getField("serverContext").get(fixture);
            SSLServerSocket listener = (SSLServerSocket) fixtureType.getField("serverSocket").get(fixture);
            listener.setSoTimeout(5000);
            SSLParameters serverParameters = listener.getSSLParameters();
            serverParameters.setApplicationProtocols(new String[]{"h2", "http/1.1"});
            listener.setSSLParameters(serverParameters);
            check(clientContext.getProvider().getName().equals("AndroidOpenSSL")
                    && serverContext.getProvider().getName().equals("AndroidOpenSSL"), "actual platform providers");
            ExecutorService worker = Executors.newSingleThreadExecutor();
            Future<String> server = worker.submit(() -> {
                try (SSLSocket socket = (SSLSocket) listener.accept()) {
                    socket.setSoTimeout(5000);
                    SSLParameters acceptedParameters = socket.getSSLParameters();
                    acceptedParameters.setApplicationProtocols(new String[]{"h2", "http/1.1"});
                    socket.setSSLParameters(acceptedParameters); socket.startHandshake();
                    if (socket.getInputStream().read() != 41) throw new AssertionError("encrypted request data");
                    socket.getOutputStream().write(42); socket.getOutputStream().flush();
                    if ("SSL_NULL_WITH_NULL_NULL".equals(socket.getSession().getCipherSuite()))
                        throw new AssertionError("actual negotiated TLS cipher");
                    return socket.getApplicationProtocol();
                }
            });
            try (SSLSocket client = (SSLSocket) clientContext.getSocketFactory().createSocket(
                    "localhost", listener.getLocalPort())) {
                client.setSoTimeout(5000);
                SSLParameters parameters = client.getSSLParameters();
                parameters.setEndpointIdentificationAlgorithm("HTTPS");
                parameters.setApplicationProtocols(new String[]{"http/1.1", "h2"});
                client.setSSLParameters(parameters);
                check(client.getApplicationProtocol() == null, "before-handshake ALPN undecided");
                client.startHandshake();
                System.out.println("TLS_ALPN_OBSERVED|client=" + client.getApplicationProtocol() + "|clientClass=" + client.getClass().getName() + "|configured=" + Arrays.toString(client.getSSLParameters().getApplicationProtocols()));
                check("h2".equals(client.getApplicationProtocol()), "real server-priority ALPN h2");
                check("HTTPS".equals(client.getSSLParameters().getEndpointIdentificationAlgorithm()), "hostname checks retained");
                check(client.getSession().getPeerCertificates().length > 0, "actual trusted peer chain");
                check(!"SSL_NULL_WITH_NULL_NULL".equals(client.getSession().getCipherSuite()), "real client cipher");
                client.getOutputStream().write(41); client.getOutputStream().flush();
                check(client.getInputStream().read() == 42, "real encrypted response data");
                check("h2".equals(server.get(5, TimeUnit.SECONDS)), "both real peers agree ALPN");
            } finally {
                worker.shutdownNow(); listener.close(); fixtureType.getMethod("close").invoke(fixture);
                check(worker.awaitTermination(5, TimeUnit.SECONDS), "owned worker terminated");
            }
        }
        System.out.println("TLS_APPLICATION_PROTOCOL_CONTRACT=PASS|checks=" + checks
                + "|real_alpn_rounds=2|protocol=h2|encrypted_data=true|endpoint_identification=HTTPS|trust=original-platform-fixture");
    }
}
