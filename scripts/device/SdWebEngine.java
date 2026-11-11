import android.graphics.Bitmap;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONObject;
import java.io.*;
import java.nio.ByteBuffer;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

/** One isolated Qt/WPE host per WebView. The UI thread never waits for IPC. */
public final class SdWebEngine {
    public static final int MAX_HOST_WIDTH=2160,MAX_HOST_HEIGHT=4096;
    public static final int MAX_FRAME_BYTES=MAX_HOST_WIDTH*MAX_HOST_HEIGHT*4;

    /** Match the native host's dimensions AND byte budget without distorting pages. */
    public static int[] hostSize(int requestedWidth, int requestedHeight) {
        int w=Math.max(1,requestedWidth),h=Math.max(1,requestedHeight);
        double scale=Math.min(1.0,Math.min((double)MAX_HOST_WIDTH/w,(double)MAX_HOST_HEIGHT/h));
        scale=Math.min(scale,Math.sqrt((double)MAX_FRAME_BYTES/4/w/h));
        return new int[]{Math.max(1,(int)Math.floor(w*scale)),Math.max(1,(int)Math.floor(h*scale))};
    }

    public static JSONObject touchCommand(int action,float x,float y,long time,int viewWidth,int viewHeight)
            throws org.json.JSONException {
        return new JSONObject().put("op","touch").put("action",action).put("x",x).put("y",y)
                .put("viewWidth",viewWidth).put("viewHeight",viewHeight).put("time",time);
    }
    public interface Listener {
        void event(JSONObject event);
        void frame(Bitmap bitmap, long sequence);
        void failed(String reason);
    }
    private final Listener listener;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ArrayBlockingQueue<JSONObject> commands = new ArrayBlockingQueue<JSONObject>(128);
    private volatile boolean closed;
    private java.lang.Process process;
    private Bitmap bitmap;
    private byte[] pixels;
    private final String helper, profile;
    private final int width, height;

    public static String helperPath() {
        String override = System.getenv("SAILDROID_WEBVIEW_HELPER");
        String root = System.getenv("ANDROID_ROOT");
        return override != null ? override : root + "/libexec/sdwebview-host";
    }
    public static boolean available() { return new File(helperPath()).canExecute(); }

    public SdWebEngine(File directory, int w, int h, Listener target) {
        helper = helperPath(); profile = new File(directory,"webview-host").getAbsolutePath();
        int[] size=hostSize(w,h);width=size[0];height=size[1];listener=target;
        Thread starter = new Thread(new Runnable() { public void run() { start(); } },"sd-webview-reader");
        starter.setDaemon(true);starter.start();
    }
    private void start() {
        try {
            File home = new File(profile); if (!home.isDirectory() && !home.mkdirs()) throw new IOException("profile directory unavailable");
            ProcessBuilder builder = new ProcessBuilder(helper,String.valueOf(width),String.valueOf(height));
            Map<String,String> env=builder.environment();
            // Do not feed the ART preload/linker configuration into a glibc host.
            env.clear(); env.put("PATH","/usr/bin:/bin");env.put("HOME",profile);
            env.put("XDG_DATA_HOME",profile+"/data");env.put("XDG_CACHE_HOME",profile+"/cache");env.put("XDG_CONFIG_HOME",profile+"/config");
            env.put("XDG_RUNTIME_DIR","/run/user/"+android.os.Process.myUid());
            env.put("WAYLAND_DISPLAY","../../display/wayland-0");
            env.put("DBUS_SESSION_BUS_ADDRESS","unix:path=/run/user/"+android.os.Process.myUid()+"/dbus/user_bus_socket");
            java.lang.Process child=builder.start();
            synchronized(this) { process=child; if(closed){child.destroy();return;} }
            Thread errors=new Thread(new Runnable(){public void run(){
                try(BufferedReader log=new BufferedReader(new InputStreamReader(child.getErrorStream(),"UTF-8"))){
                    String line;while((line=log.readLine())!=null)System.err.println("SDWEBHOST_LOG="+line);
                }catch(IOException ignored){}
            }},"sd-webview-log");errors.setDaemon(true);errors.start();
            Thread writer=new Thread(new Runnable(){public void run(){
                try(DataOutputStream out=new DataOutputStream(child.getOutputStream())){
                    while(!closed){JSONObject command=commands.poll(1,TimeUnit.SECONDS);if(command==null)continue;
                        byte[] encoded=command.toString().getBytes("UTF-8");
                        if(encoded.length>4*1024*1024-4)throw new IOException("command too large");
                        out.writeInt(encoded.length);out.write(encoded);out.flush();}
                }catch(Exception failure){if(!closed)fail("write:"+failure.getClass().getSimpleName());}
            }},"sd-webview-writer");writer.setDaemon(true);writer.start();
            try(DataInputStream input=new DataInputStream(new BufferedInputStream(child.getInputStream(),65536))){
                while(!closed){
                    int bytes=input.readInt();if(bytes<1||bytes>1024*1024)throw new IOException("invalid event length");
                    byte[] json=new byte[bytes];input.readFully(json);
                    final JSONObject event=new JSONObject(new String(json,"UTF-8"));
                    if("frame".equals(event.optString("event"))){
                        final int w=event.getInt("width"),h=event.getInt("height"),count=event.getInt("bytes");
                        final long seq=event.getLong("seq");
                        if(w<1||h<1||w>MAX_HOST_WIDTH||h>MAX_HOST_HEIGHT||(long)w*h*4!=count||count>MAX_FRAME_BYTES||!"rgba8888".equals(event.getString("format")))throw new IOException("invalid frame geometry");
                        if(pixels==null||pixels.length!=count)pixels=new byte[count];
                        input.readFully(pixels);final byte[] framePixels=pixels;
                        ui.post(new Runnable(){public void run(){
                            if(closed)return;
                            try{
                                if(bitmap==null||bitmap.getWidth()!=w||bitmap.getHeight()!=h){
                                    if(bitmap!=null)bitmap.recycle();bitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);
                                }
                                bitmap.copyPixelsFromBuffer(ByteBuffer.wrap(framePixels));
                                if(System.getenv("SAILDROID_WEBVIEW_DIAGNOSTICS")!=null && seq<=20) {
                                    try(java.io.FileOutputStream dump=new java.io.FileOutputStream(profile+"/frame-"+seq+".png")){bitmap.compress(Bitmap.CompressFormat.PNG,100,dump);}
                                    catch(IOException diagnostic){System.err.println("SDWEBVIEW=frame_dump_failed");}
                                }
                                listener.frame(bitmap,seq);
                                send(new JSONObject().put("op","frame_ack").put("seq",seq));
                            }catch(Throwable failure){fail("frame:"+failure.getClass().getSimpleName());}
                        }});
                    }else ui.post(new Runnable(){public void run(){if(!closed)try{listener.event(event);}catch(Throwable callback){System.err.println("SDWEBVIEW=callback_failed|"+callback.getClass().getSimpleName());}}});
                }
            }
        }catch(Exception failure){if(!closed)fail("host:"+failure.getClass().getSimpleName()+":"+failure.getMessage());}
    }
    public boolean send(JSONObject command) {
        if(closed)return false;
        if(!commands.offer(command)){fail("command queue overflow");return false;}
        return true;
    }
    private void fail(final String reason) {
        if(closed)return;close();
        ui.post(new Runnable(){public void run(){listener.failed(reason);}});
    }
    public synchronized void close() {
        if(closed)return;closed=true;commands.clear();
        if(process!=null)process.destroy();
        // Bitmap may still be referenced by the current UI draw. It is reclaimed
        // with the provider; never recycle it from this background thread.
    }
}
