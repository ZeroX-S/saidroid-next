package owner;
import java.util.concurrent.atomic.*;
public final class Peer {
    public static void privateInt(){AtomicIntegerFieldUpdater.newUpdater(Holder.class,"privateInt");}
    public static void privateLong(){AtomicLongFieldUpdater.newUpdater(Holder.class,"privateLong");}
    public static void privateReference(){AtomicReferenceFieldUpdater.newUpdater(Holder.class,String.class,"privateReference");}
    public static AtomicIntegerFieldUpdater<Holder> packageInts(){return AtomicIntegerFieldUpdater.newUpdater(Holder.class,"packageInt");}
}
