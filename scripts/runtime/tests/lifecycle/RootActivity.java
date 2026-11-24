package org.example.saildroid.lifecycle;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.widget.TextView;

public final class RootActivity extends Activity {
    private int resumes;
    private TextView text;
    private boolean resultReceived;
    @Override public void onCreate(Bundle state){super.onCreate(state);text=new TextView(this);text.setText("Android lifecycle regression\nRoot Activity");text.setTextSize(28);setContentView(text);}
    @Override public void onResume(){
        super.onResume();resumes++;
        if(resumes==1){new Handler().postDelayed(new Runnable(){public void run(){LifecycleApplication.transition=true;startActivityForResult(new Intent(RootActivity.this,ChildActivity.class),37);}},800);}
        else if(LifecycleApplication.childSeen)new Handler().postDelayed(new Runnable(){public void run(){
            LifecycleApplication.require(resultReceived,"child-result-missing");
            LifecycleApplication.require(LifecycleApplication.started==1,"root-return-started-count");
            LifecycleApplication.require(LifecycleApplication.resumed==1,"root-return-resumed-count");
            LifecycleApplication.transition=false;LifecycleApplication.returns++;
            System.err.println("LIFECYCLE_CONTRACT="+(LifecycleApplication.violations==0?"PASS":"FAIL")+"|violations="+LifecycleApplication.violations+"|returns="+LifecycleApplication.returns+"|actual_android_callbacks=true");
            text.setText("Android lifecycle regression\nReturned to Root\nViolations: "+LifecycleApplication.violations);
        }},500);
    }
    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
        super.onActivityResult(requestCode,resultCode,data);
        LifecycleApplication.require(resumes==1,"result-delivered-after-parent-resume");
        LifecycleApplication.require(requestCode==37&&resultCode==RESULT_OK&&data!=null&&"real-child-result".equals(data.getStringExtra("payload")),"result-routing-or-payload");
        resultReceived=true;System.err.println("LIFECYCLE=result_received|request_code="+requestCode+"|result_code="+resultCode+"|before_resume=true");
    }
}
