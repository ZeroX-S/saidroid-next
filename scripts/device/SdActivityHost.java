import android.app.*;
import android.app.servertransaction.*;
import android.content.*;
import android.content.pm.*;
import android.content.res.*;
import android.os.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Real API 29 ActivityThread lifecycle, hosted asynchronously behind Wayland. */
public final class SdActivityHost {
    // Process-local endpoint for PackageManager.buildRequestPermissionsIntent.
    static final String PERMISSION_CONTROLLER_PACKAGE="org.saildroid.permissioncontroller";
    private static final ArrayList<Entry> stack=new ArrayList<Entry>();
    private static boolean hostVisible=true;
    private static int ident;
    private static boolean closeWhenReady;
    private static final AtomicInteger pendingStarts=new AtomicInteger();
    private static android.net.Uri pendingInstallerUri;
    private static final ArrayList<Remote> remoteActivities=new ArrayList<Remote>();
    private static final class Remote {
        Entry caller;ActivityInfo info;String who;int requestCode;boolean awaiting=true,ready;
    }
    private static boolean remoteLaunchPending(){for(Remote r:remoteActivities)if(r.awaiting)return true;return false;}
    private static volatile List<ActivityManager.RunningTaskInfo> taskSnapshot=Collections.emptyList();
    private static void refreshTask(){
        if(stack.isEmpty()){taskSnapshot=Collections.emptyList();return;}
        Entry base=stack.get(0),top=stack.get(stack.size()-1);
        ActivityManager.RunningTaskInfo task=new ActivityManager.RunningTaskInfo();
        task.id=1;
        task.baseActivity=new ComponentName(base.info.packageName,base.info.name);
        task.topActivity=new ComponentName(top.info.packageName,top.info.name);task.numActivities=stack.size();
        for(Remote remote:remoteActivities)if(remote.ready){task.topActivity=new ComponentName(remote.info.packageName,remote.info.name);task.numActivities++;}
        task.lastActiveTime=android.os.SystemClock.elapsedRealtime();task.configuration.setTo(displayConfiguration());
        taskSnapshot=Collections.singletonList(task);
    }
    public static List<ActivityManager.RunningTaskInfo> runningTasks(int maximum){
        if(maximum<=0)return new ArrayList<ActivityManager.RunningTaskInfo>();
        ArrayList<ActivityManager.RunningTaskInfo> result=new ArrayList<ActivityManager.RunningTaskInfo>();
        for(ActivityManager.RunningTaskInfo task:taskSnapshot){android.os.Parcel parcel=android.os.Parcel.obtain();try{task.writeToParcel(parcel,0);parcel.setDataPosition(0);result.add(ActivityManager.RunningTaskInfo.CREATOR.createFromParcel(parcel));}finally{parcel.recycle();}if(result.size()>=maximum)break;}
        return result;
    }
    public static void dumpState(){
        for(Entry e:stack){
            if(e.activity==null){System.err.println("SDDIAGNOSTICS=activity_pending|class="+e.info.name);continue;}
            System.err.println("SDDIAGNOSTICS=activity|class="+e.info.name+"|resumed="+e.resumed+"|stopped="+e.stopped+"|window_focus="+e.activity.hasWindowFocus()+"|finishing="+e.activity.isFinishing());
            for(Class<?> type=e.activity.getClass();type!=null&&type!=Activity.class;type=type.getSuperclass())for(Field field:type.getDeclaredFields())if(field.getType()==boolean.class&&!Modifier.isStatic(field.getModifiers()))try{field.setAccessible(true);System.err.println("SDDIAGNOSTICS=activity_flag|class="+type.getName()+"|field="+field.getName()+"|value="+field.getBoolean(e.activity));}catch(Exception unavailable){}
        }
    }
    private static final class Entry {
        Binder token;Object record;ActivityInfo info;Intent intent;Activity activity;boolean resumed,stopped;
        IBinder resultTo;String resultWho;int requestCode=-1;
        IBinder remoteResult;
    }
    private static void set(Object object,String name,Object value)throws Exception{Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);f.set(object,value);}
    private static Entry find(IBinder token){for(Entry e:stack)if(e.token==token)return e;throw new IllegalArgumentException("Unknown Activity token");}
    public static void requireActivity(IBinder token){find(token);}
    public static boolean isTop(IBinder token){return !stack.isEmpty()&&stack.get(stack.size()-1).token==token;}
    public static ComponentName component(IBinder token){Entry e=find(token);return new ComponentName(e.info.packageName,e.info.name);}
    public static int requestedOrientation(IBinder token){return find(token).info.screenOrientation;}
    public static void requestOrientation(IBinder token,int requested){
        Entry e=find(token);
        if(requested<ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED||requested>ActivityInfo.SCREEN_ORIENTATION_LOCKED)throw new IllegalArgumentException("Unknown orientation request");
        if(requested==ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE||requested==ActivityInfo.SCREEN_ORIENTATION_REVERSE_LANDSCAPE||requested==ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE||requested==ActivityInfo.SCREEN_ORIENTATION_USER_LANDSCAPE||requested==ActivityInfo.SCREEN_ORIENTATION_REVERSE_PORTRAIT)throw new UnsupportedOperationException("The current host output supports portrait orientation");
        e.info.screenOrientation=requested;
        System.err.println("SDACTIVITY=orientation_requested|value="+requested+"|configuration=portrait|activity="+e.info.name);
    }
    public static Configuration displayConfiguration(){
        Configuration c=new Configuration();c.setToDefaults();c.setLocale(Locale.getDefault());c.densityDpi=SdDisplayShim.DENSITY;
        float density=SdDisplayShim.DENSITY/160f;c.screenWidthDp=(int)(SdDisplayShim.WIDTH/density);c.screenHeightDp=(int)(SdDisplayShim.HEIGHT/density);c.smallestScreenWidthDp=Math.min(c.screenWidthDp,c.screenHeightDp);
        c.orientation=Configuration.ORIENTATION_PORTRAIT;c.screenLayout=Configuration.reduceScreenLayout(Configuration.resetScreenLayout(0),Math.max(c.screenWidthDp,c.screenHeightDp),c.smallestScreenWidthDp);
        return c;
    }
    public static void applyDisplayConfiguration(ActivityThread thread)throws Exception{
        Configuration c=displayConfiguration();
        Method changed=ActivityThread.class.getDeclaredMethod("handleConfigurationChanged",Configuration.class,CompatibilityInfo.class);changed.setAccessible(true);changed.invoke(thread,c,null);
        System.err.println("SDACTIVITY=display_configured|api=29|width_dp="+c.screenWidthDp);
    }
    private static void post(Runnable runnable){Message message=Message.obtain(new Handler(Looper.getMainLooper()),runnable);message.setAsynchronous(true);message.getTarget().sendMessage(message);}
    private static void pause(Entry e){if(!e.resumed)return;ActivityThread.currentActivityThread().handlePauseActivity(e.token,false,false,0,new PendingTransactionActions(),"SailDroid host background");e.resumed=false;}
    private static void stop(Entry e){if(e.stopped)return;ActivityThread.currentActivityThread().handleStopActivity(e.token,false,0,new PendingTransactionActions(),false,"SailDroid host background");e.stopped=true;}
    private static void resume(Entry e){if(e.resumed)return;ActivityThread.currentActivityThread().handleResumeActivity(e.token,true,false,"SailDroid host foreground");e.resumed=true;e.stopped=false;}
    public static void hostVisibility(boolean active){
        SdRuntimeDiagnostics.captureUncaught();
        if(hostVisible==active)return;hostVisible=active;
        if(stack.isEmpty())return;Entry e=stack.get(stack.size()-1);if(e.activity==null)return;
        if(active)resume(e);else{pause(e);if(!remoteLaunchPending())stop(e);}
        refreshTask();
        System.err.println("SDACTIVITY=host_visibility|foreground="+active+"|activity="+e.info.name);
    }
    private static void launch(Intent request)throws Exception{launch(request,null,null,-1,null,null);}
    private static void launch(Intent request,IBinder resultTo,String resultWho,int requestCode)throws Exception{
        String referrer=resultTo==null?SdApkPackage.NAME:find(resultTo).info.packageName;
        launch(request,resultTo,resultWho,requestCode,null,referrer);
    }
    private static void launch(Intent request,IBinder resultTo,String resultWho,int requestCode,IBinder remoteResult,String referrer)throws Exception{
        if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("Activity launch must use main Looper");
        if(!SdWindowHost.isStarted())SdRuntime.ensureUiHost();
        List<ResolveInfo> candidates=SdApkPackage.resolveActivities(request,request.getType(),0);
        if(candidates.isEmpty())throw new ActivityNotFoundException(request.toString());
        ActivityInfo info=candidates.get(0).activityInfo;
        if(info.processName!=null&&!info.processName.equals(SdApkPackage.processName())){
            if(!info.packageName.equals(SdApkPackage.NAME))throw new UnsupportedOperationException("Separate-process Activity: "+info.processName);
            if(remoteResult!=null)throw new SecurityException("Remote Activity reached the wrong process");
            startRemote(request,info,resultTo,resultWho,requestCode);return;
        }
        Entry previous=stack.isEmpty()?null:stack.get(stack.size()-1);
        // QQ can re-submit LoginActivity while its login page is settling.
        // Keep one Activity/window and deliver the new Intent instead of
        // creating a second identical surface.
        if(remoteResult==null&&requestCode<0&&previous!=null&&previous.activity!=null&&previous.info.packageName.equals(info.packageName)&&previous.info.name.equals(info.name)){
            ActivityThread.currentActivityThread().getInstrumentation().callActivityOnNewIntent(previous.activity,request);
            refreshTask();
            System.err.println("SDACTIVITY=reused|class="+info.name+"|reason=same-top-component");
            return;
        }
        final Entry e=new Entry();e.token=new Binder();e.info=info;e.intent=new Intent(request).setComponent(new ComponentName(info.packageName,info.name));
        e.remoteResult=remoteResult;
        if(requestCode>=0){find(resultTo);e.resultTo=resultTo;e.resultWho=resultWho;e.requestCode=requestCode;}
        info.applicationInfo=ActivityThread.currentApplication().getApplicationInfo();
        final ActivityThread thread=ActivityThread.currentActivityThread();
        // Android pauses the outgoing Activity before creating/resuming its
        // successor. Stop remains deferred until the new Activity is ready.
        // Reversing this order exposes two resumed Activities to applications.
        if(previous!=null&&previous.activity!=null)pause(previous);
        SdServices.registerActivity(e.token,info,e.intent,SdDisplayShim.DISPLAY_ID);stack.add(e);refreshTask();
        ClientTransaction transaction=ClientTransaction.obtain(thread.getApplicationThread(),e.token);
        // Activity.getReferrer() falls back to the launch caller's package when
        // the Intent has no explicit referrer. Result callbacks are optional,
        // so ordinary startActivity calls must retain their caller too.
        transaction.addCallback(LaunchActivityItem.obtain(e.intent,++ident,info,displayConfiguration(),new Configuration(),CompatibilityInfo.DEFAULT_COMPATIBILITY_INFO,referrer,null,hostVisible?ActivityManager.PROCESS_STATE_TOP:ActivityManager.PROCESS_STATE_IMPORTANT_BACKGROUND,null,null,null,null,true,null));
        transaction.setLifecycleStateRequest(ResumeActivityItem.obtain(true));
        transaction.schedule();
        final Entry old=previous;
        System.err.println("SDACTIVITY=transaction_scheduled|class="+info.name+"|stack="+stack.size()+"|referrer="+referrer);
        verifyLaunch(thread,e,old,0);
    }
    public static void activityRelaunched(IBinder token){
        Entry entry = find(token);
        verifyLaunch(ActivityThread.currentActivityThread(),entry,null,0);
        System.err.println("SDACTIVITY=relaunch_reported|class="+entry.info.name);
    }
    private static void verifyLaunch(final ActivityThread thread,final Entry e,final Entry old,final int attempt){
        post(new Runnable(){public void run(){try{
            if(!stack.contains(e))return;
            e.record=ActivityThread.class.getMethod("getActivityClient",IBinder.class).invoke(thread,e.token);
            // Android 9 getActivity() dereferences an absent client record.
            // Launch and relaunch transactions can still be queued here.
            e.activity=e.record==null?null:thread.getActivity(e.token);
            if((e.activity==null||e.record==null)&&attempt<80){
                System.err.println("SDACTIVITY=transaction_pending|class="+e.info.name+"|attempt="+attempt);
                new Handler(Looper.getMainLooper()).postDelayed(new Runnable(){public void run(){verifyLaunch(thread,e,old,attempt+1);}},25);
                return;
            }
            if(e.activity==null||e.record==null)throw new IllegalStateException("Activity transaction did not create the requested Activity|class="+e.info.name+"|attempts="+attempt);
            Method state=e.record.getClass().getMethod("getLifecycleState");state.setAccessible(true);int lifecycle=(Integer)state.invoke(e.record);
            e.resumed=lifecycle==ActivityLifecycleItem.ON_RESUME;e.stopped=lifecycle==ActivityLifecycleItem.ON_STOP;
            if(!hostVisible){pause(e);stop(e);}if(old!=null&&stack.contains(old)){pause(old);stop(old);}refreshTask();
            System.err.println("SDACTIVITY=launched|class="+e.info.name+"|resumed="+e.resumed+"|stack="+stack.size()+"|dispatch=client-transaction");
            System.err.println("SDRUNTIME=activity_ready|package="+e.info.packageName);
            if(e.remoteResult!=null)SdRemoteActivities.ready(e.remoteResult);
            SdRuntimeDiagnostics.captureUncaught();
            if(pendingInstallerUri!=null){android.net.Uri uri=pendingInstallerUri;pendingInstallerUri=null;openInstallerFile(uri);}
            if(closeWhenReady)closeTask();
        }catch(Exception failure){throw new IllegalStateException("Activity transaction completion failed",failure);}}});
    }

    private static void startRemote(Intent intent,ActivityInfo info,IBinder resultTo,String who,int requestCode){
        final Remote remote=new Remote();remote.info=info;remote.who=who;remote.requestCode=requestCode;
        remote.caller=resultTo!=null?find(resultTo):stack.isEmpty()?null:stack.get(stack.size()-1);
        if(remote.caller==null)throw new IllegalStateException("Remote Activity requires a live task owner");
        remoteActivities.add(remote);pause(remote.caller);
        SdRemoteActivities.start(new Intent(intent),info,new SdRemoteActivities.Lifecycle(){
            public void ready(){
                if(!remoteActivities.contains(remote)||remote.ready)return;
                remote.awaiting=false;remote.ready=true;
                if(stack.contains(remote.caller)){pause(remote.caller);stop(remote.caller);}
                refreshTask();System.err.println("SDACTIVITY=remote_ready|class="+remote.info.name+"|process="+remote.info.processName);
            }
            public void finished(int code,Intent value,boolean foreground){completeRemote(remote,code,value,foreground);}
            public void failed(String type){System.err.println("SDACTIVITY=remote_failed|class="+remote.info.name+"|type="+type);completeRemote(remote,Activity.RESULT_CANCELED,null,!remote.ready&&hostVisible);}
        });
        System.err.println("SDACTIVITY=remote_requested|class="+info.name+"|process="+info.processName);
    }
    private static void completeRemote(Remote remote,int code,Intent value,boolean foreground){
        if(!remoteActivities.remove(remote))return;
        Entry caller=remote.caller;
        if(stack.contains(caller)&&caller.activity!=null&&!caller.activity.isFinishing()&&remote.requestCode>=0){
            ArrayList<ResultInfo> results=new ArrayList<ResultInfo>();results.add(new ResultInfo(remote.who,remote.requestCode,code,value));
            ActivityThread.currentActivityThread().handleSendResult(caller.token,results,"SailDroid remote Activity finished");
            System.err.println("SDACTIVITY=remote_result_delivered|request_code="+remote.requestCode+"|result_code="+code);
        }
        refreshTask();
        if(foreground&&!stack.isEmpty()){
            hostVisible=true;resume(stack.get(stack.size()-1));org.saildroid.host.HostApi.activateSelf();
        }
    }
    public static void requestRemoteStart(final Intent intent,final IBinder callback){
        final Intent snapshot=new Intent(intent);
        post(new Runnable(){public void run(){try{
            SdRuntime.ensureUiHost();launch(snapshot,null,null,-1,callback,SdApkPackage.NAME);
        }catch(Exception failure){
            try{SdRemoteActivities.finish(callback,Activity.RESULT_CANCELED,null,false);}catch(RemoteException ignored){}
            throw new IllegalStateException("Remote Activity launch failed",failure);
        }}});
    }

    public static void launchMainActivity(String apk)throws Exception{
        if(!apk.equals(SdApkPackage.APK))throw new SecurityException("Application APK identity mismatch");
        Intent intent=new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setPackage(SdApkPackage.NAME).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);launch(intent);
    }
    public static void requestStart(final Intent intent){
        requestStart(intent,null,null,-1);
    }
    public static void requestStart(final Intent intent,final IBinder resultTo,final String resultWho,final int requestCode){
        if(SdPermissionController.accepts(intent)||SdPermissionController.acceptsSettings(intent)){
            requestPermissions(intent,resultTo,resultWho,requestCode);return;
        }
        if(SdApkPackage.resolveActivities(intent,intent.getType(),0).isEmpty())throw new ActivityNotFoundException(intent.toString());
        final Entry caller=resultTo!=null||requestCode>=0?find(resultTo):null;
        final String referrer=caller==null?SdApkPackage.NAME:caller.info.packageName;
        final Intent snapshot=new Intent(intent);
        pendingStarts.incrementAndGet();
        post(new Runnable(){public void run(){try{
            // The caller can finish between accepting this request and dispatch.
            // Retain its referrer, but detach results from a destroyed Activity.
            boolean callerAlive=caller!=null&&stack.contains(caller);
            if(caller!=null&&!callerAlive)System.err.println("SDACTIVITY=launch_caller_finished|class="+caller.info.name+"|request_code="+requestCode);
            launch(snapshot,callerAlive?caller.token:null,resultWho,callerAlive?requestCode:-1,null,referrer);
        }catch(Exception e){throw new IllegalStateException("Activity launch failed",e);}
        finally{pendingStarts.decrementAndGet();}}});
    }
    private static void requestPermissions(Intent intent,final IBinder token,final String who,final int requestCode){
        final boolean settings=SdPermissionController.acceptsSettings(intent);
        final Entry caller=token!=null?find(token):settings&&!stack.isEmpty()?stack.get(stack.size()-1):null;
        if(caller==null)throw new SecurityException("Permission dialog requires a hosted Activity");
        if(!settings&&(requestCode<0||who==null||!who.startsWith("@android:requestPermissions:")))throw new SecurityException("Permission request requires an Activity result owner");
        final Intent snapshot=new Intent(intent);
        post(new Runnable(){public void run(){
            if(!stack.contains(caller))return;
            ActivityThread thread=ActivityThread.currentActivityThread();
            if(thread.getActivityClient(caller.token)==null)return;
            Activity target=thread.getActivity(caller.token);
            if(target==null||target.isFinishing())return;
            if(settings){pause(caller);SdPermissionController.showSettings(target,caller.token,who,requestCode);}
            else SdPermissionController.request(target,caller.token,snapshot,who,requestCode);
        }});
    }
    public static void permissionSettingsClosed(IBinder token,String who,int requestCode){
        Entry caller=null;for(Entry entry:stack)if(entry.token==token)caller=entry;
        if(caller==null||caller.activity==null||caller.activity.isFinishing())return;
        if(requestCode>=0){
            ArrayList<ResultInfo> results=new ArrayList<ResultInfo>();results.add(new ResultInfo(who,requestCode,Activity.RESULT_OK,null));
            ActivityThread.currentActivityThread().handleSendResult(token,results,"SailDroid application permissions closed");
        }
        if(hostVisible&&isTop(token))resume(caller);
    }
    public static void openInstallerFile(android.net.Uri uri){
        if(!"org.saildroid.manager".equals(SdApkPackage.NAME))throw new IllegalStateException("Installer Activity unavailable");
        if(stack.isEmpty()||stack.get(stack.size()-1).activity==null){pendingInstallerUri=uri;return;}
        Entry e=stack.get(stack.size()-1);
        Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive");
        ActivityThread.currentActivityThread().getInstrumentation().callActivityOnNewIntent(e.activity,intent);
        System.err.println("SDACTIVITY=new_intent|class="+e.info.name);
    }
    public static void requestFinishSubActivities(final IBinder token,final String who,final int requestCode){
        final Entry caller=find(token);
        for(Remote remote:remoteActivities)if(remote.caller==caller&&remote.requestCode==requestCode&&Objects.equals(remote.who,who))throw new UnsupportedOperationException("Closing a pending remote sub-Activity requires its process endpoint");
        post(new Runnable(){public void run(){
            if(!stack.contains(caller))return;
            ArrayList<Entry> matched=new ArrayList<Entry>();
            for(int i=stack.size()-1;i>=0;i--){Entry child=stack.get(i);if(child.resultTo==token&&child.requestCode==requestCode&&Objects.equals(child.resultWho,who))matched.add(child);}
            for(Entry child:matched)requestFinish(child.token,Activity.RESULT_CANCELED,null);
        }});
    }
    public static boolean requestNavigateUp(IBinder token,Intent destination,final int resultCode,Intent result){
        final Entry source=find(token);
        final Intent intent=new Intent(Objects.requireNonNull(destination));
        List<ResolveInfo> candidates=SdApkPackage.resolveActivities(intent,intent.getType(),0);
        if(candidates.isEmpty())return false;
        ActivityInfo info=candidates.get(0).activityInfo;
        Entry selected=null;
        for(int index=stack.indexOf(source)-1;index>=0;index--){
            Entry entry=stack.get(index);
            if(entry.info.packageName.equals(info.packageName)&&entry.info.name.equals(info.name)){selected=entry;break;}
        }
        if(selected==null||selected.activity==null)return false;
        final Entry parent=selected;
        final boolean reuseParent=info.launchMode==ActivityInfo.LAUNCH_SINGLE_TOP
                ||info.launchMode==ActivityInfo.LAUNCH_SINGLE_TASK
                ||info.launchMode==ActivityInfo.LAUNCH_SINGLE_INSTANCE
                ||(intent.getFlags()&Intent.FLAG_ACTIVITY_CLEAR_TOP)!=0;
        final Intent resultData=result==null?null:new Intent(result);
        final ArrayList<Entry> children=new ArrayList<Entry>(stack.subList(stack.indexOf(parent)+(reuseParent?1:0),stack.indexOf(source)+1));
        Collections.reverse(children);
        post(new Runnable(){public void run(){
            if(!stack.contains(source)||!stack.contains(parent))return;
            pause(stack.get(stack.size()-1));
            if(reuseParent)ActivityThread.currentActivityThread().getInstrumentation().callActivityOnNewIntent(parent.activity,intent);
            else try{launch(intent,source.token,null,-1);}catch(Exception failure){throw new IllegalStateException("Up Activity launch failed",failure);}
            Entry last=children.get(children.size()-1);
            for(Entry child:children){
                if(!stack.contains(child))continue;
                int code=child==source?resultCode:Activity.RESULT_CANCELED;
                Intent data=child==source?resultData:null;
                requestFinish(child.token,code,data,reuseParent&&child==last);
            }
            System.err.println("SDACTIVITY=up_requested|from="+source.info.name+"|to="+parent.info.name+"|children="+children.size());
        }});
        return true;
    }
    public static boolean requestFinish(final IBinder token,final int resultCode,final Intent result){
        return requestFinish(token,resultCode,result,true);
    }
    private static boolean requestFinish(final IBinder token,final int resultCode,final Intent result,final boolean revealPrevious){
        final Entry e=find(token);
        if(System.getenv("SAILDROID_ANDROID_LOG_STDERR")!=null)new Throwable("SDACTIVITY=finish_requested|class="+e.info.name).printStackTrace();
        post(new Runnable(){public void run(){
            if(!stack.contains(e))return;
            boolean top=isTop(token);SdPermissionController.cancel(token);pause(e);
            Entry revealed=null;
            if(top&&revealPrevious&&stack.size()>1)revealed=stack.get(stack.size()-2);
            // The revealed Activity must start/resume before the finishing one
            // stops, as in Android's pause -> resume -> stop/destroy sequence.
            // Otherwise an in-app Back transition briefly has zero started
            // Activities and looks like the entire application went away.
            if(e.resultTo!=null){
                Entry target=null;for(Entry candidate:stack)if(candidate.token==e.resultTo)target=candidate;
                if(target!=null&&target.activity!=null&&!target.activity.isFinishing()){
                    ArrayList<ResultInfo> results=new ArrayList<ResultInfo>();
                    results.add(new ResultInfo(e.resultWho,e.requestCode,resultCode,result==null?null:new Intent(result)));
                    ActivityThread.currentActivityThread().handleSendResult(target.token,results,"SailDroid child Activity finished");
                    System.err.println("SDACTIVITY=result_delivered|request_code="+e.requestCode+"|result_code="+resultCode+"|target="+target.info.name);
                }
            }
            if(e.remoteResult!=null)try{SdRemoteActivities.finish(e.remoteResult,resultCode,result,hostVisible);}catch(RemoteException failure){System.err.println("SDACTIVITY=remote_caller_ended");}
            if(revealed!=null&&hostVisible&&revealed.activity!=null)resume(revealed);
            stop(e);ActivityThread.currentActivityThread().handleDestroyActivity(token,true,0,false,"SailDroid Activity finish");
            stack.remove(e);refreshTask();
            if(stack.isEmpty()&&pendingStarts.get()>0){System.err.println("SDACTIVITY=activity_stack_empty|pending_starts="+pendingStarts.get());return;}
            if(stack.isEmpty()&&SdInstrumentation.requested()){System.err.println("SDINSTRUMENTATION=activity_stack_empty|process_retained=true");return;}
            if(stack.isEmpty()){try{SdServiceHost.closeAll();}catch(Exception failure){throw new IllegalStateException("Service cleanup failed",failure);}SdWindowHost.stop();System.exit(0);}
        }});return true;
    }
    public static void closeTask(){
        ActivityThread thread=ActivityThread.currentActivityThread();
        for(Entry entry:stack)if(entry.activity==null){closeWhenReady=true;return;}
        while(!stack.isEmpty()){
            Entry e=stack.get(stack.size()-1);SdPermissionController.cancel(e.token);pause(e);
            if(e.remoteResult!=null)try{SdRemoteActivities.finish(e.remoteResult,Activity.RESULT_CANCELED,null,false);}catch(RemoteException ignored){}
            stop(e);thread.handleDestroyActivity(e.token,true,0,false,"Sailfish task closed");stack.remove(e);
        }
        refreshTask();
        try{SdServiceHost.closeAll();}catch(Exception failure){throw new IllegalStateException("Service cleanup failed",failure);}
        System.exit(0);
    }
}
