package org.example.saildroid.remoteactivity;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Process;
import android.widget.*;
import android.view.View;

/** Ordinary APK contract: a manifest process boundary, Intent and result. */
public final class ParentActivity extends Activity {
    public static boolean visited;
    boolean resumed,resultReceived,valid;
    int completed;
    TextView status;
    @Override public void onCreate(Bundle state){
        super.onCreate(state);visited=true;
        int componentState=getPackageManager().getComponentEnabledSetting(getComponentName());
        if(componentState!=android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DEFAULT)throw new IllegalStateException("Manifest component state differs");
        try{getPackageManager().getComponentEnabledSetting(new android.content.ComponentName(getPackageName(),getPackageName()+".Missing"));throw new AssertionError("Unknown component accepted");}catch(IllegalArgumentException expected){}
        System.err.println("REMOTE_ACTIVITY=component_state|default=true|unknown_rejected=true");
        android.media.AudioManager audio=(android.media.AudioManager)getSystemService(AUDIO_SERVICE);
        int volume=audio.getStreamVolume(android.media.AudioManager.STREAM_MUSIC);
        int max=audio.getStreamMaxVolume(android.media.AudioManager.STREAM_MUSIC);
        android.media.AudioDeviceInfo[] outputs=audio.getDevices(android.media.AudioManager.GET_DEVICES_OUTPUTS);
        if(volume<0||volume>max||outputs.length==0)throw new IllegalStateException("Host audio queries unavailable");
        System.err.println("REMOTE_ACTIVITY=audio|volume="+volume+"|max="+max+"|outputs="+outputs.length+"|ringer="+audio.getRingerMode());
        overridePendingTransition(android.R.anim.fade_in,android.R.anim.fade_out);
        android.os.BatteryManager battery=(android.os.BatteryManager)getSystemService(BATTERY_SERVICE);
        int capacity=battery.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_CAPACITY);
        int batteryStatus=battery.getIntProperty(android.os.BatteryManager.BATTERY_PROPERTY_STATUS);
        if(capacity<0||capacity>100||batteryStatus<1||batteryStatus>5)throw new IllegalStateException("Host battery query unavailable");
        System.err.println("REMOTE_ACTIVITY=battery|capacity="+capacity+"|status="+batteryStatus+"|source=power_supply");
        Thread scheduling=new Thread(new Runnable(){public void run(){android.os.Process.setThreadPriority(-10);if(android.os.Process.getThreadPriority(android.os.Process.myTid())!=-10)throw new IllegalStateException("Android thread priority was not applied");android.os.Process.setThreadPriority(0);System.err.println("REMOTE_ACTIVITY=thread_priority|nice=-10|restored=0");}});scheduling.start();try{scheduling.join(3000);}catch(InterruptedException failure){throw new IllegalStateException(failure);}
        LinearLayout page=new LinearLayout(this);page.setOrientation(1);page.setPadding(32,120,32,32);page.setBackgroundColor(0xffe0f2fe);
        status=new TextView(this);status.setTextSize(26);status.setText("Parent process\nTap to open declared :tool Activity");page.addView(status,new LinearLayout.LayoutParams(-1,260));
        Button button=new Button(this);button.setText("Open remote Activity");page.addView(button,new LinearLayout.LayoutParams(-1,240));
        button.setOnClickListener(new View.OnClickListener(){public void onClick(View view){
            resultReceived=false;valid=false;
            Intent intent=new Intent(ParentActivity.this,ChildActivity.class).putExtra("parentPid",Process.myPid()).putExtra("round",completed+1).putExtra("proof","cross-process-intent");
            startActivityForResult(intent,73);System.err.println("REMOTE_ACTIVITY=parent_requested|pid="+Process.myPid());
        }});setContentView(page);System.err.println("REMOTE_ACTIVITY=parent_created|pid="+Process.myPid());
    }
    @Override public void onPause(){resumed=false;super.onPause();System.err.println("REMOTE_ACTIVITY=parent_paused");}
    @Override public void onStop(){super.onStop();System.err.println("REMOTE_ACTIVITY=parent_stopped");}
    @Override public void onResume(){super.onResume();resumed=true;System.err.println("REMOTE_ACTIVITY=parent_resumed");if(resultReceived){status.setText(valid?"PASS: real remote Activity and result":"FAIL: remote Activity contract");System.err.println("REMOTE_ACTIVITY="+(valid?"PASS":"FAIL")+"|result_before_resume=true");}}
    @Override public void onActivityResult(int request,int code,Intent data){
        super.onActivityResult(request,code,data);resultReceived=true;completed++;
        valid=!resumed&&request==73&&code==RESULT_OK&&data!=null&&"remote-result".equals(data.getStringExtra("proof"))&&data.getBooleanExtra("isolated",false)&&data.getBooleanExtra("provider",false)&&data.getBooleanExtra("store",false)&&SharedProvider.calls==completed&&data.getIntExtra("childPid",-1)!=Process.myPid()&&(getPackageName()+":tool").equals(data.getStringExtra("process"));
        System.err.println("REMOTE_ACTIVITY=result_received|request="+request+"|result="+code+"|before_resume="+!resumed+"|valid="+valid);
    }
}
