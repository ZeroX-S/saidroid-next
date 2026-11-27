package org.example.saildroid.matrixprobe;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.widget.TextView;

/**
 * Integration-matrix probe, activity A (launcher, default process).
 *
 * It drives a deterministic Activity chain without human input so the host's
 * Activity switching / secondary-process co-hosting can be asserted from the
 * runtime log: every real lifecycle callback is printed with a monotonic
 * timestamp, and A -> B -> Tool runs by itself.
 */
public class MatrixActivity extends Activity {
    static final String TAG = "APIMATRIX=lifecycle";
    private boolean chained;

    static void log(String activity, String event) {
        System.err.println(TAG + "|activity=" + activity + "|event=" + event
                + "|t=" + SystemClock.elapsedRealtime());
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        log("MatrixActivity", "create");
        TextView text = new TextView(this);
        text.setText("SailDroid matrix probe A");
        text.setTextSize(28);
        setContentView(text);
    }

    @Override protected void onStart() {
        super.onStart();
        log("MatrixActivity", "start");
    }

    @Override protected void onPostCreate(Bundle state) {
        super.onPostCreate(state);
        log("MatrixActivity", "post_create");
    }

    @Override protected void onResume() {
        super.onResume();
        log("MatrixActivity", "resume");
        if (chained) return;
        chained = true;
        new android.os.Handler(getMainLooper()).postDelayed(new Runnable() {
            public void run() {
                startActivity(new Intent(MatrixActivity.this, SecondMatrixActivity.class));
            }
        }, 1800);
    }

    @Override protected void onPause() {
        log("MatrixActivity", "pause");
        super.onPause();
    }

    @Override protected void onStop() {
        log("MatrixActivity", "stop");
        super.onStop();
    }

    @Override protected void onDestroy() {
        log("MatrixActivity", "destroy");
        super.onDestroy();
    }
}
