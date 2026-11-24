package other;
import owner.Holder;
import java.util.concurrent.atomic.*;
public final class Stranger {
    public static void packageInt(){AtomicIntegerFieldUpdater.newUpdater(Holder.class,"packageInt");}
    public static void protectedInt(){AtomicIntegerFieldUpdater.newUpdater(Holder.class,"protectedInt");}
    public static AtomicIntegerFieldUpdater<Holder> publicInts(){return AtomicIntegerFieldUpdater.newUpdater(Holder.class,"publicInt");}
}
