package org.saildroid.compat;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Declared secondary-process receiver used by package identity contracts. */
public final class ProbeReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {}
}
