package org.example.saildroid.pending;

import android.app.*;
import android.content.*;
import android.os.*;
import android.widget.TextView;
import java.util.concurrent.*;

/** Normal signed APK: no private runtime or hidden Android API calls. */
public final class PendingActivity extends Activity {
    private final LinkedBlockingQueue<Intent> received=new LinkedBlockingQueue<Intent>();
    private final BroadcastReceiver receiver=new BroadcastReceiver(){
        @Override public void onReceive(Context context,Intent intent){received.add(new Intent(intent));}
    };
    private int checks;
    private void require(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private Intent intent(String action,int value){return new Intent(getPackageName()+"."+action).setPackage(getPackageName()).putExtra("value",value);}
    private Intent take()throws Exception{Intent value=received.poll(3,TimeUnit.SECONDS);require(value!=null,"receiver did not execute");return value;}
    private void canceled(PendingIntent value)throws Exception{
        boolean rejected=false;try{value.send();}catch(PendingIntent.CanceledException expected){rejected=true;}
        require(rejected,"canceled token dispatched");
    }
    @Override public void onCreate(Bundle state){
        super.onCreate(state);TextView view=new TextView(this);view.setText("Private PendingIntent regression");setContentView(view);
        IntentFilter filter=new IntentFilter();for(String action:new String[]{"same","cancel","immutable","mutable","once","parcel","handler"})filter.addAction(getPackageName()+"."+action);registerReceiver(receiver,filter);
        new Thread(new Runnable(){public void run(){try{test();}catch(Throwable failure){System.err.println("PENDING_FIXTURE=FAIL|"+failure);failure.printStackTrace();}}},"Pending-fixture").start();
    }
    private void test()throws Exception{
        System.err.println("PENDING_FIXTURE=target|sdk="+getApplicationInfo().targetSdkVersion);
        PendingIntent missing=PendingIntent.getBroadcast(this,100,intent("same",0),PendingIntent.FLAG_NO_CREATE);
        require(missing==null,"NO_CREATE allocated missing token");
        PendingIntent first=PendingIntent.getBroadcast(this,100,intent("same",1),0);
        require(getPackageName().equals(first.getCreatorPackage()),"creator package differs");
        require(first.getCreatorUid()==android.os.Process.myUid(),"creator uid differs");
        PendingIntent same=PendingIntent.getBroadcast(this,100,intent("same",2),0);
        require(first.equals(same),"filter identity included extras");first.send();require(take().getIntExtra("value",-1)==1,"extras replaced without UPDATE");
        PendingIntent updated=PendingIntent.getBroadcast(this,100,intent("same",3),PendingIntent.FLAG_UPDATE_CURRENT);
        require(first.equals(updated),"UPDATE changed token");first.send();require(take().getIntExtra("value",-1)==3,"UPDATE did not replace extras");
        require(first.equals(PendingIntent.getBroadcast(this,100,intent("same",9),PendingIntent.FLAG_NO_CREATE)),"NO_CREATE did not find token");
        PendingIntent different=PendingIntent.getBroadcast(this,101,intent("same",4),0);require(!first.equals(different),"request codes aliased");different.cancel();
        first.cancel();canceled(first);require(PendingIntent.getBroadcast(this,100,intent("same",0),PendingIntent.FLAG_NO_CREATE)==null,"canceled token remained active");
        PendingIntent old=PendingIntent.getBroadcast(this,102,intent("cancel",5),0);
        PendingIntent replacement=PendingIntent.getBroadcast(this,102,intent("cancel",6),PendingIntent.FLAG_CANCEL_CURRENT);
        require(!old.equals(replacement),"CANCEL_CURRENT reused token");canceled(old);replacement.send();require(take().getIntExtra("value",-1)==6,"replacement extras differ");replacement.cancel();
        PendingIntent immutable=PendingIntent.getBroadcast(this,103,intent("immutable",7),PendingIntent.FLAG_IMMUTABLE);
        immutable.send(this,0,new Intent().putExtra("value",99));require(take().getIntExtra("value",-1)==7,"immutable accepted fill-in");
        PendingIntent immutableUpdate=PendingIntent.getBroadcast(this,103,intent("immutable",8),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        require(immutable.equals(immutableUpdate),"immutable UPDATE changed token");immutable.send();require(take().getIntExtra("value",-1)==8,"creator cannot update immutable");immutable.cancel();
        PendingIntent mutable=PendingIntent.getBroadcast(this,104,intent("mutable",9),0);
        mutable.send(this,0,new Intent().putExtra("additional","filled"));Intent filled=take();require(filled.getIntExtra("value",-1)==9&&"filled".equals(filled.getStringExtra("additional")),"mutable extras not filled");mutable.cancel();
        PendingIntent once=PendingIntent.getBroadcast(this,105,intent("once",10),PendingIntent.FLAG_ONE_SHOT);
        once.send();require(take().getIntExtra("value",-1)==10,"one-shot was not delivered");canceled(once);
        PendingIntent parcel=PendingIntent.getBroadcast(this,106,intent("parcel",11),0);Parcel data=Parcel.obtain();PendingIntent copy;
        try{parcel.writeToParcel(data,0);data.setDataPosition(0);copy=PendingIntent.CREATOR.createFromParcel(data);}finally{data.recycle();}
        require(parcel.equals(copy),"parcel token identity differs");copy.send();require(take().getIntExtra("value",-1)==11,"parcel token did not dispatch");parcel.cancel();canceled(copy);
        HandlerThread thread=new HandlerThread("Pending-real-handler");thread.start();final CountDownLatch done=new CountDownLatch(1);final Throwable[] error=new Throwable[1];
        new Handler(thread.getLooper()).post(new Runnable(){public void run(){try{PendingIntent token=PendingIntent.getBroadcast(PendingActivity.this,107,intent("handler",12),0);token.send();token.cancel();}catch(Throwable failure){error[0]=failure;}finally{done.countDown();}}});
        require(done.await(4,TimeUnit.SECONDS)&&error[0]==null,"HandlerThread create/send failed");require(take().getIntExtra("value",-1)==12,"HandlerThread receiver value differs");thread.quitSafely();thread.join(2000);
        boolean denied=false;try{PendingIntent.getBroadcast(this,108,new Intent("foreign").setPackage("other.application"),0);}catch(SecurityException expected){denied=true;}require(denied,"foreign package accepted");
        denied=false;try{PendingIntent.getBroadcast(this,109,new Intent().setComponent(new ComponentName("other.application","other.application.Receiver")),0);}catch(SecurityException expected){denied=true;}require(denied,"foreign component accepted");
        NotificationManager notifications=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);require(!notifications.areNotificationsEnabled(),"host notification policy changed");
        notifications.createNotificationChannel(new NotificationChannel("pending-test","Private regression",NotificationManager.IMPORTANCE_DEFAULT));
        PendingIntent action=PendingIntent.getBroadcast(this,110,intent("same",13),0);
        Notification notification=new Notification.Builder(this,"pending-test").setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("Private regression").setContentIntent(action).build();
        notifications.notify(301,notification);require(notifications.getActiveNotifications().length==0,"disabled notification was posted");notifications.cancel(301);notifications.deleteNotificationChannel("pending-test");action.cancel();
        require(received.isEmpty(),"unexpected extra broadcast delivery");
        System.err.println("PENDING_FIXTURE=PASS|checks="+checks+"|delivery=real-BroadcastReceiver|parcel=real-binder|notification=disabled-policy");
    }
    @Override public void onDestroy(){unregisterReceiver(receiver);super.onDestroy();}
}
