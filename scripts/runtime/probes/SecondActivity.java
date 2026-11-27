package org.example.saildroid.inputprobe;

/** Exercises a real queued launch followed immediately by finishing its caller. */
public final class SecondActivity extends android.app.Activity {
    private boolean postCreated,resumed;
    @Override protected void onCreate(android.os.Bundle state){
        super.onCreate(state);android.widget.TextView text=new android.widget.TextView(this);text.setText("Second Activity lifecycle");setContentView(text);
        new android.os.Handler().postDelayed(new Runnable(){public void run(){
            if(!KeyboardActivity.destroyed||!postCreated||!resumed)throw new AssertionError("Launch/finish lifecycle incomplete");
            System.err.println("API29_ACTIVITY_STACK=PASS|first_destroyed=true|second_resumed=true|pid="+android.os.Process.myPid());finish();
        }},1000);
    }
    @Override protected void onPostCreate(android.os.Bundle state){super.onPostCreate(state);postCreated=true;}
    @Override protected void onResume(){if(!postCreated)throw new AssertionError("Second Activity postCreate missing");super.onResume();resumed=true;}
}
