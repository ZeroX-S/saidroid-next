package other;
import owner.Holder;
import java.util.concurrent.atomic.*;
public final class Child extends Holder {
    public static void privateInt(){AtomicIntegerFieldUpdater.newUpdater(Holder.class,"privateInt");}
    public static void privateLong(){AtomicLongFieldUpdater.newUpdater(Holder.class,"privateLong");}
    public static void privateReference(){AtomicReferenceFieldUpdater.newUpdater(Holder.class,String.class,"privateReference");}
    public static AtomicIntegerFieldUpdater<Holder> protectedInts(){return AtomicIntegerFieldUpdater.newUpdater(Holder.class,"protectedInt");}
}
