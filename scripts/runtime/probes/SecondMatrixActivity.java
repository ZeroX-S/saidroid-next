package org.example.saildroid.matrixprobe;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

/** Integration-matrix probe, activity B: same package, default process. */
public final class SecondMatrixActivity extends Activity {
    private boolean chained;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        MatrixActivity.log("SecondMatrixActivity", "create");
        TextView text = new TextView(this);
        text.setText("SailDroid matrix probe B");
        text.setTextSize(28);
        setContentView(text);
    }

    @Override protected void onStart() {
        super.onStart();
        MatrixActivity.log("SecondMatrixActivity", "start");
    }

    @Override protected void onPostCreate(Bundle state) {
        super.onPostCreate(state);
        MatrixActivity.log("SecondMatrixActivity", "post_create");
    }

    @Override protected void onResume() {
        super.onResume();
        MatrixActivity.log("SecondMatrixActivity", "resume");
        if (chained) return;
        chained = true;
        new android.os.Handler(getMainLooper()).postDelayed(new Runnable() {
            public void run() {
                startActivity(new Intent(SecondMatrixActivity.this, ToolMatrixActivity.class));
            }
        }, 1800);
    }

    @Override protected void onPause() {
        MatrixActivity.log("SecondMatrixActivity", "pause");
        super.onPause();
    }

    @Override protected void onStop() {
        MatrixActivity.log("SecondMatrixActivity", "stop");
        super.onStop();
    }

    @Override protected void onDestroy() {
        MatrixActivity.log("SecondMatrixActivity", "destroy");
        super.onDestroy();
    }
}
