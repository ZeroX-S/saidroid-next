import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import libcore.io.*;

/** Actual private fdsan registry and kernel descriptor lifecycle, no cached-tag query. */
public final class OsFdOwnershipContract {
    private static int checks;
    private static void check(boolean value, String detail) {
        if (!value) throw new AssertionError(detail);
        checks++;
    }
    private static void owned(FileDescriptor fd, Object owner, String type) {
        long nativeTag=Libcore.os.android_fdsan_get_owner_tag(fd);
        check(nativeTag!=0,"real backend registered owner");
        check(fd.getOwnerId$()==nativeTag,"Java/native owner agrees");
        check(Libcore.os.android_fdsan_get_tag_type(nativeTag).equals(type),"actual backend owner type");
        check(Libcore.os.android_fdsan_get_tag_value(nativeTag)==System.identityHashCode(owner),"actual backend object identity");
    }
    private static FileDescriptor rawCopy(int raw) {
        FileDescriptor fd=new FileDescriptor();fd.setInt$(raw);return fd;
    }
    private static Object implementation(Object socket) throws Exception {
        java.lang.reflect.Field field=socket.getClass().getDeclaredField("impl");
        field.setAccessible(true);return field.get(socket);
    }
    private static void socketClosed(FileDescriptor descriptor,int raw) {
        check(!descriptor.valid()&&descriptor.getOwnerId$()==0,"socket releases Java owner");
        check(Libcore.os.android_fdsan_get_owner_tag(rawCopy(raw))==0,"socket actual registry retired");
    }
    private static void socketRoundtrips() throws Exception {
        InetAddress loopback=InetAddress.getLoopbackAddress();
        for(int round=0;round<16;round++) {
            FileDescriptor listening,clientFd,acceptedFd;int listeningRaw,clientRaw,acceptedRaw;
            try(ServerSocket listener=new ServerSocket(0,1,loopback)) {
                listener.setSoTimeout(2000);listening=listener.getFileDescriptor$();listeningRaw=listening.getInt$();
                owned(listening,implementation(listener),"SocketImpl");
                try(Socket client=new Socket(loopback,listener.getLocalPort());Socket accepted=listener.accept()) {
                    client.setSoTimeout(2000);accepted.setSoTimeout(2000);
                    clientFd=client.getFileDescriptor$();clientRaw=clientFd.getInt$();
                    acceptedFd=accepted.getFileDescriptor$();acceptedRaw=acceptedFd.getInt$();
                    owned(clientFd,implementation(client),"SocketImpl");
                    owned(acceptedFd,implementation(accepted),"SocketImpl");
                    client.getOutputStream().write(round+1);
                    check(accepted.getInputStream().read()==round+1,"real owned TCP client->accepted");
                    accepted.getOutputStream().write(42);
                    check(client.getInputStream().read()==42,"real owned TCP accepted->client");
                }
                socketClosed(clientFd,clientRaw);socketClosed(acceptedFd,acceptedRaw);
            }
            socketClosed(listening,listeningRaw);
            FileDescriptor senderFd,receiverFd;int senderRaw,receiverRaw;
            try(DatagramSocket receiver=new DatagramSocket(0,loopback);DatagramSocket sender=new DatagramSocket(0,loopback)) {
                receiver.setSoTimeout(2000);sender.setSoTimeout(2000);
                senderFd=sender.getFileDescriptor$();senderRaw=senderFd.getInt$();
                receiverFd=receiver.getFileDescriptor$();receiverRaw=receiverFd.getInt$();
                owned(senderFd,implementation(sender),"DatagramSocketImpl");
                owned(receiverFd,implementation(receiver),"DatagramSocketImpl");
                byte[] payload=new byte[]{(byte)round,42};
                sender.send(new DatagramPacket(payload,payload.length,loopback,receiver.getLocalPort()));
                DatagramPacket packet=new DatagramPacket(new byte[8],8);receiver.receive(packet);
                check(packet.getLength()==2&&packet.getData()[0]==(byte)round&&packet.getData()[1]==42,"real owned UDP payload");
            }
            socketClosed(senderFd,senderRaw);socketClosed(receiverFd,receiverRaw);
        }
    }
    public static void run() throws Exception {
        Path directory=Files.createTempDirectory("fdsan-contract-");
        Path path=directory.resolve("payload");byte[] data=new byte[]{1,2,3,4,5};
        Set<Integer> reused=new HashSet<>();
        try {
            for(int round=0;round<32;round++) {
                FileDescriptor saved;int raw;
                FileOutputStream output=new FileOutputStream(path.toFile());saved=output.getFD();raw=saved.getInt$();
                reused.add(raw);owned(saved,output,"FileOutputStream");output.write(data);output.close();output.close();
                check(!saved.valid()&&saved.getOwnerId$()==FileDescriptor.NO_OWNER,"output released Java owner");
                check(Libcore.os.android_fdsan_get_owner_tag(rawCopy(raw))==0,"closed output retired actual registry");
                FileInputStream input=new FileInputStream(path.toFile());saved=input.getFD();raw=saved.getInt$();
                reused.add(raw);owned(saved,input,"FileInputStream");byte[] read=new byte[5];
                check(input.read(read)==5&&Arrays.equals(data,read),"real stream content");input.close();input.close();
                check(!saved.valid()&&saved.getOwnerId$()==0,"input released Java owner");
                check(Libcore.os.android_fdsan_get_owner_tag(rawCopy(raw))==0,"closed input retired registry");
                RandomAccessFile random=new RandomAccessFile(path.toFile(),"rw");saved=random.getFD();raw=saved.getInt$();
                reused.add(raw);owned(saved,random,"RandomAccessFile");random.seek(2);random.write(42);random.seek(2);
                check(random.read()==42,"real random access write/read");random.close();random.close();
                check(!saved.valid()&&saved.getOwnerId$()==0,"random access released Java owner");
                check(Libcore.os.android_fdsan_get_owner_tag(rawCopy(raw))==0,"random close retired actual registry");
            }
            check(reused.size()<96,"kernel descriptor reuse exercised");
            FileDescriptor descriptor=Libcore.os.open(path.toString(),android.system.OsConstants.O_RDONLY,0);
            Object owner=new Object();IoUtils.setFdOwner(descriptor,owner);owned(descriptor,owner,"generic");
            int raw=descriptor.getInt$();
            FileDescriptor alias=rawCopy(raw);
            check(alias.getOwnerId$()==0,"raw alias has no cached Java owner");
            check(Libcore.os.android_fdsan_get_owner_tag(alias)==descriptor.getOwnerId$(),"query actual backend independent of Java alias owner");
            try { IoUtils.setFdOwner(descriptor,new Object());throw new AssertionError("second owner accepted"); }
            catch(IllegalStateException expected) {checks++;}
            int taken=IoUtils.acquireRawFd(descriptor);
            check(taken==raw&&!descriptor.valid()&&descriptor.getOwnerId$()==0,"raw ownership transfer invalidates wrapper");
            check(Libcore.os.android_fdsan_get_owner_tag(alias)==0,"raw transfer clears actual backend tag");
            Libcore.os.close(alias);
            FileDescriptor fd=Libcore.os.open(path.toString(),android.system.OsConstants.O_RDONLY,0);
            IoUtils.setFdOwner(fd,new Object());raw=fd.getInt$();
            IoUtils.close(fd);
            check(!fd.valid()&&fd.getOwnerId$()==0,"IoUtils close releases owner");
            check(Libcore.os.android_fdsan_get_owner_tag(rawCopy(raw))==0,"IoUtils close retires backend");
            try { Libcore.os.android_fdsan_get_owner_tag(null);throw new AssertionError("null query accepted"); }
            catch(NullPointerException expected) {checks++;}
            try { Libcore.os.android_fdsan_exchange_owner_tag(null,0,0);throw new AssertionError("null exchange accepted"); }
            catch(NullPointerException expected) {checks++;}
            check(Libcore.os.android_fdsan_get_owner_tag(new FileDescriptor())==0,"invalid descriptor unowned");
        } finally { Files.deleteIfExists(path);Files.delete(directory); }
        check(!Files.exists(directory),"all owned files removed");
        socketRoundtrips();
        System.out.println("FD_OWNERSHIP_CONTRACT=PASS|checks="+checks
                +"|real_io=true|native_registry=true|alias_query_independent=true|fd_reuse=true|ownership_transfer=true|tcp_udp_rounds=16|cleanup=true");
    }
}
