import android.app.ActivityThread;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.content.pm.ProviderInfo;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.webkit.MimeTypeMap;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

/** Read-only handles for files explicitly selected in the requesting app's task. */
public final class SdDocumentsProvider extends ContentProvider {
    public static final String AUTHORITY = "org.saildroid.documents";
    private static SQLiteDatabase database;
    private static final String[] COLUMNS = {
        OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE, "mime_type", "_data"
    };

    public static ArrayList<File> roots() throws IOException {
        String home = System.getenv("HOME");
        String shared = System.getenv("EXTERNAL_STORAGE");
        if (home == null || shared == null) throw new IOException("Document roots are not configured");
        ArrayList<File> result = new ArrayList<File>();
        for (File root : new File[]{new File(shared), new File(home, "Downloads"),
                new File(home, "Documents"), new File(home, "Pictures"),
                new File(home, "Videos"), new File(home, "Music")}) {
            if (root.isDirectory() && root.canRead() && root.getAbsoluteFile().equals(root.getCanonicalFile())
                    && !result.contains(root)) result.add(root);
        }
        return result;
    }

    static File checked(File file) throws IOException {
        File absolute = file.getAbsoluteFile();
        File canonical = file.getCanonicalFile();
        if (!absolute.equals(canonical)) throw new FileNotFoundException("Document path contains a link");
        for (File root : roots()) {
            if (canonical.equals(root) || canonical.getPath().startsWith(root.getPath() + File.separator)) {
                if (!canonical.canRead()) throw new FileNotFoundException("Document is unreadable");
                return canonical;
            }
        }
        throw new FileNotFoundException("Document is outside shared folders");
    }

    static String mime(File file) {
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        String type = dot < 0 ? null : MimeTypeMap.getSingleton().getMimeTypeFromExtension(
                name.substring(dot + 1).toLowerCase(Locale.ROOT));
        return type == null ? "application/octet-stream" : type;
    }

    private static synchronized SQLiteDatabase database() {
        if (database == null) {
            Context context = ActivityThread.currentApplication();
            if (context == null) throw new IllegalStateException("Documents require a bound application");
            File path = context.getDatabasePath("saildroid-documents.db");
            try {
                if (!path.getAbsoluteFile().equals(path.getCanonicalFile())
                        || !path.getCanonicalPath().startsWith(new File(SdApkPackage.DATA).getCanonicalPath() + File.separator)) {
                    throw new SecurityException("Document grants escaped application data");
                }
            } catch (IOException failure) {
                throw new IllegalStateException("Cannot locate document grants", failure);
            }
            database = new SQLiteOpenHelper(context, path.getName(), null, 1) {
                @Override public void onCreate(SQLiteDatabase db) {
                    db.execSQL("CREATE TABLE grants (token TEXT PRIMARY KEY,path TEXT NOT NULL,persistable INTEGER NOT NULL,persisted INTEGER NOT NULL DEFAULT 0)");
                }
                @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
                    throw new IllegalStateException("Unknown document grants schema");
                }
            }.getWritableDatabase();
        }
        return database;
    }

    static ArrayList<Uri> grant(Set<File> files, boolean persistable) throws IOException {
        ArrayList<Uri> result = new ArrayList<Uri>();
        SQLiteDatabase db = database();
        db.beginTransaction();
        try {
            for (File file : files) {
                File selected = checked(file);
                if (!selected.isFile()) throw new FileNotFoundException("Selected document is not a regular file");
                String token = UUID.randomUUID().toString();
                ContentValues row = new ContentValues();
                row.put("token", token);
                row.put("path", selected.getPath());
                row.put("persistable", persistable ? 1 : 0);
                db.insertOrThrow("grants", null, row);
                result.add(new Uri.Builder().scheme("content").authority(AUTHORITY).appendPath("file").appendPath(token).build());
            }
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
        return result;
    }

    private static String token(Uri uri) {
        if (uri == null || !"content".equals(uri.getScheme()) || !AUTHORITY.equals(uri.getAuthority())
                || uri.getPathSegments().size() != 2 || !"file".equals(uri.getPathSegments().get(0))) {
            throw new SecurityException("Invalid document handle");
        }
        return uri.getLastPathSegment();
    }

    private static File selected(Uri uri) throws FileNotFoundException {
        try (Cursor row = database().query("grants", new String[]{"path"}, "token=?",
                new String[]{token(uri)}, null, null, null)) {
            if (!row.moveToFirst()) throw new FileNotFoundException("Document was not selected by this application");
            File file = checked(new File(row.getString(0)));
            if (!file.isFile()) throw new FileNotFoundException("Selected document is unavailable");
            return file;
        } catch (IOException failure) {
            throw new FileNotFoundException(failure.getMessage());
        }
    }

    static void persist(Uri uri, int mode, boolean release) {
        if (mode != android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION) {
            throw new SecurityException("Documents support read grants only");
        }
        ContentValues row = new ContentValues();
        row.put("persisted", release ? 0 : System.currentTimeMillis());
        if (database().update("grants", row, "token=? AND persistable=1", new String[]{token(uri)}) != 1) {
            throw new SecurityException("Document has no persistable grant");
        }
    }

    static ArrayList<android.content.UriPermission> persisted() {
        ArrayList<android.content.UriPermission> result = new ArrayList<android.content.UriPermission>();
        try (Cursor rows = database().query("grants", new String[]{"token", "persisted"},
                "persisted>0", null, null, null, null)) {
            while (rows.moveToNext()) {
                Uri uri = new Uri.Builder().scheme("content").authority(AUTHORITY).appendPath("file").appendPath(rows.getString(0)).build();
                result.add(new android.content.UriPermission(uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION, rows.getLong(1)));
            }
        }
        return result;
    }

    public static ProviderInfo info() {
        ProviderInfo info = new ProviderInfo();
        info.authority = AUTHORITY;
        info.name = SdDocumentsProvider.class.getName();
        info.packageName = SdApkPackage.NAME;
        info.applicationInfo = SdApkPackage.applicationInfo();
        info.exported = false;
        info.grantUriPermissions = true;
        return info;
    }

    @Override public boolean onCreate() { database(); return true; }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        try {
            File file = selected(uri);
            String[] columns = projection == null ? COLUMNS : projection;
            MatrixCursor result = new MatrixCursor(columns, 1);
            Object[] row = new Object[columns.length];
            for (int index = 0; index < columns.length; index++) {
                String column = columns[index];
                if (OpenableColumns.DISPLAY_NAME.equals(column)) row[index] = file.getName();
                else if (OpenableColumns.SIZE.equals(column)) row[index] = file.length();
                else if ("mime_type".equals(column)) row[index] = mime(file);
                else if ("_data".equals(column)) row[index] = file.getPath();
            }
            result.addRow(row);
            return result;
        } catch (FileNotFoundException failure) {
            throw new IllegalArgumentException("Selected document is unavailable", failure);
        }
    }

    @Override public String getType(Uri uri) {
        try { return mime(selected(uri)); }
        catch (FileNotFoundException failure) { return null; }
    }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Selected documents are read-only");
        File file = selected(uri);
        FileDescriptor descriptor = null;
        try {
            descriptor = Os.open(file.getPath(), OsConstants.O_RDONLY | OsConstants.O_CLOEXEC | OsConstants.O_NOFOLLOW, 0);
            if (!OsConstants.S_ISREG(Os.fstat(descriptor).st_mode)) throw new FileNotFoundException("Document is not a regular file");
            return ParcelFileDescriptor.dup(descriptor);
        } catch (ErrnoException | IOException failure) {
            throw new FileNotFoundException(failure.getMessage());
        } finally {
            if (descriptor != null) try { Os.close(descriptor); }
            catch (ErrnoException failure) { System.err.println("SDDOCUMENT=descriptor_close_failed|errno=" + failure.errno); }
        }
    }

    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException("Document insertion is unavailable"); }
    @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException("Document updates are unavailable"); }
    @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException("Document deletion is unavailable"); }
}
