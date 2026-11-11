package org.example.saildroid.remoteactivity;

import android.app.Activity;
import android.app.Application;
import android.content.Intent;
import android.os.*;
import android.os.Process;
import android.widget.*;
import android.view.View;

public final class ChildActivity extends Activity {
    @Override public void onCreate(Bundle state){
        super.onCreate(state);int parent=getIntent().getIntExtra("parentPid",-1);int round=getIntent().getIntExtra("round",1);String process=Application.getProcessName();
        boolean isolated=parent>0&&parent!=Process.myPid()&&!ParentActivity.visited&&(getPackageName()+":tool").equals(process)&&"cross-process-intent".equals(getIntent().getStringExtra("proof"));
        Bundle shared=getContentResolver().call(android.net.Uri.parse("content://org.example.saildroid.remoteactivity.shared"),"roundtrip",null,null);
        boolean provider=shared!=null&&shared.getInt("pid")==parent&&shared.getBoolean("parentVisited")&&shared.getInt("calls")==round;
        System.err.println("REMOTE_ACTIVITY=provider_roundtrip|owner_pid="+(shared==null?-1:shared.getInt("pid"))+"|valid="+provider);
        Bundle stored=getContentResolver().call(android.net.Uri.parse("content://org.example.saildroid.remoteactivity.store"),"roundtrip",null,null);
        boolean store=stored!=null&&stored.getInt("pid")!=parent&&stored.getInt("pid")!=Process.myPid()&&!stored.getBoolean("parentVisited")&&stored.getInt("calls")==round;
        System.err.println("REMOTE_ACTIVITY=provider_started|owner_pid="+(stored==null?-1:stored.getInt("pid"))+"|valid="+store);
        LinearLayout page=new LinearLayout(this);page.setOrientation(1);page.setPadding(32,120,32,32);page.setBackgroundColor(0xff065f46);
        TextView text=new TextView(this);text.setTextSize(28);text.setTextColor(0xffffffff);text.setText("Declared remote Activity\n"+process+"\nIndependent process: "+isolated);page.addView(text,new LinearLayout.LayoutParams(-1,260));
        Button back=new Button(this);back.setText("Return result");page.addView(back,new LinearLayout.LayoutParams(-1,240));back.setOnClickListener(new View.OnClickListener(){public void onClick(View view){System.err.println("REMOTE_ACTIVITY=child_return_tapped");finish();}});setContentView(page);
        setResult(RESULT_OK,new Intent().putExtra("proof","remote-result").putExtra("isolated",isolated).putExtra("provider",provider).putExtra("store",store).putExtra("childPid",Process.myPid()).putExtra("process",process));
        System.err.println("REMOTE_ACTIVITY=child_created|pid="+Process.myPid()+"|isolated="+isolated+"|process="+process);
    }
    @Override public void onResume(){super.onResume();System.err.println("REMOTE_ACTIVITY=child_resumed");}
    @Override public void onStop(){super.onStop();System.err.println("REMOTE_ACTIVITY=child_stopped");}
    @Override public void onDestroy(){super.onDestroy();System.err.println("REMOTE_ACTIVITY=child_destroyed");}
}
