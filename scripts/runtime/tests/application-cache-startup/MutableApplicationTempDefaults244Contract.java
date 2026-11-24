import android.system.Os;
import android.system.StructStat;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Properties;

/** General private app defaults with normal mutable Java property semantics. */
public final class MutableApplicationTempDefaults244Contract {
    private static int checks;
    private static void check(boolean yes,String why){checks++;if(!yes)throw new AssertionError(why);}
    public static void run(String label) throws Exception {
        check(Os.getuid()==65534,"ordinary UID");
        String actualData=System.getenv("SAILDROID_DATA_DIR");
        check(actualData.equals(System.getProperty("saidroid.data")),"actual immutable host app data");
        Path cache=Paths.get(actualData,"cache");
        String expected=cache.toString();
        check(Files.isDirectory(cache),"actual private cache exists");
        check(expected.equals(System.getProperty("java.io.tmpdir")),"actual startup default before any explicit mutable override");
        Properties saved=System.getProperties();Path file=null;
        try {
            System.setProperties(null);
            check(expected.equals(System.getProperty("java.io.tmpdir")),"normal default initialized from actual app data");
            check("".equals(System.getProperty("user.home")),"canonical empty changeable user.home default");
            Path custom=cache.resolve("mutable-choice");Files.createDirectory(custom);
            System.setProperty("java.io.tmpdir",custom.toString());
            check(custom.toString().equals(System.getProperty("java.io.tmpdir")),"java.io.tmpdir is mutable");
            Path chosen=java.io.File.createTempFile("mutable-", ".tmp").toPath();
            check(chosen.getParent().equals(custom),"actual File.createTempFile honors changed directory");Files.delete(chosen);
            check(custom.toString().equals(System.clearProperty("java.io.tmpdir")),"clear returns previous mutable value");
            check(System.getProperty("java.io.tmpdir")==null,"clear has canonical null result");
            System.setProperties(null);
            check(expected.equals(System.getProperty("java.io.tmpdir")),"reset restores private changeable default");
            Properties replacement=new Properties();replacement.setProperty("java.io.tmpdir",custom.toString());replacement.setProperty("unrelated","kept");System.setProperties(replacement);
            check(custom.toString().equals(System.getProperty("java.io.tmpdir")),"replacement preserves explicit mutable choice");
            check("kept".equals(System.getProperty("unrelated")),"unrelated properties unchanged");
            System.setProperties(new Properties());
            check(System.getProperty("java.io.tmpdir")==null,"non-null empty replacement does not invent missing mutable property");
            check(actualData.equals(System.getProperty("saidroid.data")),"canonical immutable defaults survive replacement");
            System.setProperties(null);
            System.getProperties().clear();
            check(System.getProperty("java.io.tmpdir")==null,"clear removes mutable default");
            System.setProperties(null);
            check(expected.equals(System.getProperty("java.io.tmpdir")),"reset after clear restores private cache");
            System.setProperty("user.home","/still-mutable");
            check("/still-mutable".equals(System.getProperty("user.home")),"user.home remains mutable");
            file=java.io.File.createTempFile("default-", ".bin").toPath();
            check(file.getParent().equals(cache),"default temporary file belongs to private cache");
            byte[] bytes={23,44,7,29};Files.write(file,bytes);
            check(java.util.Arrays.equals(bytes,Files.readAllBytes(file)),"real temporary file IO");
            StructStat cs=Os.lstat(cache.toString()),fs=Os.lstat(file.toString());
            check(cs.st_uid==Os.getuid()&&(cs.st_mode&0777)==0700,"cache owner/mode private");
            check(fs.st_uid==Os.getuid()&&(fs.st_mode&0077)==0,"file inaccessible to other UIDs");
            check(file.toFile().getCanonicalPath().equals(file.toString()),"canonical private path");
        } finally {System.setProperties(saved);}
        System.out.println("MUTABLE_APP_TEMP_DEFAULTS244_CONTRACT=PASS|application="+label+"|checks="+checks+"|uid="+Os.getuid()+"|file="+file);
    }
}
