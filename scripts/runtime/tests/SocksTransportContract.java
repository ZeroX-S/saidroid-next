import java.io.*;
import java.net.*;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicReference;

/** Actual ART sockets: explicit relay, local bypass, opt-out, malformed config. */
public final class SocksTransportContract {
    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    private static byte[] read(InputStream input,int size)throws IOException {
        byte[] bytes=new byte[size];int offset=0;
        while(offset<size){int got=input.read(bytes,offset,size-offset);if(got<0)throw new EOFException();offset+=got;if(size>1024)System.err.println("SOCKS_FIXTURE_READ="+Thread.currentThread().getName()+"|bytes="+offset+"|target="+size);}
        return bytes;
    }
    private static void failedAddressFallback()throws Exception {
        final ServerSocket relay=new ServerSocket(0,2,InetAddress.getByName("127.0.0.1"));
        relay.setSoTimeout(4000);
        final AtomicReference<Throwable> failure=new AtomicReference<Throwable>();
        final java.util.concurrent.atomic.AtomicInteger connections=new java.util.concurrent.atomic.AtomicInteger();
        Thread server=new Thread(new Runnable(){public void run(){
            try {
                for(int attempt=0;attempt<2;attempt++)try(Socket peer=relay.accept()) {
                    peer.setSoTimeout(4000);InputStream input=peer.getInputStream();OutputStream output=peer.getOutputStream();
                    byte[] greeting=read(input,2);require(greeting[0]==5,"Fallback SOCKS version");read(input,greeting[1]&255);
                    output.write(new byte[]{5,0});output.flush();
                    require(Arrays.equals(read(input,4),new byte[]{5,1,0,1}),"Fallback CONNECT request");
                    byte[] wanted=new byte[]{(byte)198,51,100,(byte)(attempt==0?11:10)};
                    require(Arrays.equals(read(input,4),wanted),"Resolved address fallback order");
                    require(new DataInputStream(input).readUnsignedShort()==443,"Fallback port unchanged");
                    connections.incrementAndGet();
                    output.write(new byte[]{5,(byte)(attempt==0?1:0),0,1,0,0,0,0,0,0});output.flush();
                    if(attempt==1){require(input.read()==90,"Fallback real byte");output.write(90);output.flush();}
                }
            }catch(Throwable error){failure.set(error);}
        }});server.setDaemon(true);server.start();
        System.setProperty("socksProxyPort",Integer.toString(relay.getLocalPort()));
        java.lang.reflect.Constructor<Socket> constructor=Socket.class.getDeclaredConstructor(InetAddress[].class,int.class,SocketAddress.class,boolean.class);
        constructor.setAccessible(true);
        InetAddress[] addresses={InetAddress.getByAddress(new byte[]{(byte)198,51,100,11}),InetAddress.getByAddress(new byte[]{(byte)198,51,100,10})};
        try(Socket socket=constructor.newInstance(addresses,443,null,true)) {
            socket.setSoTimeout(4000);require(socket.isConnected(),"Second address connected");
            socket.getOutputStream().write(90);socket.getOutputStream().flush();require(socket.getInputStream().read()==90,"Second address byte roundtrip");
        }
        server.join(5000);relay.close();require(!server.isAlive(),"Fallback server ended");
        if(failure.get()!=null)throw new AssertionError(failure.get());
        require(connections.get()==2,"Both original resolved addresses attempted");
    }
    public static void main(String[] args)throws Exception {
        InetAddress loop=InetAddress.getByName("127.0.0.1");
        final ServerSocket relay=new ServerSocket(0,1,loop);
        final AtomicReference<Throwable> failure=new AtomicReference<Throwable>();
        final byte[] payload=new byte[65536];for(int i=0;i<payload.length;i++)payload[i]=(byte)i;
        Thread server=new Thread(new Runnable(){public void run(){
            try(Socket socket=relay.accept()) {
                socket.setSoTimeout(4000);InputStream input=socket.getInputStream();OutputStream output=socket.getOutputStream();
                byte[] greeting=read(input,2);require(greeting[0]==5,"SOCKS version");
                byte[] methods=read(input,greeting[1]&255);require(methods.length>0,"SOCKS methods");
                output.write(new byte[]{5,0});output.flush();
                byte[] request=read(input,4);require(Arrays.equals(request,new byte[]{5,1,0,1}),"Original IPv4 TCP CONNECT request");
                require(Arrays.equals(read(input,4),new byte[]{(byte)198,51,100,10}),"Original destination retained");
                require(new DataInputStream(input).readUnsignedShort()==443,"Original destination port retained");
                output.write(new byte[]{5,0,0,1,0,0,0,0,0,0});output.flush();
                byte[] received=read(input,payload.length);require(Arrays.equals(received,payload),"Unmodified client bytes");
                output.write(received);output.flush();
            }catch(Throwable error){error.printStackTrace();failure.set(error);}
        }});server.setDaemon(true);server.start();
        System.setProperty("socksProxyHost","127.0.0.1");
        System.setProperty("socksProxyPort",Integer.toString(relay.getLocalPort()));
        System.setProperty("saidroid.network.socks.enabled","true");
        try(Socket socket=new Socket()) {
            socket.connect(new InetSocketAddress("198.51.100.10",443),4000);
            socket.setSoTimeout(4000);socket.getOutputStream().write(payload);socket.getOutputStream().flush();
            require(Arrays.equals(read(socket.getInputStream(),payload.length),payload),"Unmodified response bytes");
        }
        server.join(5000);relay.close();require(!server.isAlive(),"Relay transaction ended");
        if(failure.get()!=null)throw new AssertionError(failure.get());
        failedAddressFallback();
        // A dead relay must not intercept an actual phone/VM loopback server.
        System.setProperty("socksProxyPort","1");
        try(ServerSocket local=new ServerSocket(0,1,loop);Socket socket=new Socket()) {
            socket.connect(new InetSocketAddress(loop,local.getLocalPort()),1000);
            try(Socket accepted=local.accept()){require(socket.isConnected(),"Loopback bypass");}
        }
        // Explicit NO_PROXY retains Java's standard direct-socket contract.
        try(ServerSocket local=new ServerSocket(0,1,loop);Socket socket=new Socket(Proxy.NO_PROXY)) {
            socket.connect(new InetSocketAddress(loop,local.getLocalPort()),1000);
            try(Socket accepted=local.accept()){require(socket.isConnected(),"Explicit direct socket");}
        }
        System.setProperty("socksProxyPort","0");
        try {new Socket();throw new AssertionError("Invalid relay accepted");}
        catch(IllegalArgumentException expected){}
        System.clearProperty("saidroid.network.socks.enabled");
        try(ServerSocket local=new ServerSocket(0,1,loop);Socket socket=new Socket()) {
            socket.connect(new InetSocketAddress(loop,local.getLocalPort()),1000);
            try(Socket accepted=local.accept()){require(socket.isConnected(),"Normal opt-out unaffected");}
        }
        System.out.println("SOCKS_TRANSPORT=PASS|original_destination=true|failed_address_fallback=passed|binary_bytes=65536|loopback=direct|explicit_no_proxy=direct|invalid=rejected|opt_out=direct");
    }
}
