package org.example.saildroid.launchmodes;
import android.app.*;import android.content.*;import android.os.*;import android.widget.*;
public final class MainActivity extends Activity {
 static int instances;int resumes;boolean child;Button status;
 @Override public void onCreate(Bundle state){super.onCreate(state);instances++;child=getIntent().getBooleanExtra("child",false);status=new Button(this);status.setText(child?"Fresh standard Activity":"Launch mode regression");setContentView(status);
  if(child){if(instances!=2||isTaskRoot())throw new AssertionError("Standard child instance/root state differs");System.err.println("SD_LAUNCH_PROBE=standard_created|instances=2|is_task_root=false");new Handler().postDelayed(()->startActivity(new Intent(this,MainActivity.class).putExtra("child",true).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)),350);}
  else{status.setOnClickListener(v->{if(resumes!=3)throw new AssertionError("Return state differs");status.setText("Physical return touch passed");System.err.println("SD_LAUNCH_PROBE=return_touch_passed|resumes=3");});new Handler().postDelayed(()->startActivity(new Intent(this,MainActivity.class).putExtra("child",true)),350);}
 }
 @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);if(!child)throw new AssertionError("Standard repeated class incorrectly reused");if(instances!=2||(intent.getFlags()&Intent.FLAG_ACTIVITY_SINGLE_TOP)==0)throw new AssertionError("SingleTop flag state differs");System.err.println("SD_LAUNCH_PROBE=flag_reused|instances=2");new Handler().postDelayed(()->onBackPressed(),350);}
 @Override protected void onResume(){super.onResume();resumes++;if(!child&&resumes==2)new Handler().postDelayed(()->startActivity(new Intent(this,SingleTopActivity.class)),350);if(!child&&resumes==3){status.setText("Launch modes passed");System.err.println("SD_LAUNCH_PROBE=flow_passed|resumes=3|standard_instances=2|single_top_instances="+SingleTopActivity.instances);}}
}
