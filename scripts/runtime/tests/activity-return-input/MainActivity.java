package org.example.saildroid.finish;
import android.app.Activity;import android.os.Bundle;import android.os.Handler;import android.content.Intent;import android.widget.TextView;import android.widget.Button;
public final class MainActivity extends Activity {
 int resumes;TextView status;
 public void onCreate(Bundle state){super.onCreate(state);status=new Button(this);status.setOnClickListener(v->{status.setText("Physical return touch passed");System.err.println("SD_RETURN_TOUCH=clicked|resumes="+resumes+"|destroyed="+ChildActivity.destroyed);});status.setText("Activity finish regression");setContentView(status);new Handler().postDelayed(()->startActivity(new Intent(this,ChildActivity.class)),200);}
 public void onResume(){super.onResume();resumes++;System.err.println("SD_FINISH_PROBE=main_resumed|count="+resumes);if(resumes==2)new Handler().postDelayed(()->{if(!ChildActivity.destroyed||!ChildActivity.secondAccepted)throw new AssertionError("Delayed finish incomplete");status.setText("Repeated finish passed");System.err.println("SD_FINISH_PROBE=passed|resumes="+resumes+"|destroyed=true|second=true");},1700);}
}
