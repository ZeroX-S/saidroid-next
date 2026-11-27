package org.example.saildroid.launchmodes;
import android.app.*;import android.content.*;import android.os.*;import android.widget.*;
public final class SingleTopActivity extends Activity {
 static int instances;
 @Override public void onCreate(Bundle state){super.onCreate(state);instances++;if(instances!=1)throw new AssertionError("Manifest singleTop created duplicate");TextView view=new TextView(this);view.setText("Manifest singleTop");setContentView(view);new Handler().postDelayed(()->startActivity(new Intent(this,SingleTopActivity.class)),350);}
 @Override protected void onNewIntent(Intent value){super.onNewIntent(value);if(instances!=1)throw new AssertionError("Manifest reuse state differs");System.err.println("SD_LAUNCH_PROBE=manifest_reused|instances=1");new Handler().postDelayed(()->finish(),350);}
}
