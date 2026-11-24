package org.example.saildroid.lifecycle;
import android.app.*;import android.os.*;import android.content.*;
public final class DefaultService extends Service {
 @Override public IBinder onBind(Intent i){return null;}
 @Override public int onStartCommand(Intent i,int flags,int id){Bundle b=new Bundle();b.putInt("pid",android.os.Process.myPid());b.putString("process",Application.getProcessName());((ResultReceiver)i.getParcelableExtra("reply")).send(1,b);System.err.println("LIFECYCLE_DEFAULT=delivered|process="+Application.getProcessName());stopSelf(id);return START_NOT_STICKY;}
}
