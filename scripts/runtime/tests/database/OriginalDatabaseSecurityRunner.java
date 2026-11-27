import android.content.Context;
import android.content.ContextWrapper;
import android.database.DatabaseErrorHandler;
import android.database.sqlite.SQLiteDatabase;
import java.io.File;
import java.lang.reflect.InvocationTargetException;

/** Explicit original-APK diagnostic with a private real SQLite context. */
public final class OriginalDatabaseSecurityRunner {
    private static final class FixtureContext extends ContextWrapper {
        private final File root;
        FixtureContext(File directory){super(null);root=directory;}
        @Override public File getDatabasePath(String name){
            if(!"database_test.db".equals(name))throw new SecurityException("Unexpected fixture database");
            return new File(root,name);
        }
        @Override public boolean deleteDatabase(String name){return SQLiteDatabase.deleteDatabase(getDatabasePath(name));}
        @Override public SQLiteDatabase openOrCreateDatabase(String name,int mode,SQLiteDatabase.CursorFactory factory){
            if(mode!=Context.MODE_PRIVATE)throw new SecurityException("Unexpected fixture database mode");
            return SQLiteDatabase.openOrCreateDatabase(getDatabasePath(name),factory);
        }
        @Override public SQLiteDatabase openOrCreateDatabase(String name,int mode,SQLiteDatabase.CursorFactory factory,DatabaseErrorHandler handler){
            if(mode!=Context.MODE_PRIVATE)throw new SecurityException("Unexpected fixture database mode");
            return SQLiteDatabase.openOrCreateDatabase(getDatabasePath(name).getAbsolutePath(),factory,handler);
        }
        @Override public Context getApplicationContext(){return this;}
    }
    public static void main(String[] args) throws Exception {
        DatabaseCorruptionContract.initialize();
        File fixture=new File(args[1]);
        if(!fixture.isDirectory()||fixture.list().length!=0)throw new AssertionError("Empty private fixture required");
        DatabaseCorruptionContract.fixturePageSize(fixture);
        int sdk=Integer.parseInt(args[2]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion()!=sdk)throw new AssertionError("SDK binding failed");
        ClassLoader loader=new dalvik.system.PathClassLoader(args[0],Object.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?> type=Class.forName("android.database.sqlite.cts.SQLiteSecurityTest",true,loader);
        int failures=0;
        for(String name:new String[]{"testScript1","testScript2","testScript3"}){
            Object test=type.newInstance();
            type.getMethod("setName",String.class).invoke(test,name);
            type.getMethod("setContext",Context.class).invoke(test,new FixtureContext(fixture));
            try{type.getMethod("runBare").invoke(test);System.out.println("ORIGINAL_SQLITE_SECURITY|test="+name+"|result=PASS");}
            catch(InvocationTargetException failure){failures++;System.out.println("ORIGINAL_SQLITE_SECURITY|test="+name+"|result=FAIL");failure.getCause().printStackTrace();}
        }
        System.out.println("ORIGINAL_SQLITE_SECURITY_VM|tests=3|failures="+failures+"|targetSdk="+sdk);
        if(failures!=0)throw new AssertionError("Original SQLite security cases failed");
    }
}
