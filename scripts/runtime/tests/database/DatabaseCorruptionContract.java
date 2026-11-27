import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteStatement;
import java.io.File;
import java.io.RandomAccessFile;
import java.lang.reflect.Field;

/** Real SQLite corruption/recovery on a private VM fixture, never phone data. */
public final class DatabaseCorruptionContract {
    public static void initialize() throws Exception {
        System.load(System.getProperty("saidroid.bridge.library"));
        Class<?> bridge=Class.forName("SdBridge");
        String nativeRoot=System.getProperty("saidroid.native.root");
        String dirs=nativeRoot+"/lib64:"+nativeRoot+"/apex/com.android.runtime.debug/lib64:"
                +nativeRoot+"/apex/com.android.conscrypt/lib64:"+nativeRoot+"/apex/com.android.resolv/lib64";
        if(!(Boolean)bridge.getMethod("loadBionicLibrary",String.class,String.class).invoke(null,
                nativeRoot+"/lib64/libandroid_runtime.so",dirs))throw new AssertionError("Native bootstrap failed");
        if((Integer)bridge.getMethod("registerFrameworkNatives").invoke(null)<1)
            throw new AssertionError("Framework JNI registration failed");
        Field service=android.content.ContentResolver.class.getDeclaredField("sContentService");
        service.setAccessible(true);service.set(null,SdContentService.service());
    }
    public static void fixturePageSize(File root) throws Exception {
        // The Linux VM has no Android /data mount. Cache the actual fixture
        // filesystem block size, as SQLiteGlobal normally obtains from /data.
        Field pageSize=Class.forName("android.database.sqlite.SQLiteGlobal").getDeclaredField("sDefaultPageSize");
        pageSize.setAccessible(true);
        pageSize.setInt(null,new android.os.StatFs(root.getAbsolutePath()).getBlockSize());
    }
    public static void main(String[] args) throws Exception {
        initialize();
        File root=new File(args[0]);
        if(!root.isDirectory()||root.list().length!=0)throw new AssertionError("Empty fixture required");
        fixturePageSize(root);
        File sentinel=new File(root,"outside-sentinel");
        RandomAccessFile check=new RandomAccessFile(sentinel,"rw");check.writeUTF("must remain");check.close();
        File database=new File(root,"corrupt.db");
        SQLiteDatabase db=SQLiteDatabase.openOrCreateDatabase(database,null);
        db.execSQL("CREATE TABLE original_payload(value TEXT)");
        db.execSQL("INSERT INTO original_payload VALUES ('before corruption')");
        db.close();
        RandomAccessFile corrupt=new RandomAccessFile(database,"rw");
        corrupt.seek(0);corrupt.write(new byte[100]);corrupt.close();
        System.out.println("SQLITE_CORRUPTION=created|bytes=100");
        db=SQLiteDatabase.openOrCreateDatabase(database,null);
        SQLiteStatement statement=db.compileStatement("SELECT count(*) FROM sqlite_master WHERE name='original_payload'");
        if(statement.simpleQueryForLong()!=0)throw new AssertionError("Corrupt database not recreated");
        statement.close();
        db.execSQL("CREATE TABLE recovered(value INTEGER)");
        db.execSQL("INSERT INTO recovered VALUES (42)");
        statement=db.compileStatement("SELECT value FROM recovered");
        if(statement.simpleQueryForLong()!=42)throw new AssertionError("Recovered SQLite not writable");
        statement.close();db.close();
        check=new RandomAccessFile(sentinel,"r");
        if(!"must remain".equals(check.readUTF()))throw new AssertionError("Unrelated fixture changed");
        check.close();
        System.out.println("DATABASE_CORRUPTION_CONTRACT=PASS|native_sqlite=true|recreated=true|sentinel_intact=true");
    }
}
