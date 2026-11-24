package org.example.saildroid.lifecycle;
import android.app.*;import android.os.*;import android.content.*;
public final class LifecycleActivity extends Activity {
 @Override public void onCreate(Bundle state){super.onCreate(state);startService(new Intent(this,LifecycleService.class));System.err.println("LIFECYCLE_OWNER=started");}
}
