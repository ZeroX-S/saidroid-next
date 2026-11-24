import java.util.*;

/** Explicit, one-shot diagnostics on the authenticated application control socket. */
public final class SdRuntimeDiagnostics {
    private static final Set<String> unsupported=new HashSet<String>();
    private static final class ReportingHandler implements Thread.UncaughtExceptionHandler {
        final Thread.UncaughtExceptionHandler delegate;
        ReportingHandler(Thread.UncaughtExceptionHandler delegate){this.delegate=delegate;}
        public void uncaughtException(Thread thread,Throwable failure){System.err.println("SDRUNTIME=uncaught|thread="+thread.getName()+"|type="+failure.getClass().getName());failure.printStackTrace();try{SdViewDump.dump();}catch(Throwable ignored){}if(delegate!=null)delegate.uncaughtException(thread,failure);else Runtime.getRuntime().halt(10);}
    }
    private static final class ReportingPreHandler implements Thread.UncaughtExceptionHandler {
        final Thread.UncaughtExceptionHandler delegate;
        ReportingPreHandler(Thread.UncaughtExceptionHandler delegate){this.delegate=delegate;}
        public void uncaughtException(Thread thread,Throwable failure){System.err.println("SDRUNTIME=uncaught_pre|thread="+thread.getName()+"|type="+failure.getClass().getName());failure.printStackTrace();try{SdViewDump.dump();}catch(Throwable ignored){}if(delegate!=null)delegate.uncaughtException(thread,failure);}
    }
    public static synchronized void captureUncaught(){
        if(System.getenv("SAILDROID_ANDROID_LOG_STDERR")==null)return;
        try{
            java.lang.reflect.Method get=Thread.class.getDeclaredMethod("getUncaughtExceptionPreHandler");
            java.lang.reflect.Method set=Thread.class.getDeclaredMethod("setUncaughtExceptionPreHandler",Thread.UncaughtExceptionHandler.class);
            Thread.UncaughtExceptionHandler handler=(Thread.UncaughtExceptionHandler)get.invoke(null);
            if(!(handler instanceof ReportingPreHandler))set.invoke(null,new ReportingPreHandler(handler));
            return;
        }catch(ReflectiveOperationException unavailable){/* Older cores retain the default-handler diagnostic. */}
        Thread.UncaughtExceptionHandler handler=Thread.getDefaultUncaughtExceptionHandler();if(!(handler instanceof ReportingHandler))Thread.setDefaultUncaughtExceptionHandler(new ReportingHandler(handler));
    }
    public static UnsupportedOperationException unsupported(String owner,java.lang.reflect.Method method){
        String message=owner+": "+method.toGenericString();
        if(System.getenv("SAILDROID_ANDROID_LOG_STDERR")!=null)synchronized(unsupported){if(unsupported.add(message))System.err.println("SDUNSUPPORTED="+message);}
        return new UnsupportedOperationException(message);
    }
    public static void dumpThreads(){
        long memoryStart=android.os.SystemClock.uptimeMillis();long[] memoryParts=new long[3],memtrack=new long[1];
        long pss=android.os.Debug.getPss(android.os.Process.myPid(),memoryParts,memtrack);
        android.os.Debug.MemoryInfo memory=new android.os.Debug.MemoryInfo();android.os.Debug.getMemoryInfo(memory);
        System.err.println("SDMEMORY=measured|pid="+android.os.Process.myPid()+"|pss_kb="+pss+"|uss_kb="+memoryParts[0]+"|swap_pss_kb="+memoryParts[1]+"|rss_kb="+memoryParts[2]+"|info_pss_kb="+memory.getTotalPss()+"|elapsed_ms="+(android.os.SystemClock.uptimeMillis()-memoryStart)+"|source=linux-smaps|memtrack=unavailable");
        System.err.println("SDDIAGNOSTICS=threads_begin|pid="+android.os.Process.myPid());
        Map<Thread,StackTraceElement[]> traces=Thread.getAllStackTraces();
        ArrayList<Thread> threads=new ArrayList<Thread>(traces.keySet());
        Collections.sort(threads,new Comparator<Thread>(){public int compare(Thread a,Thread b){return a.getName().compareTo(b.getName());}});
        for(Thread thread:threads){System.err.println("SDTHREAD=name:"+thread.getName()+"|id="+thread.getId()+"|state="+thread.getState());for(StackTraceElement frame:traces.get(thread))System.err.println("\tat "+frame);}
        System.err.println("SDDIAGNOSTICS=threads_end|count="+threads.size());
        final android.os.Looper main=android.os.Looper.getMainLooper();
        if(main!=null){
            main.dump(new android.util.Printer(){public void println(String text){System.err.println("SDDIAGNOSTICS=looper|"+text);}},"");
            android.os.Message message=android.os.Message.obtain(new android.os.Handler(main),new Runnable(){public void run(){SdActivityHost.dumpState();SdDisplayFrames.dumpState();SdViewDump.dump();System.err.println("SDDIAGNOSTICS=main_complete");}});message.setAsynchronous(true);message.getTarget().sendMessage(message);
        }
        try{SdServices.activityManager().dumpBroadcasts();}catch(IllegalStateException notApplication){}
        if(System.getProperty("saidroid.apk")!=null)for(android.content.pm.PackageParser.Activity receiver:SdApkPackage.parsed().receivers)for(android.content.pm.PackageParser.ActivityIntentInfo filter:receiver.intents)for(int i=0;i<filter.countActions();i++)System.err.println("SDDIAGNOSTICS=manifest_receiver|class="+receiver.info.name+"|process="+receiver.info.processName+"|action="+filter.getAction(i));
    }
}
