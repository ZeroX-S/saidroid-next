package org.example.saildroid.finish;
import android.app.Activity;import android.os.Bundle;import android.os.Handler;import android.widget.TextView;
public final class ChildActivity extends Activity {
 static boolean destroyed,secondAccepted;
 public void onCreate(Bundle state){super.onCreate(state);TextView v=new TextView(this);v.setText("Child closes twice");setContentView(v);Handler h=new Handler();h.postDelayed(()->{System.err.println("SD_FINISH_PROBE=first_request");finish();},300);h.postDelayed(()->{if(!destroyed)throw new AssertionError("First finish did not destroy child");System.err.println("SD_FINISH_PROBE=second_request|destroyed=true");finish();secondAccepted=true;System.err.println("SD_FINISH_PROBE=second_accepted");},1000);}
 public void onDestroy(){super.onDestroy();destroyed=true;System.err.println("SD_FINISH_PROBE=child_destroyed");}
}
