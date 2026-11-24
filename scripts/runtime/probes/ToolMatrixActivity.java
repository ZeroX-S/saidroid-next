package org.example.saildroid.matrixprobe;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

/**
 * Integration-matrix probe, activity C.
 *
 * Declared in a secondary Android process (":tool") in the manifest. The host
 * co-hosts it inside the existing ART/UI container so the application keeps
 * one window stack and one Wayland surface; the runtime log must show
 * `SDACTIVITY=cohosted|declared_process=<package>:tool`.
 *
 * It finishes by itself so the previous Activity's resume can be asserted.
 */
public final class ToolMatrixActivity extends Activity {
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        MatrixActivity.log("ToolMatrixActivity", "create");
        TextView text = new TextView(this);
        text.setText("SailDroid matrix probe tool process");
        text.setTextSize(24);
        setContentView(text);
    }

    @Override protected void onStart() {
        super.onStart();
        MatrixActivity.log("ToolMatrixActivity", "start");
    }

    @Override protected void onPostCreate(Bundle state) {
        super.onPostCreate(state);
        MatrixActivity.log("ToolMatrixActivity", "post_create");
    }

    @Override protected void onResume() {
        super.onResume();
        MatrixActivity.log("ToolMatrixActivity", "resume");
        new android.os.Handler(getMainLooper()).postDelayed(new Runnable() {
            public void run() {
                finish();
            }
        }, 2500);
    }

    @Override protected void onPause() {
        MatrixActivity.log("ToolMatrixActivity", "pause");
        super.onPause();
    }

    @Override protected void onStop() {
        MatrixActivity.log("ToolMatrixActivity", "stop");
        super.onStop();
    }

    @Override protected void onDestroy() {
        MatrixActivity.log("ToolMatrixActivity", "destroy");
        super.onDestroy();
    }
}
