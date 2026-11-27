import java.net.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import android.system.*;

/** Real Java/LinuxJNI private static-host lookup plus actual IPv4/IPv6 payload IO. */
public final class ComponentHostsContract {
    static int checks;
    static void require(boolean v,String reason){if(!v)throw new AssertionError(reason);checks++;}
    public static void run()throws Exception{
        String original=new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get("/etc/hosts")),"UTF-8");
        require(!original.contains("ip6-localhost"),"Real host file lacks Android alias; no globaledit");
        for(int i=0;i<32;i++)for(String name:new String[]{"ip6-localhost","IP6-LOCALHOST","ip6-localhost."}){
            InetAddress[] addresses=InetAddress.getAllByName(name);require(addresses.length>0,"Real hostname lookup");
            for(InetAddress address:addresses)require(address instanceof Inet6Address&&address.isLoopbackAddress(),"Real IPv6loopback address");
        }
        ExecutorService executor=Executors.newSingleThreadExecutor();
        try{
            for(String name:new String[]{"localhost","ip6-localhost"})for(int round=0;round<8;round++){
                InetAddress address=InetAddress.getByName(name);
                try(ServerSocket server=new ServerSocket(0,4,address)){
                    Future<Integer> accepted=executor.submit(new Callable<Integer>(){public Integer call()throws Exception{
                        try(Socket socket=server.accept()){socket.setSoTimeout(5000);int value=socket.getInputStream().read();socket.getOutputStream().write(value+1);return value;}
                    }});
                    try(Socket client=new Socket(name,server.getLocalPort())){
                        client.setSoTimeout(5000);client.getOutputStream().write(41);require(client.getInputStream().read()==42,"Actual static-host TCPbytes");
                        require(accepted.get(5,TimeUnit.SECONDS)==41,"Actual peer receivedpayload");
                        require(client.getInetAddress().isLoopbackAddress(),"Real peer loopbackidentity");
                    }
                }
            }
        }finally{executor.shutdownNow();require(executor.awaitTermination(5,TimeUnit.SECONDS),"All networkworkers terminal");}
        StructAddrinfo hints=new StructAddrinfo();hints.ai_family=OsConstants.AF_INET6;hints.ai_socktype=OsConstants.SOCK_STREAM;hints.ai_flags=OsConstants.AI_CANONNAME;
        InetAddress[] aliases=libcore.io.Libcore.os.android_getaddrinfo("ip6-localhost",hints,0);require(aliases.length==1&&aliases[0].isLoopbackAddress(),"Direct actual LinuxJNIhostname lookup");
        try{libcore.io.Libcore.os.android_getaddrinfo("ip6-localhost",hints,7);throw new AssertionError("Nondefault network unexpectedlyaccepted");}catch(GaiException expected){checks++;}
        require(new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get("/etc/hosts")),"UTF-8").equals(original),"Actual host resolverfile unchanged");
        System.out.println("COMPONENT_HOSTS_JAVA=PASS|checks="+checks+"|actual_alias=IPv6-loopback|tcp_rounds=16|direct_linux_jni=true|host_files=unchanged");
    }
}
