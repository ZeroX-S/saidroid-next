package org.example.saildroid.api28return;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

/** A separate-process producer launches its successor and immediately finishes. */
public final class ActivityReturnProbe extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        TextView status = new TextView(this);
        status.setText("Checking process return");
        setContentView(status);
        startActivity(new Intent(this, ActivityReturnProducer.class));
    }
}
