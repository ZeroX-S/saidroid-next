import android.app.Activity;
import android.content.ClipData;
import android.content.ComponentName;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ActivityInfo;
import android.content.pm.ResolveInfo;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Local document selection using the host's real shared folders. */
public final class SdDocumentPicker extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final LinkedHashSet<File> selected = new LinkedHashSet<File>();
    private ArrayList<File> roots = new ArrayList<File>();
    private ArrayList<File> entries = new ArrayList<File>();
    private File folder;
    private Intent request;
    private ListView list;
    private TextView title;
    private Button choose;
    private boolean multiple;
    private boolean closed;
    private int generation;

    private static Intent request(Intent intent) {
        ComponentName component = intent.getComponent();
        if (Intent.ACTION_CHOOSER.equals(intent.getAction())
                && (component == null || new ComponentName(SdApkPackage.NAME, SdDocumentPicker.class.getName()).equals(component))
                && (intent.getPackage() == null || SdApkPackage.NAME.equals(intent.getPackage()))) {
            return intent.getParcelableExtra(Intent.EXTRA_INTENT);
        }
        return intent;
    }

    public static ResolveInfo resolve(Intent intent, String type) {
        Intent selected = request(intent);
        if (selected == null || !(Intent.ACTION_GET_CONTENT.equals(selected.getAction())
                || Intent.ACTION_OPEN_DOCUMENT.equals(selected.getAction()))) return null;
        ComponentName component = selected.getComponent();
        if (component != null && !new ComponentName(SdApkPackage.NAME, SdDocumentPicker.class.getName()).equals(component)) return null;
        if (selected.getPackage() != null && !SdApkPackage.NAME.equals(selected.getPackage())) return null;
        Set<String> categories = selected.getCategories();
        if (categories != null) for (String category : categories) {
            if (!Intent.CATEGORY_DEFAULT.equals(category) && !Intent.CATEGORY_OPENABLE.equals(category)) return null;
        }
        String mime = selected.getType() == null ? type : selected.getType();
        if (mime == null || mime.indexOf('/') <= 0) return null;
        ResolveInfo result = new ResolveInfo();
        result.activityInfo = activityInfo();
        result.isDefault = true;
        result.match = IntentFilter.MATCH_CATEGORY_TYPE;
        return result;
    }

    public static ActivityInfo activityInfo() {
        ActivityInfo info = new ActivityInfo();
        info.packageName = SdApkPackage.NAME;
        info.name = SdDocumentPicker.class.getName();
        info.processName = SdApkPackage.processName();
        info.applicationInfo = SdApkPackage.applicationInfo();
        info.theme = android.R.style.Theme_Material_Light_NoActionBar;
        if (SdWindowHost.hardware()) info.flags |= ActivityInfo.FLAG_HARDWARE_ACCELERATED;
        info.enabled = true;
        info.exported = true;
        info.nonLocalizedLabel = "选择文件";
        return info;
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (resolve(getIntent(), getIntent().getType()) == null) { finish(); return; }
        request = request(getIntent());
        multiple = request.getBooleanExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(16 * getResources().getDisplayMetrics().density);
        content.setPadding(padding, padding, padding, padding);
        Button back = new Button(this);
        back.setText("返回上级 / 共享位置");
        back.setOnClickListener(view -> up());
        content.addView(back);
        title = new TextView(this);
        content.addView(title);
        list = new ListView(this);
        list.setChoiceMode(multiple ? ListView.CHOICE_MODE_MULTIPLE : ListView.CHOICE_MODE_NONE);
        list.setOnItemClickListener((parent, view, position, id) -> select(position));
        content.addView(list, new LinearLayout.LayoutParams(-1, 0, 1));
        choose = new Button(this);
        choose.setText("选择文件");
        choose.setEnabled(false);
        choose.setVisibility(multiple ? android.view.View.VISIBLE : android.view.View.GONE);
        choose.setOnClickListener(view -> complete());
        content.addView(choose);
        Button cancel = new Button(this);
        cancel.setText("取消");
        cancel.setOnClickListener(view -> finish());
        content.addView(cancel);
        setContentView(content);
        try {
            roots = SdDocumentsProvider.roots();
            show(initialFolder());
            System.err.println("SDDOCUMENT=picker_opened|action=" + request.getAction() + "|multiple=" + multiple);
        } catch (IOException failure) {
            title.setText("无法读取共享位置");
            System.err.println("SDDOCUMENT=roots_failed|type=" + failure.getClass().getName());
        }
    }

    private File initialFolder() {
        Uri uri = request.getParcelableExtra(DocumentsContract.EXTRA_INITIAL_URI);
        if (uri == null || !"com.android.externalstorage.documents".equals(uri.getAuthority())) return null;
        try {
            String id = DocumentsContract.getDocumentId(uri);
            if (!id.startsWith("primary:")) return null;
            File directory = SdDocumentsProvider.checked(new File(System.getenv("EXTERNAL_STORAGE"), id.substring(8)));
            return directory.isDirectory() ? directory : null;
        } catch (IOException | IllegalArgumentException failure) { return null; }
    }

    private boolean matches(File file) {
        String[] types = request.getStringArrayExtra(Intent.EXTRA_MIME_TYPES);
        if (types == null || types.length == 0) types = new String[]{request.getType()};
        String actual = SdDocumentsProvider.mime(file);
        for (String type : types) if (type != null && ("*/*".equals(type) || actual.equals(type)
                || type.endsWith("/*") && actual.startsWith(type.substring(0, type.length() - 1)))) return true;
        return false;
    }

    private void show(File directory) {
        folder = directory;
        final int current = ++generation;
        list.setEnabled(false);
        title.setText(directory == null ? "共享位置" : directory.getName());
        worker.execute(() -> {
            ArrayList<File> found = new ArrayList<File>();
            String error = null;
            try {
                if (directory == null) found.addAll(roots);
                else {
                    File[] children = SdDocumentsProvider.checked(directory).listFiles();
                    if (children == null) throw new IOException("Cannot list shared directory");
                    if (children.length > 10000) throw new IOException("Shared directory has too many entries");
                    Arrays.sort(children, Comparator.comparing(File::isFile).thenComparing(File::getName, String.CASE_INSENSITIVE_ORDER));
                    for (File child : children) {
                        if (child.getName().startsWith(".")) continue;
                        try {
                            File file = SdDocumentsProvider.checked(child);
                            if (file.isDirectory() || file.isFile() && matches(file)) found.add(file);
                        } catch (IOException unavailable) { /* A removed or unreadable entry is omitted. */ }
                    }
                }
            } catch (IOException failure) { error = "无法读取文件夹"; }
            final String message = error;
            runOnUiThread(() -> {
                if (closed || current != generation) return;
                entries = found;
                ArrayList<String> labels = new ArrayList<String>();
                for (File file : entries) labels.add((file.isDirectory() ? "▸ " : "")
                        + (directory == null && file.getPath().equals(System.getenv("EXTERNAL_STORAGE")) ? "SailDroid 共享文件" : file.getName()));
                list.setAdapter(new ArrayAdapter<String>(this, multiple ? android.R.layout.simple_list_item_multiple_choice
                        : android.R.layout.simple_list_item_1, labels));
                for (int index = 0; index < entries.size(); index++) list.setItemChecked(index, selected.contains(entries.get(index)));
                list.setEnabled(true);
                if (message != null) title.setText(message);
                else if (entries.isEmpty()) title.setText(title.getText() + " · 没有匹配的文件");
            });
        });
    }

    private void select(int position) {
        File file = entries.get(position);
        if (file.isDirectory()) { show(file); return; }
        if (!multiple) { selected.add(file); complete(); return; }
        if (selected.contains(file)) selected.remove(file);
        else if (selected.size() < 256) selected.add(file);
        list.setItemChecked(position, selected.contains(file));
        choose.setText("选择 (" + selected.size() + ")");
        choose.setEnabled(!selected.isEmpty());
    }

    private void complete() {
        if (selected.isEmpty()) return;
        try {
            boolean persistable = Intent.ACTION_OPEN_DOCUMENT.equals(request.getAction());
            ArrayList<Uri> uris = SdDocumentsProvider.grant(selected, persistable);
            Intent result = new Intent().setDataAndType(uris.get(0), SdDocumentsProvider.mime(selected.iterator().next()))
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            if (persistable) result.addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
            ClipData clip = new ClipData("Selected files", new String[]{"*/*"}, new ClipData.Item(uris.get(0)));
            for (int index = 1; index < uris.size(); index++) clip.addItem(new ClipData.Item(uris.get(index)));
            result.setClipData(clip);
            setResult(RESULT_OK, result);
            System.err.println("SDDOCUMENT=selection_completed|count=" + uris.size() + "|persistable=" + persistable);
            finish();
        } catch (IOException | RuntimeException failure) {
            title.setText("所选文件已不可用，请重新选择");
            selected.clear();
            choose.setEnabled(false);
            System.err.println("SDDOCUMENT=selection_failed|type=" + failure.getClass().getName());
        }
    }

    private void up() {
        if (folder == null) { finish(); return; }
        show(roots.contains(folder) ? null : folder.getParentFile());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (resolve(intent, intent.getType()) == null) return;
        setIntent(intent);
        request = request(intent);
        multiple = request.getBooleanExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
        selected.clear();
        list.setChoiceMode(multiple ? ListView.CHOICE_MODE_MULTIPLE : ListView.CHOICE_MODE_NONE);
        choose.setEnabled(false);
        choose.setText("选择文件");
        choose.setVisibility(multiple ? android.view.View.VISIBLE : android.view.View.GONE);
        show(initialFolder());
    }

    @Override public void onBackPressed() { up(); }
    @Override protected void onDestroy() {
        closed = true;
        worker.shutdownNow();
        super.onDestroy();
    }
}
