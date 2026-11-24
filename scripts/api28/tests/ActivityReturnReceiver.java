package org.example.saildroid.api28return;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.SystemClock;
import android.widget.TextView;
import java.io.File;

public final class ActivityReturnReceiver extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        int producer = getIntent().getIntExtra("producer_pid", -1);
        if (producer <= 0 || producer == android.os.Process.myPid())
            throw new AssertionError("Return did not cross processes");
        // Hold the receiver's launch transaction until the producer is gone.
        // This makes the late READY notification race deterministic.
        long deadline = SystemClock.uptimeMillis() + 10000;
        File process = new File("/proc/" + producer);
        while (process.exists() && SystemClock.uptimeMillis() < deadline)
            SystemClock.sleep(20);
        if (process.exists()) throw new AssertionError("Producer remained alive");
        if (!"captured-media-result".equals(getIntent().getStringExtra("result_value")))
            throw new AssertionError("Return intent lost its payload");
        TextView status = new TextView(this);
        status.setText("Process return passed");
        setContentView(status);
        new Handler().postDelayed(() ->
                System.err.println("API28_RETURN=passed|producer_ended=true|payload_preserved=true"), 1500);
    }
}
