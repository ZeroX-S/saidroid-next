package org.example.saildroid.nativedisplay;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public final class NativeDisplayActivity extends Activity {
    static { System.loadLibrary("nativedisplayprobe"); }
    private static native String checkNativeDisplay();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        final TextView view = new TextView(this);
        view.setText("Checking native display callbacks");
        setContentView(view);
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    final String result = checkNativeDisplay();
                    System.err.println("API28_COMPAT=" + result);
                    runOnUiThread(new Runnable() {
                        @Override public void run() { view.setText(result); }
                    });
                } catch (Throwable failure) {
                    System.err.println("API28_COMPAT=failed|" + failure);
                }
            }
        }, "native-display-probe").start();
    }
}
