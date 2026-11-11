import android.app.Activity;
import android.app.ActivityThread;
import android.app.AlertDialog;
import android.app.ResultInfo;
import android.content.ComponentName;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.os.IBinder;
import android.provider.Settings;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/** The API29 permission prompt and per-app choices hosted in the requesting task. */
public final class SdPermissionController {
    public static final String PACKAGE = "org.saildroid.permissioncontroller";
    private static final Map<IBinder, AlertDialog> pending = new HashMap<IBinder, AlertDialog>();

    public static boolean accepts(Intent intent) {
        return PackageManager.ACTION_REQUEST_PERMISSIONS.equals(intent.getAction())
                && PACKAGE.equals(intent.getPackage()) && intent.getComponent() == null;
    }

    public static boolean acceptsSettings(Intent intent) {
        if (!Settings.ACTION_APPLICATION_DETAILS_SETTINGS.equals(intent.getAction())) return false;
        if (intent.getData() == null || !"package".equals(intent.getData().getScheme())
                || !SdApkPackage.NAME.equals(intent.getData().getSchemeSpecificPart())) return false;
        ComponentName component = intent.getComponent();
        String target = component == null ? intent.getPackage() : component.getPackageName();
        return target == null || PACKAGE.equals(target) || "com.android.settings".equals(target);
    }

    public static ActivityInfo settingsActivityInfo() {
        ActivityInfo info = new ActivityInfo();
        info.packageName = PACKAGE;
        info.name = SdPermissionController.class.getName();
        info.processName = SdApkPackage.processName();
        info.applicationInfo = SdApkPackage.applicationInfo();
        info.nonLocalizedLabel = "应用权限";
        info.enabled = true;
        return info;
    }

    public static ResolveInfo resolveSettings(Intent intent) {
        if (!acceptsSettings(intent)) return null;
        ResolveInfo info = new ResolveInfo();
        info.activityInfo = settingsActivityInfo();
        info.isDefault = true;
        return info;
    }

    private static String label(String name) {
        if ("android.permission.CAMERA".equals(name)) return "摄像头";
        if ("android.permission.READ_EXTERNAL_STORAGE".equals(name)) return "读取照片和共享文件";
        if ("android.permission.WRITE_EXTERNAL_STORAGE".equals(name)) return "写入共享文件";
        if ("android.permission.RECORD_AUDIO".equals(name)) return "麦克风";
        return name.replace("android.permission.", "");
    }

    public static void request(Activity activity, IBinder token, Intent intent, String who, int code) {
        if (!accepts(intent) || pending.containsKey(token)) throw new IllegalStateException("Invalid or overlapping permission request");
        String[] requested = intent.getStringArrayExtra(PackageManager.EXTRA_REQUEST_PERMISSIONS_NAMES);
        if (requested == null || requested.length > 64) throw new IllegalArgumentException("Invalid requested permission array");
        for (String name : requested) if (name == null || name.isEmpty()) throw new IllegalArgumentException("Permission name is empty");
        try {
            Request request = new Request(activity, token, requested.clone(), who, code);
            pending.put(token, null);
            request.show();
        } catch (Exception failure) {
            cancel(token);
            throw new IllegalStateException("Permission request failed", failure);
        }
    }

    private static final class Request implements DialogInterface.OnClickListener, DialogInterface.OnCancelListener {
        final Activity activity;
        final IBinder token;
        final String[] names;
        final String who;
        final int code;
        final SdAppPermissions state;
        boolean completed;

        Request(Activity owner, IBinder ownerToken, String[] requested, String resultWho, int requestCode) throws Exception {
            activity = owner;
            token = ownerToken;
            names = requested;
            who = resultWho;
            code = requestCode;
            state = new SdAppPermissions(SdApkPackage.APK, SdApkPackage.NAME);
        }

        void show() {
            StringBuilder access = new StringBuilder();
            for (String name : names) if (state.supported(name) && !state.holds(name)) {
                if (access.length() > 0) access.append("\n");
                access.append("• ").append(label(name));
            }
            if (access.length() == 0) { finish(false, false); return; }
            CharSequence appLabel = activity.getApplicationInfo().loadLabel(activity.getPackageManager());
            AlertDialog dialog = new AlertDialog.Builder(activity).setTitle("允许“" + appLabel + "”访问以下内容？")
                    .setMessage(access.toString()).setPositiveButton("允许", this).setNegativeButton("不允许", this)
                    .setOnCancelListener(this).create();
            dialog.setOnDismissListener(ignored -> finish(false, false));
            pending.put(token, dialog);
            dialog.show();
            logButtons(dialog, code);
            System.err.println("SDPERMISSION=prompt_shown|request_code=" + code + "|count=" + names.length);
        }

        @Override public void onClick(DialogInterface dialog, int button) {
            finish(button == DialogInterface.BUTTON_POSITIVE, true);
        }

        @Override public void onCancel(DialogInterface dialog) { finish(false, true); }

        void finish(boolean grant, boolean save) {
            if (completed || !pending.containsKey(token)) return;
            completed = true;
            pending.remove(token);
            if (save) {
                Map<String, Boolean> choices = new LinkedHashMap<String, Boolean>();
                for (String name : names) if (state.supported(name) && !state.holds(name)) choices.put(name, grant);
                try { state.decide(choices); }
                catch (RuntimeException failure) {
                    System.err.println("SDPERMISSION=save_failed|type=" + failure.getClass().getName());
                }
            }
            if (activity.isFinishing() || activity.isDestroyed()
                    || ActivityThread.currentActivityThread().getActivityClient(token) == null) return;
            int[] grants = new int[names.length];
            for (int index = 0; index < names.length; index++) {
                grants[index] = state.holds(names[index]) ? PackageManager.PERMISSION_GRANTED : PackageManager.PERMISSION_DENIED;
                System.err.println("SDPERMISSION=result|permission=" + names[index] + "|granted="
                        + (grants[index] == PackageManager.PERMISSION_GRANTED) + "|request_code=" + code);
            }
            Intent result = new Intent().putExtra(PackageManager.EXTRA_REQUEST_PERMISSIONS_NAMES, names)
                    .putExtra(PackageManager.EXTRA_REQUEST_PERMISSIONS_RESULTS, grants);
            ArrayList<ResultInfo> results = new ArrayList<ResultInfo>();
            results.add(new ResultInfo(who, code, Activity.RESULT_OK, result));
            ActivityThread.currentActivityThread().handleSendResult(token, results, "SailDroid runtime permission decision");
            System.err.println("SDPERMISSION=callback_delivered|request_code=" + code + "|count=" + names.length);
        }
    }

    public static void showSettings(final Activity activity, final IBinder token, final String who, final int code) {
        if (pending.containsKey(token)) throw new IllegalStateException("Permission dialog is already open");
        try {
            final SdAppPermissions state = new SdAppPermissions(SdApkPackage.APK, SdApkPackage.NAME);
            final Map<String, CheckBox> controls = new LinkedHashMap<String, CheckBox>();
            LinearLayout content = new LinearLayout(activity);
            content.setOrientation(LinearLayout.VERTICAL);
            int padding = Math.round(20 * activity.getResources().getDisplayMetrics().density);
            content.setPadding(padding, padding, padding, padding);
            for (String name : state.getRuntimePermissions()) {
                CheckBox control = new CheckBox(activity);
                boolean supported = state.supported(name);
                control.setText(label(name) + (supported ? "" : "（后端尚不可用）"));
                control.setChecked(state.holds(name));
                control.setEnabled(supported);
                controls.put(name, control);
                content.addView(control);
            }
            ScrollView scroll = new ScrollView(activity);
            scroll.addView(content);
            CharSequence appLabel = activity.getApplicationInfo().loadLabel(activity.getPackageManager());
            AlertDialog dialog = new AlertDialog.Builder(activity).setTitle(appLabel + " · 应用权限").setView(scroll)
                    .setPositiveButton("保存", (ignored, button) -> {
                        Map<String, Boolean> choices = new LinkedHashMap<String, Boolean>();
                        for (Map.Entry<String, CheckBox> entry : controls.entrySet()) {
                            if (entry.getValue().isEnabled()) choices.put(entry.getKey(), entry.getValue().isChecked());
                        }
                        try {
                            state.decide(choices);
                            System.err.println("SDPERMISSION=settings_saved|count=" + choices.size());
                        } catch (RuntimeException failure) {
                            System.err.println("SDPERMISSION=save_failed|type=" + failure.getClass().getName());
                        }
                    }).setNegativeButton("取消", null).create();
            dialog.setOnDismissListener(ignored -> {
                if (!pending.containsKey(token)) return;
                pending.remove(token);
                SdActivityHost.permissionSettingsClosed(token, who, code);
            });
            pending.put(token, dialog);
            dialog.show();
            logButtons(dialog, code);
            if (System.getenv("SAILDROID_DIAG_INPUT") != null) scroll.post(() -> {
                for (Map.Entry<String, CheckBox> entry : controls.entrySet()) {
                    CheckBox control = entry.getValue();
                    int[] point = new int[2];
                    control.getLocationOnScreen(point);
                    System.err.println("SDPERMISSION=settings_control|permission=" + entry.getKey()
                            + "|enabled=" + control.isEnabled() + "|checked=" + control.isChecked()
                            + "|x=" + (point[0] + control.getWidth() / 2) + "|y=" + (point[1] + control.getHeight() / 2));
                }
            });
            System.err.println("SDPERMISSION=settings_shown|count=" + controls.size());
        } catch (Exception failure) {
            cancel(token);
            SdActivityHost.permissionSettingsClosed(token, who, code);
            throw new IllegalStateException("Cannot open application permissions", failure);
        }
    }

    private static void logButtons(final AlertDialog dialog, final int code) {
        if (System.getenv("SAILDROID_DIAG_INPUT") == null) return;
        dialog.getWindow().getDecorView().post(() -> {
            for (int button : new int[]{DialogInterface.BUTTON_POSITIVE, DialogInterface.BUTTON_NEGATIVE}) {
                android.widget.Button control = dialog.getButton(button);
                int[] point = new int[2];
                control.getLocationOnScreen(point);
                System.err.println("SDPERMISSION=button_geometry|request_code=" + code + "|choice="
                        + (button == DialogInterface.BUTTON_POSITIVE ? "allow" : "deny")
                        + "|x=" + (point[0] + control.getWidth() / 2) + "|y=" + (point[1] + control.getHeight() / 2));
            }
        });
    }

    public static void cancel(IBinder token) {
        AlertDialog dialog = pending.remove(token);
        if (dialog != null) dialog.dismiss();
    }
}
