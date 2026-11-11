package org.example.saildroid.documents;

import android.app.Activity;
import android.app.Application;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.system.Os;
import android.widget.Button;
import android.widget.ListView;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.UUID;

/** Normal APK entry points with automation restricted to this fixture's files. */
public final class DocumentPickerActivity extends Activity {
    private final Handler handler = new Handler();
    private File directory;
    private Uri persisted;
    private Activity currentPicker;
    private int phase;
    private boolean failed;
    private boolean repeated;
    private final byte[] payload = "SailDroid document selection regression\n".getBytes(StandardCharsets.UTF_8);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView status = new TextView(this);
        status.setText("Checking document selection");
        setContentView(status);
        getApplication().registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
            @Override public void onActivityCreated(Activity activity, Bundle state) {
                if ("SdDocumentPicker".equals(activity.getClass().getName())) currentPicker = activity;
            }
            @Override public void onActivityDestroyed(Activity activity) { if (currentPicker == activity) currentPicker = null; }
            @Override public void onActivityStarted(Activity activity) { }
            @Override public void onActivityResumed(Activity activity) { }
            @Override public void onActivityPaused(Activity activity) { }
            @Override public void onActivityStopped(Activity activity) { }
            @Override public void onActivitySaveInstanceState(Activity activity, Bundle state) { }
        });
        try {
            Intent get = intent(Intent.ACTION_GET_CONTENT, "text/plain");
            Intent open = intent(Intent.ACTION_OPEN_DOCUMENT, "*/*");
            if (get.resolveActivity(getPackageManager()) == null && open.resolveActivity(getPackageManager()) == null) {
                System.err.println("DOCUMENT_PICKER=baseline_missing|GET_CONTENT=true|OPEN_DOCUMENT=true");
                System.err.println("DOCUMENT_PICKER=passed");
                return;
            }
            require(get.resolveActivity(getPackageManager()) != null, "GET_CONTENT resolution");
            require(!getPackageManager().queryIntentActivities(open, android.content.pm.PackageManager.MATCH_DEFAULT_ONLY).isEmpty(), "OPEN_DOCUMENT resolution");
            require(new Intent("org.example.saildroid.UNKNOWN").resolveActivity(getPackageManager()) == null, "Unrelated intent resolution");
            directory = new File(System.getenv("EXTERNAL_STORAGE"), "Download/.saildroid-document-check-" + UUID.randomUUID());
            require(directory.mkdir(), "Fixture directory creation");
            write(new File(directory, "a.txt"));
            write(new File(directory, "b.txt"));
            write(new File(directory, "c.bin"));
            Os.symlink(new File(getFilesDir(), "private.txt").getPath(), new File(directory, "escape.txt").getPath());
            begin(1);
        } catch (Throwable failure) { fail(failure); }
    }

    private static Intent intent(String action, String mime) {
        return new Intent(action).addCategory(Intent.CATEGORY_OPENABLE).setType(mime);
    }

    private void begin(int next) {
        phase = next;
        Intent request = intent(next == 2 ? Intent.ACTION_OPEN_DOCUMENT : Intent.ACTION_GET_CONTENT,
                next == 2 ? "*/*" : "text/plain");
        request.putExtra(DocumentsContract.EXTRA_INITIAL_URI, DocumentsContract.buildDocumentUri(
                "com.android.externalstorage.documents", "primary:Download/" + directory.getName()));
        if (next == 2) request.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                .putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"text/plain"});
        if (next == 3) request = Intent.createChooser(request, "Fixture cancellation");
        startActivityForResult(request, next);
        automate(next, 0);
    }

    private static <T extends android.view.View> T view(android.view.View root, Class<T> type, String text) {
        if (type.isInstance(root) && (text == null || root instanceof TextView
                && ((TextView) root).getText().toString().startsWith(text))) return type.cast(root);
        if (root instanceof android.view.ViewGroup) {
            android.view.ViewGroup group = (android.view.ViewGroup) root;
            for (int index = 0; index < group.getChildCount(); index++) {
                T found = view(group.getChildAt(index), type, text);
                if (found != null) return found;
            }
        }
        return null;
    }

    private void automate(int expected, int attempt) {
        handler.postDelayed(() -> {
            if (failed || phase != expected) return;
            try {
                Activity picker = currentPicker;
                ListView list = picker == null ? null : view(picker.getWindow().getDecorView(), ListView.class, null);
                if (list == null || !list.isEnabled() || list.getAdapter() == null) {
                    require(attempt < 100, "Picker became ready");
                    automate(expected, attempt + 1);
                    return;
                }
                boolean hardware = (getApplicationInfo().flags
                        & android.content.pm.ApplicationInfo.FLAG_HARDWARE_ACCELERATED) != 0;
                require(picker.getWindow().getDecorView().isHardwareAccelerated() == hardware,
                        "Picker rendering matches the application backend");
                if (expected == 1) System.err.println("DOCUMENT_PICKER=rendering_passed|hardware=" + hardware);
                require(list.getAdapter().getCount() == 2, "MIME filter and linked-file exclusion");
                require("a.txt".equals(list.getAdapter().getItem(0)), "Fixture folder listing");
                if (expected == 3) { picker.finish(); return; }
                if (expected == 6 && !repeated) {
                    repeated = true;
                    Intent replacement = intent(Intent.ACTION_OPEN_DOCUMENT, "text/plain")
                            .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                            .putExtra(DocumentsContract.EXTRA_INITIAL_URI, DocumentsContract.buildDocumentUri(
                                "com.android.externalstorage.documents", "primary:Download/" + directory.getName()));
                    picker.startActivity(replacement);
                    automate(expected, attempt + 1);
                    return;
                }
                if (expected == 6 && list.getChoiceMode() != ListView.CHOICE_MODE_MULTIPLE) {
                    require(attempt < 100, "Repeated request updated picker");
                    automate(expected, attempt + 1);
                    return;
                }
                if (expected == 4) require(new File(directory, "a.txt").delete(), "Remove selected file");
                list.performItemClick(list.getChildAt(0), 0, list.getAdapter().getItemId(0));
                if (expected == 2) {
                    list.performItemClick(list.getChildAt(1), 1, list.getAdapter().getItemId(1));
                    view(picker.getWindow().getDecorView(), Button.class, "选择 (").performClick();
                }
                if (expected == 6) view(picker.getWindow().getDecorView(), Button.class, "选择 (").performClick();
                if (expected == 4) {
                    require(!picker.isFinishing(), "Removed document keeps picker open");
                    picker.finish();
                }
            } catch (Throwable failure) { fail(failure); }
        }, 100);
    }

    private void read(Uri uri) throws Exception {
        require("content".equals(uri.getScheme()), "Content URI result");
        require("text/plain".equals(getContentResolver().getType(uri)), "MIME result");
        try (Cursor row = getContentResolver().query(uri,
                new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE, "_data"}, null, null, null)) {
            require(row != null && row.moveToFirst(), "Openable metadata");
            require(row.getLong(1) == payload.length, "Actual file size");
            require(new File(row.getString(2)).getParentFile().equals(directory), "Actual selected path");
        }
        try (InputStream input = getContentResolver().openInputStream(uri)) {
            byte[] bytes = new byte[payload.length + 1];
            int size = 0;
            int count;
            while ((count = input.read(bytes, size, bytes.length - size)) > 0) size += count;
            require(size == payload.length && java.util.Arrays.equals(payload, java.util.Arrays.copyOf(bytes, size)), "Actual document bytes");
        }
        boolean denied = false;
        try (android.os.ParcelFileDescriptor ignored = getContentResolver().openFileDescriptor(uri, "rw")) { }
        catch (java.io.FileNotFoundException expected) { denied = true; }
        require(denied, "Write handle denied");
    }

    @Override protected void onActivityResult(int request, int code, Intent result) {
        super.onActivityResult(request, code, result);
        try {
            require(request == phase, "Result request owner");
            if (request == 1) {
                require(code == RESULT_OK && result != null, "Single selection callback");
                read(result.getData());
                File selected = new File(directory, "a.txt");
                require(selected.delete(), "Replace selected file");
                Os.symlink(new File(getFilesDir(), "private.txt").getPath(), selected.getPath());
                boolean denied = false;
                try (InputStream ignored = getContentResolver().openInputStream(result.getData())) { }
                catch (java.io.FileNotFoundException expected) { denied = true; }
                require(denied, "Linked replacement denied");
                require(selected.delete(), "Remove replacement link");
                write(selected);
                System.err.println("DOCUMENT_PICKER=single_passed|metadata=true|bytes=true|write_denied=true|link_denied=true");
                begin(2);
            } else if (request == 2) {
                require(code == RESULT_OK && result.getClipData().getItemCount() == 2, "Multiple selection callback");
                read(result.getData());
                read(result.getClipData().getItemAt(1).getUri());
                persisted = result.getData();
                getContentResolver().takePersistableUriPermission(persisted, Intent.FLAG_GRANT_READ_URI_PERMISSION);
                require(getContentResolver().getPersistedUriPermissions().size() == 1, "Persisted read grant");
                phase = 5;
                startActivityForResult(new Intent(this, ReaderActivity.class).putExtra("uri", persisted), 5);
            } else if (request == 5) {
                require(code == RESULT_OK, "Independent process document read");
                getContentResolver().releasePersistableUriPermission(persisted, Intent.FLAG_GRANT_READ_URI_PERMISSION);
                require(getContentResolver().getPersistedUriPermissions().isEmpty(), "Read grant release");
                System.err.println("DOCUMENT_PICKER=multiple_passed|count=2|persisted=true|cross_process=true");
                begin(3);
            } else if (request == 3) {
                require(code == RESULT_CANCELED, "Chooser cancellation result");
                System.err.println("DOCUMENT_PICKER=cancel_passed|chooser=true");
                begin(4);
            } else if (request == 4) {
                require(code == RESULT_CANCELED, "Removed file cancellation");
                System.err.println("DOCUMENT_PICKER=removed_file_passed");
                write(new File(directory, "a.txt"));
                begin(6);
            } else if (request == 6) {
                require(code == RESULT_OK && (result.getFlags() & Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION) != 0,
                        "Repeated request retained result owner and new action");
                read(result.getData());
                cleanup();
                System.err.println("DOCUMENT_PICKER=repeated_request_passed");
                System.err.println("DOCUMENT_PICKER=passed");
            }
        } catch (Throwable failure) { fail(failure); }
    }

    private void write(File file) throws Exception {
        try (FileOutputStream output = new FileOutputStream(file)) { output.write(payload); }
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private void cleanup() {
        if (directory == null || !directory.isDirectory()) return;
        for (String name : new String[]{"a.txt", "b.txt", "c.bin", "escape.txt"}) {
            File file = new File(directory, name);
            if (file.exists() || java.nio.file.Files.isSymbolicLink(file.toPath())) require(file.delete(), "Fixture file cleanup");
        }
        require(directory.delete(), "Fixture directory cleanup");
    }

    private void fail(Throwable failure) {
        failed = true;
        failure.printStackTrace();
        try { cleanup(); } catch (Throwable cleanup) { cleanup.printStackTrace(); }
        System.err.println("DOCUMENT_PICKER=failed|type=" + failure.getClass().getName());
    }

    public static final class ReaderActivity extends Activity {
        @Override public void onCreate(Bundle state) {
            super.onCreate(state);
            try {
                Uri uri = getIntent().getParcelableExtra("uri");
                try (InputStream input = getContentResolver().openInputStream(uri)) {
                    require(input.read() == 'S', "Independent process bytes");
                }
                require(getContentResolver().getPersistedUriPermissions().size() == 1, "Independent process persisted grant");
                setResult(RESULT_OK);
            } catch (Throwable failure) {
                failure.printStackTrace();
                System.err.println("DOCUMENT_PICKER=failed|reader=true");
            }
            finish();
        }
    }
}
