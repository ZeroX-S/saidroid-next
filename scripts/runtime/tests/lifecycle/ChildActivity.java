package org.example.saildroid.lifecycle;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.widget.TextView;

public final class ChildActivity extends Activity {
    @Override public void onCreate(Bundle state){super.onCreate(state);TextView text=new TextView(this);text.setText("Android lifecycle regression\nChild Activity");text.setTextSize(28);setContentView(text);}
    @Override public void onResume(){super.onResume();new Handler().postDelayed(new Runnable(){public void run(){setResult(RESULT_OK,new android.content.Intent().putExtra("payload","real-child-result"));finish();}},900);}
}
