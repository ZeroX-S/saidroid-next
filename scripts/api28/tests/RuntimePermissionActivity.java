package org.example.saildroid.api28permissions;

import android.app.Activity;
import android.app.AppOpsManager;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.hardware.Camera;
import android.net.Uri;
import android.os.Bundle;
import android.os.Process;
import android.provider.MediaStore;
import android.provider.Settings;
import android.view.HapticFeedbackConstants;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Ordinary APK entry for permission callbacks, real media, camera and settings. */
public final class RuntimePermissionActivity extends Activity {
    private static final String READ = "android.permission.READ_EXTERNAL_STORAGE";
    private static final String WRITE = "android.permission.WRITE_EXTERNAL_STORAGE";
    private static final String CAMERA = "android.permission.CAMERA";
    private static final String UNKNOWN = "org.example.saildroid.api28permissions.UNDECLARED";
    private static final String FIXTURE = "saildroid-api28-permission-regression-20261108.png";
    private TextView status;
    private int attempts;
    private int settingsVisits;
    private int resumes;
    private boolean hapticsChecked;

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        status = new TextView(this);
        content.addView(status);
        Button files = button(content, "files", "Request files");
        Button camera = button(content, "camera", "Request camera");
        Button settings = button(content, "settings", "Open permissions");
        files.setOnClickListener(view -> requestFiles());
        files.setOnLongClickListener(view -> {
            System.err.println("API28_PERMISSION_UI=long_press_passed");
            return true;
        });
        camera.setOnClickListener(view -> requestPermissions(new String[]{CAMERA}, 73));
        settings.setOnClickListener(view -> {
            settingsVisits++;
            startActivityForResult(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + getPackageName())), 80);
        });
        setContentView(content);
        require(checkSelfPermission(UNKNOWN) == PackageManager.PERMISSION_DENIED, "Undeclared permission granted");
        require(checkSelfPermission("android.permission.INTERNET") == PackageManager.PERMISSION_GRANTED, "Normal permission lost");
        if (checkSelfPermission(READ) == PackageManager.PERMISSION_GRANTED) {
            verifyMedia();
            status.setText("Persisted permission passed");
            System.err.println("API28_PERMISSION_UI=persistence_passed");
        } else {
            require(!shouldShowRequestPermissionRationale(READ), "Fresh denial history inferred");
            requestFiles();
        }
    }

    private Button button(LinearLayout content, final String name, String title) {
        final Button button = new Button(this);
        button.setText(title);
        content.addView(button);
        button.post(() -> {
            int[] point = new int[2];
            button.getLocationOnScreen(point);
            System.err.println("API28_PERMISSION_UI=button|name=" + name + "|x="
                    + (point[0] + button.getWidth() / 2) + "|y=" + (point[1] + button.getHeight() / 2));
        });
        return button;
    }

    private void requestFiles() {
        attempts++;
        requestPermissions(new String[]{READ, WRITE, UNKNOWN}, 70 + attempts);
    }

    @Override public void onResume() {
        super.onResume();
        resumes++;
        System.err.println("API28_PERMISSION_UI=resumed|count=" + resumes);
    }

    @Override public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (!focus || hapticsChecked) return;
        hapticsChecked = true;
        int flags = HapticFeedbackConstants.FLAG_IGNORE_VIEW_SETTING
                | HapticFeedbackConstants.FLAG_IGNORE_GLOBAL_SETTING;
        for (int effect : new int[]{HapticFeedbackConstants.LONG_PRESS,
                HapticFeedbackConstants.KEYBOARD_TAP, HapticFeedbackConstants.VIRTUAL_KEY}) {
            require(!status.performHapticFeedback(effect, flags), "Unavailable vibration advertised");
        }
        System.err.println("API28_PERMISSION_UI=haptic_api_passed|calls=3");
    }

    @Override public void onRequestPermissionsResult(int code, String[] names, int[] results) {
        super.onRequestPermissionsResult(code, names, results);
        if (code == 73) {
            require(names.length == 1 && CAMERA.equals(names[0]) && results[0] == PackageManager.PERMISSION_GRANTED,
                    "Camera permission callback differs");
            require(checkSelfPermission(CAMERA) == PackageManager.PERMISSION_GRANTED, "Camera grant not visible");
            int count = Camera.getNumberOfCameras();
            require(count > 0, "Real camera inventory missing");
            Camera camera = Camera.open(0);
            try { require(camera.getParameters().getSupportedPictureSizes().size() > 0, "Camera parameters missing"); }
            finally { camera.release(); }
            System.err.println("API28_PERMISSION_UI=camera_open_passed|count=" + count + "|photos_taken=0");
            return;
        }
        require(code == 70 + attempts && names.length == 3 && results.length == 3
                && READ.equals(names[0]) && WRITE.equals(names[1]) && UNKNOWN.equals(names[2])
                && results[2] == PackageManager.PERMISSION_DENIED, "File permission result routing differs");
        if (attempts == 1) {
            require(results[0] == PackageManager.PERMISSION_DENIED && results[1] == PackageManager.PERMISSION_DENIED
                    && shouldShowRequestPermissionRationale(READ), "User denial not recorded");
            verifyChecks(false);
            status.setText("Denied. Request files again");
            System.err.println("API28_PERMISSION_UI=denial_passed");
        } else {
            require(attempts == 2 && results[0] == PackageManager.PERMISSION_GRANTED
                    && results[1] == PackageManager.PERMISSION_GRANTED && !shouldShowRequestPermissionRationale(READ),
                    "Reauthorization differs");
            verifyChecks(true);
            verifyMedia();
            status.setText("File permission flow passed");
            System.err.println("API28_PERMISSION_UI=flow_passed|callbacks=2");
        }
    }

    @Override public void onActivityResult(int requestCode, int resultCode, Intent value) {
        super.onActivityResult(requestCode, resultCode, value);
        require(requestCode == 80 && resultCode == RESULT_OK, "Settings result callback differs");
        boolean expected = settingsVisits != 2;
        verifyChecks(expected);
        if (expected) verifyMedia();
        System.err.println("API28_PERMISSION_UI=settings_return|visit=" + settingsVisits + "|granted=" + expected);
    }

    private void verifyChecks(boolean granted) {
        int permission = granted ? PackageManager.PERMISSION_GRANTED : PackageManager.PERMISSION_DENIED;
        require(checkSelfPermission(READ) == permission, "ActivityManager grant differs");
        require(getPackageManager().checkPermission(READ, getPackageName()) == permission, "PackageManager grant differs");
        AppOpsManager operations = (AppOpsManager) getSystemService(APP_OPS_SERVICE);
        require(operations.checkOpNoThrow(AppOpsManager.OPSTR_READ_EXTERNAL_STORAGE, Process.myUid(), getPackageName())
                == (granted ? AppOpsManager.MODE_ALLOWED : AppOpsManager.MODE_IGNORED), "AppOps grant differs");
        try {
            PackageInfo info = getPackageManager().getPackageInfo(getPackageName(), PackageManager.GET_PERMISSIONS);
            for (int index = 0; index < info.requestedPermissions.length; index++) if (READ.equals(info.requestedPermissions[index])) {
                require(((info.requestedPermissionsFlags[index] & PackageInfo.REQUESTED_PERMISSION_GRANTED) != 0) == granted,
                        "Requested permission flags differ");
                return;
            }
            throw new AssertionError("Manifest permission missing");
        } catch (PackageManager.NameNotFoundException failure) { throw new AssertionError(failure); }
    }

    private void verifyMedia() {
        try (Cursor cursor = getContentResolver().query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                new String[]{"_id", "_data", "width", "height"}, "_display_name = ?", new String[]{FIXTURE}, null)) {
            require(cursor != null && cursor.getCount() == 1 && cursor.moveToFirst(), "Controlled media fixture missing");
            require(cursor.getInt(2) == 1 && cursor.getInt(3) == 1, "Real image dimensions differ");
            Uri uri = android.content.ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cursor.getLong(0));
            try (java.io.InputStream input = getContentResolver().openInputStream(uri)) {
                require(input.read() == 137 && input.read() == 80, "Real media file bytes differ");
            }
            System.err.println("API28_PERMISSION_UI=media_passed|rows=1");
        } catch (java.io.IOException failure) { throw new AssertionError(failure); }
    }
}
