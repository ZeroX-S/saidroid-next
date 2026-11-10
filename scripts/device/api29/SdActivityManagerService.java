/* Process-local ActivityManager backend for the standalone ART runtime.
 *
 * This service owns only the Android application hosted by this Linux process.
 * It reports the real PID/UID, and records visibility only when the window host
 * explicitly reports it. Unsupported Android operations fail explicitly rather
 * than claiming that a service, activity or permission operation succeeded.
 */
import android.app.ActivityManager;
import android.app.IActivityManager;
import android.app.ContentProviderHolder;
import android.content.pm.ApplicationInfo;
import android.content.pm.ActivityInfo;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.IIntentReceiver;
import android.os.Binder;
import android.os.IBinder;
import android.os.Process;

import java.lang.reflect.Field;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.IdentityHashMap;

public final class SdActivityManagerService implements InvocationHandler {
    private final SdPendingIntents pendingIntents = new SdPendingIntents(this);
    private final Binder binder = new Binder();
    private final IActivityManager service;
    private final int pid = Process.myPid();
    private final int uid = Process.myUid();
    private String packageName;
    private String processName;
    private boolean resumed;
    private String apkPath;
    private SdAppPermissions permissions;
    private android.app.IApplicationThread applicationThread;
    private long applicationStartSequence;
    private int nextTaskId = 1;
    private final IdentityHashMap<IBinder, HostedActivity> activities =
            new IdentityHashMap<IBinder, HostedActivity>();

    private static final class HostedActivity {
        final ActivityInfo info;
        final Intent intent;
        final int displayId;
        final int taskId;
        boolean lifecycleResumed,idle;
        android.content.res.Configuration configuration;
        int[] horizontalConfigurations,verticalConfigurations,smallestConfigurations;
        ActivityManager.TaskDescription description = new ActivityManager.TaskDescription();
        HostedActivity(ActivityInfo info, Intent intent, int displayId, int taskId) {
            this.info = new ActivityInfo(info);
            this.intent = new Intent(intent);
            this.displayId = displayId;
            this.taskId = taskId;
        }
    }

    public synchronized void registerActivity(IBinder token, ActivityInfo info,
                                              Intent intent, int displayId) {
        if (token == null || info == null || intent == null) {
            throw new IllegalArgumentException("Complete Activity launch identity required");
        }
        if (packageName == null || !packageName.equals(info.packageName)) {
            throw new SecurityException("Activity owner differs from the bound Application");
        }
        if (displayId != SdDisplayShim.DISPLAY_ID) throw new IllegalArgumentException("Unknown display");
        if (activities.containsKey(token)) throw new IllegalStateException("Activity token already registered");
        activities.put(token, new HostedActivity(info, intent, displayId, 1));
    }

    private synchronized HostedActivity activity(IBinder token) {
        HostedActivity activity = activities.get(token);
        if (activity == null) throw new IllegalArgumentException("Unknown Activity token");
        return activity;
    }

    public synchronized ActivityManager.TaskDescription getActivityTaskDescription(IBinder token) {
        return new ActivityManager.TaskDescription(activity(token).description);
    }

    private synchronized void setTaskDescription(IBinder token, ActivityManager.TaskDescription description) {
        if (description == null) throw new IllegalArgumentException("Task description is required");
        activity(token).description = new ActivityManager.TaskDescription(description);
    }
    private final IdentityHashMap<IBinder, ReceiverRecord> receivers =
            new IdentityHashMap<IBinder, ReceiverRecord>();
    private final java.util.LinkedHashMap<String,int[]> broadcastCounts=new java.util.LinkedHashMap<String,int[]>();
    public synchronized void dumpBroadcasts(){
        for(ReceiverRecord record:receivers.values())for(ReceiverFilter entry:record.filters)for(int i=0;i<entry.filter.countActions();i++)System.err.println("SDDIAGNOSTICS=receiver|action="+entry.filter.getAction(i));
        for(java.util.Map.Entry<String,int[]> entry:broadcastCounts.entrySet())System.err.println("SDDIAGNOSTICS=broadcast|action="+entry.getKey()+"|sent="+entry.getValue()[0]+"|local_targets="+entry.getValue()[1]+"|remote_deliveries="+entry.getValue()[2]);
    }

    private static final class ReceiverRecord {
        final IIntentReceiver receiver;
        final List<ReceiverFilter> filters = new ArrayList<ReceiverFilter>();
        ReceiverRecord(IIntentReceiver receiver) { this.receiver = receiver; }
    }

    private static final class ReceiverFilter {
        final IntentFilter filter;
        final String permission;
        ReceiverFilter(IntentFilter filter, String permission) {
            this.filter = new IntentFilter(filter);
            this.permission = permission;
        }
    }

    private boolean holdsPermission(String permission) throws Exception {
        if (permission == null) return true;
        if (apkPath == null) return false;
        if (permissions == null) permissions = new SdAppPermissions(apkPath, packageName);
        return permissions.holds(permission);
    }

    public synchronized int checkLocalPermission(String permission, int callingPid, int callingUid)
            throws Exception {
        if (permission == null) throw new IllegalArgumentException("Permission name is required");
        return packageName != null && callingUid == uid && (callingPid == pid || callingPid == -1)
                && holdsPermission(permission) ? android.content.pm.PackageManager.PERMISSION_GRANTED
                : android.content.pm.PackageManager.PERMISSION_DENIED;
    }

    private synchronized void requireLocalUser(int user) {
        if (packageName == null) throw new IllegalStateException("No application is bound");
        if (user != uid / 100000) {
            throw new SecurityException("Cross-user broadcasts are not supported: " + user);
        }
    }

    private synchronized Intent registerReceiver(Object[] args) {
        requireLocalUser((Integer) args[5]);
        if (!packageName.equals(args[1])) throw new SecurityException("Receiver package mismatch");
        IntentFilter filter = (IntentFilter) args[3];
        if (filter == null) throw new IllegalArgumentException("IntentFilter is required");
        IIntentReceiver receiver = (IIntentReceiver) args[2];
        if (receiver != null) {
            IBinder token = receiver.asBinder();
            if (token == null) throw new IllegalArgumentException("Receiver Binder is required");
            ReceiverRecord record = receivers.get(token);
            if (record == null) {
                record = new ReceiverRecord(receiver);
                receivers.put(token, record);
            }
            record.filters.add(new ReceiverFilter(filter, (String) args[4]));
        }
        // No host sticky-event source is connected yet. There is no previously
        // received sticky Intent to return; do not invent battery/network state.
        return null;
    }

    private synchronized void unregisterReceiver(IIntentReceiver receiver) {
        if (receiver == null || receivers.remove(receiver.asBinder()) == null) {
            throw new IllegalArgumentException("Receiver was not registered");
        }
    }

    private int manifestReceiversPending;

    synchronized void checkManifestReceiverUser(int user) { requireLocalUser(user); }

    synchronized boolean allowManifestReceiver(ActivityInfo info, String[] requiredPermissions, int user) throws Exception {
        requireLocalUser(user);
        if (info == null || !packageName.equals(info.packageName))
            throw new SecurityException("Manifest receiver owner differs");
        if (!holdsPermission(info.permission)) return false;
        if (requiredPermissions != null)
            for (String permission : requiredPermissions) if (!holdsPermission(permission)) return false;
        return true;
    }

    synchronized void scheduleManifestReceiver(Intent intent, ActivityInfo info, int result,
                                                String resultData, android.os.Bundle extras, int user) throws Exception {
        requireLocalUser(user);
        if (!packageName.equals(info.packageName) || !processName.equals(info.processName))
            throw new SecurityException("Manifest receiver process differs");
        if (applicationThread == null) throw new IllegalStateException("ApplicationThread is not attached");
        manifestReceiversPending++;
        try {
            applicationThread.scheduleReceiver(new Intent(intent), new ActivityInfo(info),
                    android.content.res.CompatibilityInfo.DEFAULT_COMPATIBILITY_INFO,
                    result, resultData, extras == null ? null : new android.os.Bundle(extras),
                    false, user, ActivityManager.PROCESS_STATE_RECEIVER);
        } catch (Exception failure) {
            manifestReceiversPending--;
            throw failure;
        }
        System.err.println("SDBROADCAST=manifest_queued|class="+info.name+"|process="+processName);
    }

    private synchronized void finishManifestReceiver(IBinder token) {
        if (applicationThread == null || token != applicationThread.asBinder() || manifestReceiversPending <= 0)
            throw new IllegalArgumentException("No scheduled manifest receiver owns this completion");
        manifestReceiversPending--;
        System.err.println("SDBROADCAST=manifest_finished|pending="+manifestReceiversPending+"|process="+processName);
    }

    void dispatchPendingBroadcast(Intent intent,String type,int code,String permission,int user) throws Exception {
        String[] permissions=permission==null?null:new String[]{permission};
        if(intent.getComponent()!=null) {
            SdManifestReceivers.send(intent,code,null,null,permissions,user);
        } else {
            deliverBroadcast(intent,type,code,null,null,permissions,user,false);
            if(SdKernelServices.enabled())SdRemoteServices.broadcast(intent,type,code,null,null,permissions,user);
        }
    }

    private int broadcastIntent(Object[] args) throws Exception {
        Intent intent=(Intent)args[1];if(intent==null)throw new IllegalArgumentException("Intent is required");
        if(args[3]!=null||(Boolean)args[10]||(Boolean)args[11]||(Integer)args[8]!=-1||args[9]!=null)throw new UnsupportedOperationException("Ordered/sticky/app-op/options broadcasts unavailable");
        String[] permissions=(String[])args[7];int user=(Integer)args[12];
        if (intent.getComponent() != null) {
            SdManifestReceivers.send(intent,(Integer)args[4],(String)args[5],(android.os.Bundle)args[6],permissions,user);
            return ActivityManager.BROADCAST_SUCCESS;
        }
        deliverBroadcast(intent,(String)args[2],(Integer)args[4],(String)args[5],(android.os.Bundle)args[6],permissions,user,false);
        if(SdKernelServices.enabled())SdRemoteServices.broadcast(intent,(String)args[2],(Integer)args[4],(String)args[5],(android.os.Bundle)args[6],permissions,user);
        return ActivityManager.BROADCAST_SUCCESS;
    }
    public void deliverBroadcast(Intent intent,String type,int result,String resultData,android.os.Bundle extras,String[] requiredPermissions,int user,boolean remote)throws Exception {
        List<IIntentReceiver> targets=new ArrayList<IIntentReceiver>();
        synchronized(this){
            requireLocalUser(user);
            if(requiredPermissions!=null)for(String permission:requiredPermissions)if(!holdsPermission(permission))return;
            if(intent.getComponent()!=null)throw new UnsupportedOperationException("Manifest receivers unavailable");
            // A package-scoped broadcast for another application has no local
            // receivers. Android sendBroadcast does not throw for this case.
            // Keep same-package remote-process routing in broadcastIntent intact.
            if(intent.getPackage()!=null&&!packageName.equals(intent.getPackage())) {
                System.err.println("SDBROADCAST=local_skipped|reason=foreign-package|action="+intent.getAction()+"|target="+intent.getPackage());
                return;
            }
            for(ReceiverRecord record:receivers.values())for(ReceiverFilter entry:record.filters){
                if(entry.filter.match(intent.getAction(),type,intent.getScheme(),intent.getData(),intent.getCategories(),"SailDroidBroadcast")>=0&&holdsPermission(entry.permission)){targets.add(record.receiver);break;}
            }
            String action=intent.getAction();int[] counts=broadcastCounts.get(action);
            if(counts==null&&broadcastCounts.size()<128){counts=new int[3];broadcastCounts.put(action,counts);}
            if(counts!=null){if(!remote)counts[0]++;counts[remote?2:1]+=targets.size();}
        }
        for(IIntentReceiver receiver:targets)receiver.performReceive(new Intent(intent),result,resultData,extras==null?null:new android.os.Bundle(extras),false,false,user);
    }

    public SdActivityManagerService() {
        service = (IActivityManager) Proxy.newProxyInstance(
                IActivityManager.class.getClassLoader(),
                new Class<?>[]{IActivityManager.class}, this);
        binder.attachInterface(service, "android.app.IActivityManager");
    }

    public IBinder asBinder() {
        return binder;
    }

    public synchronized void bindApplication(ApplicationInfo info) {
        if (info == null || info.packageName == null || info.packageName.length() == 0) {
            throw new IllegalArgumentException("Application package is required");
        }
        String name = info.processName;
        if (name == null || name.length() == 0) name = info.packageName;
        if (packageName != null && (!packageName.equals(info.packageName)
                || !processName.equals(name))) {
            throw new IllegalStateException("This ART process already hosts " + processName);
        }
        packageName = info.packageName;
        processName = name;
        if (apkPath == null) apkPath = info.sourceDir;
    }

    /** Called by the actual activity/window host, never inferred from a query. */
    public synchronized void setActivityResumed(boolean value) {
        if (packageName == null) throw new IllegalStateException("No application is bound");
        resumed = value;
    }

    /** Repair an earlier cached null without replacing another service owner. */
    public void installFrameworkCache() throws Exception {
        Field field = Class.forName("android.app.ActivityManager")
                .getDeclaredField("IActivityManagerSingleton");
        field.setAccessible(true);
        Object singleton = field.get(null);
        Field instance = Class.forName("android.util.Singleton").getDeclaredField("mInstance");
        instance.setAccessible(true);
        synchronized (singleton) {
            Object previous = instance.get(singleton);
            if (previous != null && previous != service) {
                throw new IllegalStateException("ActivityManager already has another owner");
            }
            instance.set(singleton, service);
        }
    }

    private synchronized ActivityManager.RunningAppProcessInfo snapshot() {
        if (packageName == null) return null;
        ActivityManager.RunningAppProcessInfo info = new ActivityManager.RunningAppProcessInfo();
        info.pid = pid;
        info.uid = uid;
        info.processName = processName;
        info.pkgList = new String[]{packageName};
        boolean services=SdServiceHost.hasLiveServices();
        info.importance = resumed ? ActivityManager.RunningAppProcessInfo.IMPORTANCE_FOREGROUND
                : services?ActivityManager.RunningAppProcessInfo.IMPORTANCE_SERVICE:ActivityManager.RunningAppProcessInfo.IMPORTANCE_BACKGROUND;
        info.processState = resumed ? ActivityManager.PROCESS_STATE_TOP
                : services?ActivityManager.PROCESS_STATE_SERVICE:activities.isEmpty()?ActivityManager.PROCESS_STATE_CACHED_EMPTY:ActivityManager.PROCESS_STATE_CACHED_ACTIVITY;
        return info;
    }

    private synchronized boolean processOwned(int target){
        if(target==pid)return true;if(target<=0||packageName==null)return false;
        try{
            java.nio.file.Path proc=java.nio.file.Paths.get("/proc/"+target);
            String status=new String(java.nio.file.Files.readAllBytes(proc.resolve("status")),"UTF-8");boolean sameUid=false;
            for(String line:status.split("\n"))if(line.startsWith("Uid:"))sameUid=Integer.parseInt(line.substring(4).trim().split("\\s+")[0])==uid;
            String command=new String(java.nio.file.Files.readAllBytes(proc.resolve("cmdline")),"UTF-8");int end=command.indexOf('\0');if(end>=0)command=command.substring(0,end);
            return sameUid&&(command.equals(packageName)||command.startsWith(packageName+":"));
        }catch(java.io.IOException gone){return false;}
    }
    private android.os.Debug.MemoryInfo[] processMemory(int[] targets){
        if(targets==null)throw new IllegalArgumentException("Process IDs required");
        android.os.Debug.MemoryInfo[] result=new android.os.Debug.MemoryInfo[targets.length];
        for(int i=0;i<targets.length;i++){
            result[i]=new android.os.Debug.MemoryInfo();
            if(!processOwned(targets[i]))continue; // API29 hides unrelated app memory.
            try{android.os.Debug.getMemoryInfo(targets[i],result[i]);}
            catch(IllegalStateException unavailable){if(targets[i]==pid)throw unavailable;}
        }
        return result;
    }
    private static void memoryInfo(ActivityManager.MemoryInfo target) throws java.io.IOException {
        if (target == null) throw new IllegalArgumentException("MemoryInfo required");
        java.util.Map<String,Long> values=new java.util.HashMap<String,Long>();
        try(java.io.BufferedReader input=new java.io.BufferedReader(new java.io.FileReader("/proc/meminfo"))){
            String line;while((line=input.readLine())!=null){String[] fields=line.trim().split("\\s+");
                if(fields.length>=2)values.put(fields[0],Long.parseLong(fields[1])*1024L);
            }
        }
        target.totalMem=values.get("MemTotal:");
        Long available=values.get("MemAvailable:");
        target.availMem=available!=null?available:values.get("MemFree:")+values.get("Cached:")+values.get("Buffers:");
        // This runtime owns no Android low-memory killer. Its pressure boundary
        // follows Linux's actual minimum free-page policy, not invented RAM.
        try(java.io.BufferedReader input=new java.io.BufferedReader(new java.io.FileReader("/proc/sys/vm/min_free_kbytes"))){
            target.threshold=Long.parseLong(input.readLine().trim())*1024L;
        }
        target.lowMemory=target.availMem<=target.threshold;
        target.hiddenAppThreshold=target.secondaryServerThreshold=target.visibleAppThreshold=target.foregroundAppThreshold=target.threshold;
    }

    @Override
    public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        String name = method.getName();
        if (method.getDeclaringClass() == Object.class) {
            if ("toString".equals(name)) return "SaiDroidActivityManager(pid=" + pid + ")";
            if ("hashCode".equals(name)) return System.identityHashCode(proxy);
            if ("equals".equals(name)) return proxy == args[0];
        }
        if ("asBinder".equals(name)) return binder;
        if ("setRenderThread".equals(name)) {
            int tid=(Integer)args[0];
            if(tid<=0||!new java.io.File("/proc/self/task/"+tid).isDirectory())
                throw new SecurityException("RenderThread does not belong to this application process");
            Process.setThreadPriority(tid,Process.THREAD_PRIORITY_DISPLAY);
            System.err.println("SDHWUI=render_thread_registered|tid="+tid+"|nice="+Process.getThreadPriority(tid));
            return null;
        }
        if ("startService".equals(name)){if(SdKernelServices.enabled()&&SdRemoteServices.isRemote((Intent)args[1],(String)args[2]))return SdRemoteServices.start((Intent)args[1],(String)args[2],(Boolean)args[3],(String)args[4],(Integer)args[5]);return SdServiceHost.start((Intent)args[1],(String)args[2],(Boolean)args[3],(String)args[4],(Integer)args[5]);}
        if ("stopService".equals(name)){if(SdKernelServices.enabled()&&SdRemoteServices.isRemote((Intent)args[1],(String)args[2]))return SdRemoteServices.stop((Intent)args[1],(String)args[2],(Integer)args[3]);return SdServiceHost.stop((Intent)args[1],(String)args[2],(Integer)args[3]);}
        if ("bindService".equals(name)){if(SdKernelServices.enabled()&&SdRemoteServices.isRemote((Intent)args[2],(String)args[3]))return SdRemoteServices.bind((Intent)args[2],(String)args[3],(android.app.IServiceConnection)args[4],(Integer)args[5],(String)args[6],(Integer)args[7]);return SdServiceHost.bind((Intent)args[2],(String)args[3],(android.app.IServiceConnection)args[4],(Integer)args[5],(String)args[6],(Integer)args[7]);}
        if ("bindIsolatedService".equals(name)) {
            if(args[6]!=null)throw new UnsupportedOperationException("Isolated Service processes are unavailable");
            if(SdKernelServices.enabled()&&SdRemoteServices.isRemote((Intent)args[2],(String)args[3]))return SdRemoteServices.bind((Intent)args[2],(String)args[3],(android.app.IServiceConnection)args[4],(Integer)args[5],(String)args[7],(Integer)args[8]);
            return SdServiceHost.bind((Intent)args[2],(String)args[3],(android.app.IServiceConnection)args[4],(Integer)args[5],(String)args[7],(Integer)args[8]);
        }
        if ("unbindService".equals(name)){boolean local=SdServiceHost.unbind((android.app.IServiceConnection)args[0]);boolean remote=SdKernelServices.enabled()&&SdRemoteServices.unbind((android.app.IServiceConnection)args[0]);return local||remote;}
        if ("publishService".equals(name)){SdServiceHost.publish((IBinder)args[0],(Intent)args[1],(IBinder)args[2]);return null;}
        if ("stopServiceToken".equals(name))return SdServiceHost.stopToken((android.content.ComponentName)args[0],(IBinder)args[1],(Integer)args[2]);
        if ("serviceDoneExecuting".equals(name)){SdServiceHost.done((IBinder)args[0],(Integer)args[1],(Integer)args[2],(Integer)args[3]);return null;}
        if ("unbindFinished".equals(name)){SdServiceHost.unbindFinished((IBinder)args[0],(Intent)args[1],(Boolean)args[2]);return null;}
        if ("peekService".equals(name)){if(SdKernelServices.enabled()&&SdRemoteServices.isRemote((Intent)args[0],(String)args[1]))return SdRemoteServices.peek((Intent)args[0],(String)args[1]);return SdServiceHost.peek((Intent)args[0],(String)args[1]);}
        if ("getServices".equals(name))return SdServiceHost.running((Integer)args[0]);
        if ("getTasks".equals(name))return System.getProperty("saidroid.service")!=null?SdRemoteServices.tasks((Integer)args[0]):SdActivityHost.runningTasks((Integer)args[0]);
        if ("setServiceForeground".equals(name)){
            if((Integer)args[2]!=0)throw new UnsupportedOperationException("Foreground Service notifications are unavailable");
            return null; // No foreground notification was published by this backend.
        }
        if ("getForegroundServiceType".equals(name))return 0; // Foreground starts are rejected above.
        if ("getCurrentUser".equals(name)) return SdUsers.current();
        if ("finishReceiver".equals(name)) {finishManifestReceiver((IBinder)args[0]);return null;}
        if ("attachApplication".equals(name)) {
            android.app.IApplicationThread incoming=(android.app.IApplicationThread)args[0];
            if(applicationThread!=null&&applicationThread.asBinder()!=incoming.asBinder())throw new IllegalStateException("Another application thread is already attached");
            applicationThread=incoming;applicationStartSequence=(Long)args[1];return null;
        }
        if ("addInstrumentationResults".equals(name)||"finishInstrumentation".equals(name)){
            android.app.IApplicationThread caller=(android.app.IApplicationThread)args[0];
            if(applicationThread==null||caller==null||caller.asBinder()!=applicationThread.asBinder())throw new SecurityException("Instrumentation ApplicationThread differs");
            if(name.equals("addInstrumentationResults"))SdInstrumentation.add((android.os.Bundle)args[1]);else SdInstrumentation.finish((Integer)args[1],(android.os.Bundle)args[2]);return null;
        }
        if ("getMemoryInfo".equals(name)) { memoryInfo((ActivityManager.MemoryInfo)args[0]);return null; }
        if ("getProcessMemoryInfo".equals(name))return processMemory((int[])args[0]);
        if ("getContentProvider".equals(name)) return SdContentProviders.acquire((String)args[2],(Integer)args[3]);
        if ("publishContentProviders".equals(name)) {
            SdContentProviders.publish((java.util.List<android.app.ContentProviderHolder>)args[1]);return null;
        }
        if ("checkPermission".equals(name)) {
            return checkLocalPermission((String) args[0], (Integer) args[1], (Integer) args[2]);
        }
        if ("activityResumed".equals(name)) { activity((IBinder)args[0]).lifecycleResumed=true;setActivityResumed(true);return null; }
        if ("activityPaused".equals(name)||"activityStopped".equals(name)) {
            activity((IBinder)args[0]).lifecycleResumed=false;
            boolean any=false;for(HostedActivity item:activities.values())any|=item.lifecycleResumed;setActivityResumed(any);return null;
        }
        if ("activityIdle".equals(name)) {
            HostedActivity current=activity((IBinder)args[0]);current.idle=true;
            if(args[1]!=null)current.configuration=new android.content.res.Configuration((android.content.res.Configuration)args[1]);return null;
        }
        if ("activityDestroyed".equals(name)) {activity((IBinder)args[0]);activities.remove((IBinder)args[0]);return null;}
        if ("getCallingActivity".equals(name)||"getCallingPackage".equals(name)) {
            android.content.ComponentName caller=SdActivityHost.callingActivity((IBinder)args[0]);
            return "getCallingActivity".equals(name)?caller:caller==null?null:caller.getPackageName();
        }
        if ("getActivityDisplayId".equals(name)) return activity((IBinder) args[0]).displayId;
        if ("reportSizeConfigurations".equals(name)) {
            HostedActivity current=activity((IBinder)args[0]);current.horizontalConfigurations=args[1]==null?null:((int[])args[1]).clone();current.verticalConfigurations=args[2]==null?null:((int[])args[2]).clone();current.smallestConfigurations=args[3]==null?null:((int[])args[3]).clone();return null;
        }
        if ("getTaskForActivity".equals(name)) return activity((IBinder) args[0]).taskId;
        if ("setTaskDescription".equals(name)) {
            setTaskDescription((IBinder) args[0], (ActivityManager.TaskDescription) args[1]);
            return null;
        }
        if ("getActivityOptions".equals(name)) {
            activity((IBinder) args[0]);
            // This host's launch request supplied no ActivityOptions bundle.
            return null;
        }
        if ("getIntentSender".equals(name)||"cancelIntentSender".equals(name)||"sendIntentSender".equals(name)
                ||"getPackageForIntentSender".equals(name)||"getUidForIntentSender".equals(name)
                ||"getIntentForIntentSender".equals(name)||"getTagForIntentSender".equals(name)
                ||"isIntentSenderAnActivity".equals(name)||"isIntentSenderAForegroundService".equals(name)
                ||"isIntentSenderABroadcast".equals(name)||"isIntentSenderTargetedToPackage".equals(name)
                ||"registerIntentSenderCancelListener".equals(name)||"unregisterIntentSenderCancelListener".equals(name))
            return pendingIntents.invoke(name,args);
        if ("registerReceiver".equals(name)) return registerReceiver(args);
        if ("unregisterReceiver".equals(name)) {
            unregisterReceiver((IIntentReceiver) args[0]);
            return null;
        }
        if ("broadcastIntent".equals(name)) return broadcastIntent(args);
        if ("getRunningAppProcesses".equals(name)) {
            List<ActivityManager.RunningAppProcessInfo> result =
                    new ArrayList<ActivityManager.RunningAppProcessInfo>();
            ActivityManager.RunningAppProcessInfo current = snapshot();
            if (current != null) result.add(current);
            return result;
        }
        if ("getMyMemoryState".equals(name)) {
            ActivityManager.RunningAppProcessInfo current = snapshot();
            if (current == null) throw new IllegalStateException("No application is bound");
            ActivityManager.RunningAppProcessInfo target =
                    (ActivityManager.RunningAppProcessInfo) args[0];
            if (target == null) throw new IllegalArgumentException("Process info is required");
            target.pid = current.pid;
            target.uid = current.uid;
            target.processName = current.processName;
            target.pkgList = current.pkgList;
            target.importance = current.importance;
            target.processState = current.processState;
            return null;
        }
        if ("getPackageProcessState".equals(name)) {
            ActivityManager.RunningAppProcessInfo current = snapshot();
            return current != null && current.pkgList[0].equals(args[0])
                    ? current.processState : ActivityManager.PROCESS_STATE_NONEXISTENT;
        }
        if ("testIsSystemReady".equals(name)) return snapshot() != null;
        throw SdRuntimeDiagnostics.unsupported("SaiDroid ActivityManager",method);
    }
}
