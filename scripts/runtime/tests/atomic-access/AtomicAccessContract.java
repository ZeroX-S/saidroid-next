import owner.Holder;
import owner.Peer;
import other.Child;
import other.Stranger;
import java.lang.reflect.InvocationTargetException;
import java.util.concurrent.atomic.*;

/** Real caller access checks, allowed atomic operations, and defining-loader identity. */
public final class AtomicAccessContract {
    private static int checks;
    private static void require(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static void denied(String name)throws Exception{
        int split=name.lastIndexOf('.');Class<?> type=Class.forName(name.substring(0,split));
        try{type.getMethod(name.substring(split+1)).invoke(null);throw new AssertionError("Private/package/protected access allowed: "+name);}
        catch(InvocationTargetException failure){
            Throwable cause=failure.getCause();
            require(cause instanceof RuntimeException && cause.getCause() instanceof IllegalAccessException,"Wrong access denial: "+cause);
        }
    }
    private static final class SeparateLoader extends dalvik.system.PathClassLoader {
        SeparateLoader(String jar){super(jar,Object.class.getClassLoader());}
        @Override protected Class<?> loadClass(String name,boolean resolve)throws ClassNotFoundException{
            if(!name.equals("owner.LoaderPeer"))return super.loadClass(name,resolve);
            Class<?> type=findLoadedClass(name);if(type==null)type=findClass(name);if(resolve)resolveClass(type);return type;
        }
    }
    public static void main(String[] args)throws Exception{
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(29);
        Holder value=new Holder();
        AtomicIntegerFieldUpdater<Holder> ints=Holder.privateInts();
        require(ints.compareAndSet(value,0,7)&&ints.get(value)==7,"Owner private integer access");
        AtomicLongFieldUpdater<Holder> longs=Holder.privateLongs();
        require(longs.compareAndSet(value,0,1L<<40)&&longs.get(value)==1L<<40,"Owner private long access");
        AtomicReferenceFieldUpdater<Holder,String> refs=Holder.privateReferences();
        require(refs.compareAndSet(value,null,"owned")&&refs.get(value).equals("owned"),"Owner private reference access");
        for(String name:new String[]{"owner.Peer.privateInt","owner.Peer.privateLong","owner.Peer.privateReference",
                "other.Child.privateInt","other.Child.privateLong","other.Child.privateReference",
                "other.Stranger.packageInt","other.Stranger.protectedInt"})denied(name);
        AtomicIntegerFieldUpdater<Holder> packageInts=Peer.packageInts();
        require(packageInts.compareAndSet(value,0,11)&&packageInts.get(value)==11,"Same runtime package access");
        AtomicIntegerFieldUpdater<Holder> publicInts=Stranger.publicInts();
        require(publicInts.compareAndSet(value,0,13)&&publicInts.get(value)==13,"Cross-package public access");
        AtomicIntegerFieldUpdater<Holder> protectedInts=Child.protectedInts();Child child=new Child();
        require(protectedInts.compareAndSet(child,0,17)&&protectedInts.get(child)==17,"Cross-package subclass protected access");
        try{protectedInts.get(value);throw new AssertionError("Protected updater accepted base receiver");}
        catch(RuntimeException failure){require(failure.getCause() instanceof IllegalAccessException,"Wrong protected receiver denial");}
        Class<?> separate=new SeparateLoader(args[0]).loadClass("owner.LoaderPeer");
        require(separate.getClassLoader()!=Holder.class.getClassLoader(),"Separate defining loader required");
        try{separate.getMethod("packageInt").invoke(null);throw new AssertionError("Matching package name bypassed defining-loader boundary");}
        catch(InvocationTargetException failure){require(failure.getCause().getCause() instanceof IllegalAccessException,"Wrong loader boundary denial");}
        System.out.println("ATOMIC_ACCESS_CONTRACT=PASS|checks="+checks+"|private_denials=true|owner_allowed=true|package_loader_boundary=true|protected_receiver_boundary=true|real_CAS=true");
    }
}
