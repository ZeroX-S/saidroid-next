package owner;
import java.util.concurrent.atomic.*;
public class Holder {
    private volatile int privateInt;
    private volatile long privateLong;
    private volatile String privateReference;
    volatile int packageInt;
    public volatile int publicInt;
    protected volatile int protectedInt;
    public static AtomicIntegerFieldUpdater<Holder> privateInts(){return AtomicIntegerFieldUpdater.newUpdater(Holder.class,"privateInt");}
    public static AtomicLongFieldUpdater<Holder> privateLongs(){return AtomicLongFieldUpdater.newUpdater(Holder.class,"privateLong");}
    public static AtomicReferenceFieldUpdater<Holder,String> privateReferences(){return AtomicReferenceFieldUpdater.newUpdater(Holder.class,String.class,"privateReference");}
}
