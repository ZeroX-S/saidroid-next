package org.example.saildroid.inputprobe;

import android.app.Service;
import android.content.Intent;
import android.os.*;

/** Real started/bound Service used by two separately installed regression APKs. */
public final class CounterService extends Service {
    private final Handler handler=new Handler(Looper.getMainLooper());
    private int counter;
    public final class CounterBinder extends Binder {public int value(){return counter;}@Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags)throws RemoteException{if(code==100){data.enforceInterface("org.example.saildroid.Counter");reply.writeNoException();reply.writeInt(counter);reply.writeInt(android.os.Process.myPid());return true;}return super.onTransact(code,data,reply,flags);}}
    private final CounterBinder binder=new CounterBinder();
    private final Runnable tick=new Runnable(){public void run(){
        counter++;
        getSharedPreferences("lifecycle",0).edit().putInt("counter",counter).putBoolean("running",true).apply();
        sendBroadcast(new Intent("org.example.saildroid.probe.TICK").setPackage(getPackageName()).putExtra("counter",counter).putExtra("sender_pid",android.os.Process.myPid()));
        if(counter%4==0)System.err.println("API29_SERVICE=tick|package="+getPackageName()+"|counter="+counter);
        handler.postDelayed(this,250);
    }};
    @Override public void onCreate(){super.onCreate();java.util.List<android.app.ActivityManager.RunningTaskInfo> tasks=((android.app.ActivityManager)getSystemService(ACTIVITY_SERVICE)).getRunningTasks(2);if(tasks.size()!=1||!getPackageName().equals(tasks.get(0).topActivity.getPackageName())||tasks.get(0).numActivities!=1)throw new AssertionError("Actual Activity task unavailable to Service");System.err.println("API29_TASKS=service_query|pid="+android.os.Process.myPid()+"|top="+tasks.get(0).topActivity.flattenToShortString());counter=getSharedPreferences("lifecycle",0).getInt("counter",0);handler.post(tick);System.err.println("API29_SERVICE=create|package="+getPackageName());}
    @Override public int onStartCommand(Intent intent,int flags,int startId){System.err.println("API29_SERVICE=start|package="+getPackageName()+"|id="+startId);return START_NOT_STICKY;}
    @Override public IBinder onBind(Intent intent){System.err.println("API29_SERVICE=bind|package="+getPackageName());return binder;}
    @Override public boolean onUnbind(Intent intent){System.err.println("API29_SERVICE=unbind|package="+getPackageName());return true;}
    @Override public void onRebind(Intent intent){System.err.println("API29_SERVICE=rebind|package="+getPackageName());}
    @Override public void onDestroy(){handler.removeCallbacks(tick);getSharedPreferences("lifecycle",0).edit().putBoolean("running",false).commit();System.err.println("API29_SERVICE=destroy|package="+getPackageName()+"|counter="+counter);super.onDestroy();}
}
