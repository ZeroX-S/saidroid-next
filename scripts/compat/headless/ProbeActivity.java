package org.saildroid.compat;

import android.app.Activity;
import android.content.Intent;

/** Receives an application-owned Parcelable through the production Intent path. */
public final class ProbeActivity extends Activity {
    public String received;
    @Override public ClassLoader getClassLoader() { return ProbeActivity.class.getClassLoader(); }
    @Override public void onNewIntent(Intent intent) {
        Payload payload = intent.getParcelableExtra("payload");
        if (payload == null) throw new AssertionError("Parcelable result missing");
        received = payload.value;
    }
}
