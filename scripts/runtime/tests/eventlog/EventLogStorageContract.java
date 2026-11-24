import android.util.EventLog;
import java.io.*;
import java.util.*;

/** Real storage and process-boundary checks, independent of official CTS counts. */
public final class EventLogStorageContract {
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[]args)throws Exception {
        System.load(args[0]);
        java.lang.reflect.Method install=EventLogVmRunner.class.getDeclaredMethod("install",String.class);install.setAccessible(true);install.invoke(null,args[1]);
        String phase=args[2];File log=new File(System.getenv("SAILDROID_DATA_DIR"),".saildroid-eventlog");
        if(phase.equals("parallel")){
            final int tag=Integer.parseInt(args[3]);final List<Throwable> failures=Collections.synchronizedList(new ArrayList<Throwable>());Thread[] threads=new Thread[4];
            for(int i=0;i<threads.length;i++){final int worker=i;threads[i]=new Thread(new Runnable(){public void run(){try{for(int n=0;n<100;n++)require(EventLog.writeEvent(tag,"worker-"+worker+":"+n)>0,"Actual event write");}catch(Throwable failure){failures.add(failure);}}});threads[i].start();}
            for(Thread thread:threads)thread.join();require(failures.isEmpty(),"Concurrent writer failures: "+failures);
            List<EventLog.Event> events=new ArrayList<EventLog.Event>();EventLog.readEvents(new int[]{tag},events);Set<String> actual=new HashSet<String>();
            for(EventLog.Event event:events){require(event.getProcessId()==android.os.Process.myPid(),"Real event PID");require(event.getThreadId()>0&&event.getTimeNanos()>0,"Real writer identity and clock");actual.add((String)event.getData());}
            require(events.size()==400&&actual.size()==400,"Concurrent records lost or duplicated");
        }else if(phase.equals("readParallel")){
            List<EventLog.Event> events=new ArrayList<EventLog.Event>();EventLog.readEvents(new int[]{70001,70002},events);
            require(events.size()==800,"Cross-process record count");Set<Integer> pids=new HashSet<Integer>();for(EventLog.Event e:events)pids.add(e.getProcessId());require(pids.size()==2&&!pids.contains(android.os.Process.myPid()),"Records retain two actual exited writer PIDs");
        }else if(phase.equals("rotate")){
            char[] bytes=new char[4000];Arrays.fill(bytes,'x');String data=new String(bytes);
            for(int n=0;n<350;n++)require(EventLog.writeEvent(70003,data)>0,"Rotation event write");
            require(EventLog.writeEvent(70004,"persisted-after-rotation")>0,"Persistent marker write");
            require(log.length()<=1024*1024,"Private log exceeds capacity");
            List<EventLog.Event> events=new ArrayList<EventLog.Event>();EventLog.readEvents(new int[]{70003},events);require(events.size()>0&&events.size()<350,"Old records did not rotate");for(EventLog.Event e:events)require(data.equals(e.getData()),"Rotation corrupted stored event");
        }else if(phase.equals("readPersisted")){
            List<EventLog.Event> events=new ArrayList<EventLog.Event>();EventLog.readEvents(new int[]{70004},events);require(events.size()==1&&"persisted-after-rotation".equals(events.get(0).getData()),"Persistent record missing");require(events.get(0).getProcessId()==Integer.parseInt(args[3])&&events.get(0).getProcessId()!=android.os.Process.myPid(),"Persistent writer PID differs");
        }else if(phase.equals("denyLink")){
            require(EventLog.writeEvent(70004,"must-not-overwrite")<0,"Linked log write accepted");boolean rejected=false;try{EventLog.readEvents(new int[]{70004},new ArrayList<EventLog.Event>());}catch(IOException expected){rejected=true;}require(rejected,"Linked log read accepted");
        }else if(phase.equals("repair")){
            require(EventLog.writeEvent(70005,"after-incomplete-tail")>0,"Append did not recover incomplete final write");List<EventLog.Event> events=new ArrayList<EventLog.Event>();EventLog.readEvents(new int[]{70004,70005},events);require(events.size()==2,"Recovery lost valid persistent record or accepted malformed trailer");
        }else throw new IllegalArgumentException(phase);
        System.out.println("EVENTLOG_STORAGE=PASS|phase="+phase+"|pid="+android.os.Process.myPid());
    }
}
