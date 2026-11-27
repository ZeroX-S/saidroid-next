package org.example.saildroid.lifecycle;
import android.app.*;import android.os.*;import android.content.*;import android.content.pm.*;import android.media.*;
public final class LifecycleService extends Service {
 private int checks;private void check(boolean v,String reason){if(!v)throw new AssertionError(reason);checks++;}
 @Override public IBinder onBind(Intent i){return null;}
 @Override public void onCreate(){super.onCreate();System.err.println("LIFECYCLE_SERVICE=headless|pid="+android.os.Process.myPid());final HandlerThread thread=new HandlerThread("Lifecycle-checks");thread.start();final Handler handler=new Handler(thread.getLooper());handler.post(new Runnable(){public void run(){try{
  check(Application.getProcessName().equals(getPackageName()+":worker"),"separate worker identity");
  ServiceInfo info=getPackageManager().getServiceInfo(new ComponentName(LifecycleService.this,DefaultService.class),0);check(getPackageName().equals(info.processName),"default service metadata");
  boolean found=false;for(ServiceInfo s:getPackageManager().getPackageInfo(getPackageName(),PackageManager.GET_SERVICES).services)if(s.name.equals(DefaultService.class.getName()))found=getPackageName().equals(s.processName);check(found,"package inventory default process");
  AudioManager audio=(AudioManager)getSystemService(AUDIO_SERVICE);AudioManager.OnAudioFocusChangeListener listener=new AudioManager.OnAudioFocusChangeListener(){public void onAudioFocusChange(int value){throw new AssertionError("no focus acquisition");}};
  for(int n=0;n<33;n++)check(audio.abandonAudioFocus(listener)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED,"legacy focus abandon");
  AudioFocusRequest request=new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN).setOnAudioFocusChangeListener(listener,handler).build();check(audio.abandonAudioFocusRequest(request)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED,"modern focus abandon");
  Intent target=new Intent(LifecycleService.this,DefaultService.class);target.putExtra("reply",new ResultReceiver(handler){@Override protected void onReceiveResult(int result,Bundle data){try{check(result==1,"default service callback");check(data.getInt("pid")!=android.os.Process.myPid(),"default service ran in owner process");check(getPackageName().equals(data.getString("process")),"default service process identity");System.err.println("LIFECYCLE_FIXTURE=PASS|checks="+checks+"|default_pid="+data.getInt("pid")+"|worker_pid="+android.os.Process.myPid());}catch(Throwable error){System.err.println("LIFECYCLE_FIXTURE=FAIL|"+error);error.printStackTrace();}finally{thread.quitSafely();}}});startService(target);
 }catch(Throwable error){System.err.println("LIFECYCLE_FIXTURE=FAIL|"+error);error.printStackTrace();thread.quitSafely();}}});}
}
