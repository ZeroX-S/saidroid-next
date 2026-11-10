package org.example.saildroid.api28return;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;

public final class ActivityReturnProducer extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        // Let the initial launch finish before starting the return transition.
        new Handler().postDelayed(() -> {
            Intent result = new Intent(this, ActivityReturnReceiver.class);
            result.putExtra("producer_pid", android.os.Process.myPid());
            result.putExtra("result_value", "captured-media-result");
            startActivity(result);
            finish();
        }, 500);
    }
}
