import android.os.*;

/** Asynchronous bridge to Sailfish's existing ordinary-user Maliit peer. */
public final class SdMaliit {
    public interface Listener { void event(long generation,int type,String text,int a,int b,int c,int d); }
    private static Handler main;
    private static volatile Listener listener;
    private static volatile boolean loaded,connecting;
    private static volatile boolean connected;
    private static native void nativeStart();
    private static native boolean nativeWidget(long generation,boolean focus,boolean changed,int type,boolean hidden,boolean prediction,boolean caps,String text,int cursor,int anchor,int enter);
    private static native boolean nativeShow(boolean show);
    public static synchronized void start(Listener value){
        listener=value;if(connected||connecting)return;connecting=true;
        main=new Handler(Looper.getMainLooper());
        // Runtime.load0 owns a process-wide monitor. An application library's
        // JNI_OnLoad may hold it while waiting for work on the UI thread.
        // Loading our keyboard bridge must therefore never wait on that
        // monitor from the UI thread. The existing native peer remains async.
        Thread loader=new Thread(new Runnable(){public void run(){
            try{if(!loaded){System.load(System.getProperty("saidroid.ime.library",System.getenv("ANDROID_ROOT")+"/lib/libsdmaliit.so"));loaded=true;}nativeStart();}
            catch(RuntimeException error){connecting=false;onNative(0,0,null,0,0,0,0);}
            catch(UnsatisfiedLinkError error){connecting=false;System.err.println("SDIME=library_unavailable");onNative(0,0,null,0,0,0,0);}
        }},"SailDroid-IME-loader");
        loader.setDaemon(true);loader.start();
    }
    public static boolean connected(){return connected;}
    public static boolean widget(long generation,boolean focus,boolean changed,int type,boolean hidden,boolean prediction,boolean caps,String text,int cursor,int anchor,int enter){return connected&&nativeWidget(generation,focus,changed,type,hidden,prediction,caps,text,cursor,anchor,enter);}
    public static boolean show(boolean show){return connected&&nativeShow(show);}
    private static void onNative(final long generation,final int type,final String text,final int a,final int b,final int c,final int d){
        if(type==0){connected=a!=0;connecting=false;}
        Message message=Message.obtain(main,new Runnable(){public void run(){Listener current=listener;if(current!=null)current.event(generation,type,text,a,b,c,d);}});
        message.setAsynchronous(true);main.sendMessage(message);
    }
}
