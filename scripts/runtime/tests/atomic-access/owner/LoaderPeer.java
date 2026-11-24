package owner;
import java.util.concurrent.atomic.AtomicIntegerFieldUpdater;
/** Same package spelling, but loaded by a distinct defining loader. */
public final class LoaderPeer {
    public static void packageInt(){AtomicIntegerFieldUpdater.newUpdater(Holder.class,"packageInt");}
}
