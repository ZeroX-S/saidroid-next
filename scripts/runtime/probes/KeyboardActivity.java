package org.example.saildroid.inputprobe;

import android.app.Activity;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import android.content.*;
import android.os.IBinder;

/** Temporary device regression app; never included in the product launcher. */
public final class KeyboardActivity extends Activity {
    public static boolean destroyed;
    private boolean binding;
    private boolean connected;
    private IBinder serviceBinder;
    private final ServiceConnection connection=new ServiceConnection(){public void onServiceConnected(ComponentName name,IBinder binder){serviceBinder=binder;connected=true;int[] values=counter();System.err.println("API29_SERVICE=connected|package="+getPackageName()+"|counter="+values[0]+"|service_pid="+values[1]+"|client_pid="+android.os.Process.myPid());}public void onServiceDisconnected(ComponentName name){serviceBinder=null;connected=false;System.err.println("API29_SERVICE=disconnected|package="+getPackageName());}};
    private int[] counter(){if(serviceBinder==null)return new int[]{-1,-1};if(serviceBinder instanceof CounterService.CounterBinder)return new int[]{((CounterService.CounterBinder)serviceBinder).value(),android.os.Process.myPid()};android.os.Parcel data=android.os.Parcel.obtain(),reply=android.os.Parcel.obtain();try{data.writeInterfaceToken("org.example.saildroid.Counter");if(!serviceBinder.transact(100,data,reply,0))throw new AssertionError("Counter transaction rejected");reply.readException();return new int[]{reply.readInt(),reply.readInt()};}catch(android.os.RemoteException failure){throw new IllegalStateException(failure);}finally{data.recycle();reply.recycle();}}
    private final android.os.Handler refresh=new android.os.Handler();
    private Runnable pollCounter;
    private BroadcastReceiver receiver;
    private boolean receivedTick;
    private boolean postCreated;
    @Override protected void onStart(){super.onStart();System.err.println("API29_LIFECYCLE=start|package="+getPackageName());}
    @Override protected void onPostCreate(Bundle state){super.onPostCreate(state);postCreated=true;System.err.println("API29_LIFECYCLE=post_create|package="+getPackageName());}
    @Override protected void onResume(){if(!postCreated)throw new AssertionError("onResume preceded onPostCreate");super.onResume();System.err.println("API29_LIFECYCLE=resume|package="+getPackageName());}
    @Override protected void onPause(){System.err.println("API29_LIFECYCLE=pause|package="+getPackageName());super.onPause();}
    private void checkManagerMemory(){android.os.Debug.MemoryInfo[] info=((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getProcessMemoryInfo(new int[]{android.os.Process.myPid()});if(info.length!=1||info[0].getTotalPss()<=0)throw new AssertionError("Manager process memory unavailable");System.err.println("API29_MEMORY=manager_query|pss_kb="+info[0].getTotalPss());}
    @Override protected void onStop(){
        checkManagerMemory();
        if(binding&&connected)try{
            android.content.pm.ServiceInfo service=getPackageManager().getServiceInfo(new ComponentName(this,CounterService.class),0);
            String process=service.processName==null?getApplicationInfo().processName:service.processName;
            android.app.ActivityManager.RunningAppProcessInfo state=new android.app.ActivityManager.RunningAppProcessInfo();android.app.ActivityManager.getMyMemoryState(state);
            int expected=process.equals(getApplicationInfo().processName)?android.app.ActivityManager.RunningAppProcessInfo.IMPORTANCE_SERVICE:android.app.ActivityManager.RunningAppProcessInfo.IMPORTANCE_BACKGROUND;
            if(state.importance!=expected)throw new AssertionError("Background process importance differs: "+state.importance+" expected "+expected);
            System.err.println("API29_PROCESS_STATE=PASS|background_importance="+state.importance);
        }catch(android.content.pm.PackageManager.NameNotFoundException failure){throw new IllegalStateException(failure);}
        System.err.println("API29_LIFECYCLE=stop|package="+getPackageName());super.onStop();
    }
    @Override protected void onDestroy(){destroyed=true;if(pollCounter!=null)refresh.removeCallbacks(pollCounter);if(binding){unbindService(connection);binding=false;}if(receiver!=null)unregisterReceiver(receiver);System.err.println("API29_LIFECYCLE=destroy|package="+getPackageName());super.onDestroy();}
    @Override public void onWindowFocusChanged(boolean focused){super.onWindowFocusChanged(focused);System.err.println("API29_INPUT=window_focus|active="+focused);}
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
        overridePendingTransition(0,0);
        if(getRequestedOrientation()!=android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT||isInMultiWindowMode()||isInPictureInPictureMode()||getResources().getConfiguration().orientation!=android.content.res.Configuration.ORIENTATION_PORTRAIT)throw new AssertionError("Host Activity window state differs");
        System.err.println("API29_WINDOW_STATE=PASS|orientation=portrait|multiwindow=false|pip=false");
        android.util.Log.i("SailDroidProbe","lifecycle_create");
        if(getSystemService(KEYGUARD_SERVICE)==null)throw new AssertionError("KeyguardManager construction failed");
        android.os.PowerManager power=(android.os.PowerManager)getSystemService(POWER_SERVICE);if(power==null||power.isWakeLockLevelSupported(android.os.PowerManager.PARTIAL_WAKE_LOCK)||power.isDeviceIdleMode())throw new AssertionError("PowerManager host capability state differs");
        android.app.NotificationManager notifications=(android.app.NotificationManager)getSystemService(NOTIFICATION_SERVICE);String channel="saildroid-regression";
        notifications.createNotificationChannel(new android.app.NotificationChannel(channel,"Regression",android.app.NotificationManager.IMPORTANCE_LOW));
        if(notifications.getNotificationChannel(channel)==null||notifications.areNotificationsEnabled())throw new AssertionError("Notification policy/metadata differs");
        notifications.deleteNotificationChannel(channel);if(notifications.getNotificationChannel(channel)!=null)throw new AssertionError("Notification channel not deleted");
        System.err.println("API29_HOST_POLICY=PASS|keyguard_constructed=true|channel_create_read_delete=true|notification_delivery=disabled");
        checkManagerMemory();
        android.os.Debug.MemoryInfo memory=new android.os.Debug.MemoryInfo();android.os.Debug.getMemoryInfo(memory);long pss=android.os.Debug.getPss();if(pss<=0||memory.getTotalPss()<=0)throw new AssertionError("Actual process PSS unavailable");System.err.println("API29_MEMORY=PASS|pss_kb="+pss+"|memory_info_pss_kb="+memory.getTotalPss());
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 80, 32, 32);
        root.setBackgroundColor(0xfff4f7fa);
        TextView title = new TextView(this);
        title.setText("SailDroid input regression");
        title.setTextSize(24);
        root.addView(title);
        final EditText editor = new EditText(this);
        editor.setSingleLine(true);
        editor.setHint("Keyboard test");
        editor.setTextSize(24);
        root.addView(editor, new LinearLayout.LayoutParams(-1, 180));
        final TextView result = new TextView(this);
        result.setTextSize(20);
        root.addView(result);
        editor.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s,int start,int count,int after) {}
            public void onTextChanged(CharSequence s,int start,int before,int count) {
                result.setText("Characters: " + s.length());
                System.err.println("API29_INPUT=text_changed|length=" + s.length());
            }
            public void afterTextChanged(Editable value) {}
        });
        Button show = new Button(this);
        show.setText("Show keyboard");
        show.setOnClickListener(new View.OnClickListener() {
            public void onClick(View view) {
                boolean focused=editor.requestFocus();
                InputMethodManager input=(InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);
                boolean requested=input.showSoftInput(editor, InputMethodManager.SHOW_IMPLICIT);
                System.err.println("API29_INPUT=show_requested|accepted=" + requested+"|requested_focus="+focused+"|focus="+editor.hasFocus()+"|window_focus="+editor.hasWindowFocus()+"|active="+input.isActive(editor));
            }
        });
        root.addView(show, new LinearLayout.LayoutParams(-1, 160));
        TextView identity=new TextView(this);identity.setText(getPackageName());identity.setTextSize(14);root.addView(identity);
        final TextView progress=new TextView(this);progress.setText("Background counter: stopped");progress.setTextSize(16);root.addView(progress);
        pollCounter=new Runnable(){public void run(){if(connected){int[] values=counter();progress.setText("Background counter: "+values[0]+" · PID "+values[1]);}refresh.postDelayed(this,1000);}};refresh.postDelayed(pollCounter,1000);
        receiver=new BroadcastReceiver(){public void onReceive(Context context,Intent intent){progress.setText("Background counter: "+intent.getIntExtra("counter",-1));if(!receivedTick){receivedTick=true;System.err.println("API29_BROADCAST=received|package="+getPackageName()+"|sender_pid="+intent.getIntExtra("sender_pid",-1)+"|receiver_pid="+android.os.Process.myPid());}}};
        registerReceiver(receiver,new IntentFilter("org.example.saildroid.probe.TICK"));
        Button start=new Button(this);start.setText("Start background service");start.setOnClickListener(new View.OnClickListener(){public void onClick(View view){Intent service=new Intent(KeyboardActivity.this,CounterService.class);ComponentName result=startService(service);if(result==null)throw new AssertionError("Service did not start");if(!binding)binding=bindService(service,connection,Context.BIND_AUTO_CREATE);System.err.println("API29_SERVICE=requested|package="+getPackageName()+"|binding="+binding);}});root.addView(start,new LinearLayout.LayoutParams(-1,140));
        Button stop=new Button(this);stop.setText("Stop background service");stop.setOnClickListener(new View.OnClickListener(){public void onClick(View view){if(binding){unbindService(connection);binding=false;}boolean stopped=stopService(new Intent(KeyboardActivity.this,CounterService.class));System.err.println("API29_SERVICE=stop_requested|package="+getPackageName()+"|result="+stopped);}});root.addView(stop,new LinearLayout.LayoutParams(-1,140));
        Button close=new Button(this);close.setText("Close app");close.setOnClickListener(new View.OnClickListener(){public void onClick(View view){System.err.println("API29_LIFECYCLE=finish_requested|package="+getPackageName());finish();}});root.addView(close,new LinearLayout.LayoutParams(-1,140));
        setContentView(root);
        int locks=0;for(int fd=3;fd<100;fd++)try{if(java.nio.file.Files.readSymbolicLink(java.nio.file.Paths.get("/proc/self/fd/"+fd)).toString().endsWith(".lock"))locks++;}catch(Exception ignored){}
        System.err.println("API29_LIFECYCLE=ready|package="+getPackageName()+"|pid="+android.os.Process.myPid()+"|inherited_locks="+locks);
        System.err.println("API29_INPUT=ready|sdk=" + android.os.Build.VERSION.SDK_INT);
        if(Boolean.getBoolean("saidroid.probe.autorun"))new android.os.Handler().postDelayed(new Runnable(){public void run(){
            Intent intent=new Intent(KeyboardActivity.this,CounterService.class);
            if(startService(intent)==null)throw new AssertionError("Start rejected");binding=bindService(intent,connection,Context.BIND_AUTO_CREATE);if(!binding)throw new AssertionError("Bind rejected");
            new android.os.Handler().postDelayed(new Runnable(){public void run(){
                if(!connected||counter()[0]<3)throw new AssertionError("Service did not bind/tick");
                unbindService(connection);binding=false;if(!stopService(new Intent(KeyboardActivity.this,CounterService.class)))throw new AssertionError("Stop rejected");
                new android.os.Handler().postDelayed(new Runnable(){public void run(){
                    if(getSharedPreferences("lifecycle",0).getBoolean("running",true)||!((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getRunningServices(10).isEmpty())throw new AssertionError("Service survived stop");
                    System.err.println("API29_SERVICE_TEST=PASS|package="+getPackageName()+"|created=true|bound=true|ticks=true|destroyed=true");startActivity(new Intent(KeyboardActivity.this,SecondActivity.class));finish();
                }},500);
            }},1500);
        }},500);
    }
}
