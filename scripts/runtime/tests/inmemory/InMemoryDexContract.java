import dalvik.system.InMemoryDexClassLoader;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Real ART DEX loading: no native registration or result substitution. */
public final class InMemoryDexContract {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("check " + checks); }
    private static void load(ByteBuffer buffer) throws Exception {
        int position=buffer.position(),limit=buffer.limit();
        ClassLoader loader=new InMemoryDexClassLoader(buffer,Object.class.getClassLoader());
        Class<?> target=loader.loadClass("inmemory.fixture.MemoryTarget");
        check(target.getClassLoader()==loader);
        check(((Integer)target.getMethod("value").invoke(null))==314159);
        check(buffer.position()==position && buffer.limit()==limit);
    }
    public static void main(String[] args) throws Exception {
        byte[] dex=Files.readAllBytes(Paths.get(System.getProperty("saidroid.test.memory-dex")));
        check(dex[0]=='d'&&dex[1]=='e'&&dex[2]=='x');
        for(boolean direct:new boolean[]{false,true}) {
            for(int padding:new int[]{0,1,37,4096}) {
                ByteBuffer base=direct?ByteBuffer.allocateDirect(padding+dex.length+13):ByteBuffer.allocate(padding+dex.length+13);
                base.position(padding);base.put(dex);base.limit(padding+dex.length);base.position(padding);
                load(base);
                load(base.slice());
                if(direct)load(base.asReadOnlyBuffer());
                ByteBuffer slice=base.slice();slice.position(3);slice= slice.slice();
                // A truncated header must never resolve a class from the parent.
                ClassLoader bad=new InMemoryDexClassLoader(slice,Object.class.getClassLoader());
                try{bad.loadClass("inmemory.fixture.MemoryTarget");throw new AssertionError("corrupt dex accepted");}
                catch(ClassNotFoundException expected){check(expected.getSuppressed().length>0);}
            }
        }
        try{new InMemoryDexClassLoader((ByteBuffer)null,Object.class.getClassLoader());throw new AssertionError("null accepted");}
        catch(NullPointerException expected){check(true);}
        try{new InMemoryDexClassLoader(new ByteBuffer[]{null},Object.class.getClassLoader());throw new AssertionError("null element accepted");}
        catch(NullPointerException expected){check(true);}
        System.out.println("INMEMORY_DEX_CONTRACT=PASS|checks="+checks+"|backend=actual-ART|buffer-position=preserved|heap-slice-offset=verified");
    }
}
