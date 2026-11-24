import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Rect;
import android.view.Surface;
import android.view.SurfaceControl;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;

/** Window layers: native HWUI Surfaces, or the explicit software diagnostic backend. */
public final class SdSurfaceStore {
    private static final LinkedHashMap<Long,Layer> layers=new LinkedHashMap<Long,Layer>();
    private static long next=1;
    private static Bitmap scene;
    private static Canvas compositor;
    private static int[] pixels;
    private static long composedFrames;
    private static final boolean traceFrames=Boolean.getBoolean("saidroid.diagnostics.frames");
    /* Per-frame benchmark counter: one increment per full-screen compose().
       Gate on the same environment variable as the native frame sampling, so a
       normal run (SAILDROID_PERF unset) executes exactly the old code path. */
    private static final boolean perfTrace=System.getenv("SAILDROID_PERF")!=null;
    private static long composes;
    /* Where the per-frame UI-thread time goes, accumulated only when sampling is
       on: erase, the layer blits, the full-screen getPixels, and present(). */
    private static long composeEraseNs,composeDrawNs,composePixelsNs,composePresentNs;
    /* Frame-pump counters, so "the view did not redraw" and "the view redrew but the
       frame never got composited" can be told apart from one run: locks (lock() entry
       = a view really started drawing), unlocks (unlock() = it handed the frame over)
       and draws (transactionComplete() = the surface transaction closed). */
    private static long locks,unlocks,draws;
    /* Coalescing is opt-in: defer one compose to the next compositor frame
       callback instead of one compose per layer unlock. The default stays
       immediate because the compositor may answer frame callbacks much more
       slowly than we commit (measured), and waiting would add latency. */
    private static final boolean composeOnVsync=System.getenv("SAILDROID_COMPOSE_ON_VSYNC")!=null;
    /* A/B switch for the single-layer fast path: same binary, two environments,
       so "before" and "after" can be measured back to back without rebuilding. */
    private static final boolean fastPathEnabled=System.getenv("SAILDROID_NO_FASTPATH")==null;
    /* Copy the single full-screen layer's pixels straight into the spare wl_shm
       buffer (bitmap ARGB_8888 memory is RGBA, so the native side negotiates
       WL_SHM_FORMAT_ABGR8888). On by default since r80: it is the best
       configuration, and only worth having when the third buffer is there too
       (on two buffers the UI thread waits for a free one and gets slower).
       SAILDROID_NO_DIRECT_COPY / SAILDROID_NO_TRIPLE_BUFFER turn them off. */
    private static final boolean directCopyEnabled=System.getenv("SAILDROID_NO_DIRECT_COPY")==null;
    private static final long COMPOSE_FALLBACK_MS=100;
    private static android.os.Handler queue;
    private static boolean composePending,composeScheduled;
    private static long composeRequests,composeFallbacks,fastPathFrames;
    /* Proof counters for the direct-copy path: frames actually sent through the
       wl_shm ByteBuffer, and frames where both buffers were busy so the staging
       path had to run instead. */
    private static long directCopies,directMisses,directDrops;
    /* A dropped frame is fine while the page keeps drawing, but a static page
       draws once: if that one frame is dropped the window stays on stale pixels
       and looks frozen, which is worse than slow. So once 100 ms later force a
       staging compose, whatever the buffer state. */
    private static long recoveries;
    private static boolean recoveryScheduled,forceStaging;
    private static boolean directActive;
    private static int directMissStreak;
    /* 必须是 long：native 侧 GetStaticFieldID 声明的是 "J"，这里写成 int 会让 JNI
       拿到 NULL fieldID 并留下 pending NoSuchFieldError —— ART 在下一个 JNI 调用处
       直接 abort（2026-10-26 真机事故：QQ 启动即 SIGSEGV，栈里只有 GC 线程，看不出真因）。 */
    private static long lastLayerCount;
    private static long lastLayerAlphaMilli=-1,lastLayerFull=-1,lastLayerIdentity=-1;
    /* Reused every frame: this is the hot path. */
    private static final java.util.ArrayList<Layer> orderedLayers=new java.util.ArrayList<Layer>();
    private static final android.graphics.Paint layerPaint=new android.graphics.Paint();
    private static final java.util.Comparator<Layer> byDepth=new java.util.Comparator<Layer>() {
        @Override public int compare(Layer a,Layer b){return Integer.compare(a.z,b.z);}
    };
    private static final Runnable composeFromVsync=new Runnable(){@Override public void run(){flushCompose(false);}};
    private static final Runnable composeFallback=new Runnable(){@Override public void run(){flushCompose(true);}};
    private static final Field nativeObject;
    private static final Method setNativeObject;
    private static final Field controlObject,controlWidth,controlHeight;
    static {
        try{
            nativeObject=Surface.class.getDeclaredField("mNativeObject");nativeObject.setAccessible(true);
            setNativeObject=Surface.class.getDeclaredMethod("setNativeObjectLocked",long.class);setNativeObject.setAccessible(true);
            controlObject=SurfaceControl.class.getDeclaredField("mNativeObject");controlObject.setAccessible(true);
            controlWidth=SurfaceControl.class.getDeclaredField("mWidth");controlWidth.setAccessible(true);
            controlHeight=SurfaceControl.class.getDeclaredField("mHeight");controlHeight.setAccessible(true);
        }catch(Exception failure){throw new ExceptionInInitializerError(failure);}
    }
    private static final class Layer {
        final long id;
        long hardwareSurface;
        Bitmap bitmap;
        final Rect frame=new Rect();
        Canvas locked;
        int references;
        boolean removed,visible=true;
        int z;
        float alpha=1;
        float dim;
        final android.graphics.Matrix matrix=new android.graphics.Matrix();
        Rect crop;
        final android.os.Binder handle=new android.os.Binder();
        long frameNumber;
        Layer(long id){this.id=id;}
    }
    private static Layer layer(long id){Layer layer=layers.get(id);if(layer==null)throw new IllegalArgumentException("Unknown Surface buffer "+id);return layer;}
    public static synchronized long create(){long id=next++;layers.put(id,new Layer(id));return id;}
    public static synchronized void layout(long id,Rect frame,boolean visible){
        Layer layer=layer(id);
        if(layer.locked!=null)throw new IllegalStateException("Cannot resize a locked Surface");
        layer.frame.set(frame);layer.visible=visible;
        if(SdWindowHost.hardware()){
            if(layer.hardwareSurface==0){
                layer.hardwareSurface=SdWindowHost.nativeHardwareSurface((int)id,Math.max(1,frame.width()),Math.max(1,frame.height()));
                if(layer.hardwareSurface==0)throw new IllegalStateException("HWUI Surface creation failed");
            }
            SdWindowHost.nativeHardwareZ(layer.hardwareSurface,layer.z);
            SdWindowHost.nativeHardwareLayout(layer.hardwareSurface,frame.left,frame.top,Math.max(1,frame.width()),Math.max(1,frame.height()),visible);
            return;
        }
        if(layer.bitmap==null||layer.bitmap.getWidth()!=frame.width()||layer.bitmap.getHeight()!=frame.height()){
            if(layer.bitmap!=null)layer.bitmap.recycle();
            layer.bitmap=Bitmap.createBitmap(Math.max(1,frame.width()),Math.max(1,frame.height()),Bitmap.Config.ARGB_8888);
            layer.bitmap.setDensity(0);
        }
    }
    public static synchronized void attach(Surface surface,long id)throws Exception{
        Layer layer = layer(id);
        long old = nativeObject.getLong(surface);
        if (SdWindowHost.hardware()) {
            long pointer = layer.hardwareSurface;
            if (pointer == 0) throw new IllegalStateException("HWUI Surface is not allocated");
            if (old == pointer) return;
            if (old != 0) SdWindowHost.nativeHardwareRelease(old);
            setNativeObject.invoke(surface, SdWindowHost.nativeHardwareRetain(pointer));
            return;
        }
        if (old == id) return;
        if (old != 0) release(old);
        layer.references++;
        setNativeObject.invoke(surface, id);
    }
    public static synchronized void attachControl(SurfaceControl control,long id,int width,int height)throws Exception{
        long old=controlObject.getLong(control);if(old!=id){if(old!=0)release(old);retain(id);controlObject.setLong(control,id);}
        controlWidth.setInt(control,width);controlHeight.setInt(control,height);
    }
    public static synchronized long retain(long id){layer(id).references++;return id;}
    public static synchronized long surfaceFromControl(long old,long control){
        if(SdWindowHost.hardware()){
            long pointer=layer(control).hardwareSurface;
            if(pointer==0)throw new IllegalStateException("GPU layer has no native Surface");
            if(old==pointer)return old;
            if(old!=0)SdWindowHost.nativeHardwareRelease(old);
            return SdWindowHost.nativeHardwareRetain(pointer);
        }
        if(old==control)return old;if(old!=0)release(old);return retain(control);
    }
    public static synchronized android.os.IBinder handle(long id){return layer(id).handle;}
    public static synchronized long controlForSurface(long pointer){
        for(Layer current:layers.values()){
            if(!current.removed&&current.hardwareSurface==pointer&&pointer!=0)return current.id;
        }
        throw new IllegalArgumentException("Surface is outside the owned window layers");
    }
    public static synchronized long controlForHandle(android.os.IBinder handle){
        if(handle==null)return 0;
        for(Layer current:layers.values()){
            if(!current.removed&&current.handle==handle)return current.id;
        }
        throw new IllegalArgumentException("SurfaceControl handle is outside the owned window layers");
    }
    public static synchronized long nextFrame(long id){if(SdWindowHost.hardware())return 1;return layer(id).frameNumber+1;}
    private static void syncHardware(Layer l){if(l.hardwareSurface!=0){SdWindowHost.nativeHardwareZ(l.hardwareSurface,l.z);SdWindowHost.nativeHardwareLayout(l.hardwareSurface,l.frame.left,l.frame.top,Math.max(1,l.frame.width()),Math.max(1,l.frame.height()),l.visible);}}
    public static synchronized void position(long id,float x,float y){Layer l=layer(id);l.frame.offsetTo(Math.round(x),Math.round(y));syncHardware(l);}
    public static synchronized void size(long id,int width,int height){Layer l=layer(id);layout(id,new Rect(l.frame.left,l.frame.top,l.frame.left+width,l.frame.top+height),l.visible);}
    public static synchronized void z(long id,int value){Layer l=layer(id);l.z=value;if(SdWindowHost.hardware()&&l.hardwareSurface!=0)SdWindowHost.nativeHardwareZ(l.hardwareSurface,value);}
    public static synchronized void dim(long id,float amount){layer(id).dim=Math.max(0,Math.min(1,amount));}
    public static synchronized void alpha(long id,float value){if(value<0||value>1)throw new IllegalArgumentException("Layer alpha out of range");layer(id).alpha=value;}
    public static synchronized void flags(long id,int value,int mask){if((mask&~1)!=0)throw new UnsupportedOperationException("Protected/secure layers are not supported");if((mask&1)!=0){Layer l=layer(id);l.visible=(value&1)==0;syncHardware(l);}}
    public static synchronized void matrix(long id,float a,float b,float c,float d){layer(id).matrix.setValues(new float[]{a,b,0,c,d,0,0,0,1});}
    public static synchronized void crop(long id,int x,int y,int width,int height){layer(id).crop=width<0||height<0?null:new Rect(x,y,x+width,y+height);}
    public static synchronized void transactionComplete(){if(SdWindowHost.hardware())return;if(perfTrace)draws++;if(!layers.isEmpty())requestCompose();}
    public static synchronized boolean valid(long id){Layer layer=layers.get(id);return layer!=null&&!layer.removed&&layer.bitmap!=null;}
    public static synchronized boolean consumerBehind(long id){layer(id);return false; /* One pending scene replaces its predecessor; no unbounded consumer queue. */}
    public static synchronized int width(long id){return layer(id).bitmap.getWidth();}
    public static synchronized int height(long id){return layer(id).bitmap.getHeight();}
    public static synchronized void allocate(long id){if(!valid(id))throw new IllegalStateException("Surface has no live buffers");}
    public static synchronized long lock(long id,Canvas canvas,Rect dirty){
        Layer layer=layer(id);allocate(id);
        if(layer.locked!=null)throw new IllegalStateException("Surface is already locked");
        if(perfTrace)locks++;
        canvas.setBitmap(layer.bitmap);canvas.setDensity(0);
        if(dirty!=null)dirty.set(0,0,layer.bitmap.getWidth(),layer.bitmap.getHeight());
        layer.locked=canvas;layer.references++;return id;
    }
    public static synchronized void unlock(long id,Canvas canvas){
        Layer layer=layer(id);if(layer.locked!=canvas)throw new IllegalStateException("Canvas does not own this lock");
        canvas.setBitmap(null);layer.locked=null;layer.frameNumber++;
        if(perfTrace)unlocks++;
        if(traceFrames)System.err.println("SDSURFACE=layer_posted|id="+id+"|frame="+layer.frame+"|visible="+layer.visible+"|z="+layer.z+"|alpha="+layer.alpha+"|matrix="+layer.matrix+"|crop="+layer.crop);
        requestCompose();
    }
    public static synchronized void release(long id){
        if(id==0)return;Layer layer=layer(id);
        if(layer.references<=0)throw new IllegalStateException("Unbalanced Surface release");
        layer.references--;collect(layer);
    }
    private static void collect(Layer layer){if(layer.removed&&layer.references==0&&layer.locked==null){if(layer.bitmap!=null)layer.bitmap.recycle();if(layer.hardwareSurface!=0){syncHardware(layer);SdWindowHost.nativeHardwareRelease(layer.hardwareSurface);layer.hardwareSurface=0;}layers.remove(layer.id);}}
    public static synchronized void remove(long id){Layer layer=layers.get(id);if(layer==null)return;layer.removed=true;layer.visible=false;collect(layer);requestCompose();}
    public static synchronized void saveSnapshot(String filename)throws java.io.IOException {
        if(scene==null){scene=Bitmap.createBitmap(SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT,Bitmap.Config.ARGB_8888);scene.setDensity(0);compositor=new Canvas(scene);compositeToScene();}
        try(java.io.FileOutputStream output=new java.io.FileOutputStream(filename)){
            if(!scene.compress(Bitmap.CompressFormat.PNG,100,output))throw new java.io.IOException("PNG encoding failed");
        }
    }
    private static android.os.Handler queue(){
        if(queue==null){
            android.os.Looper looper=android.os.Looper.getMainLooper();
            queue=new android.os.Handler(looper!=null?looper:android.os.Looper.myLooper());
        }
        return queue;
    }
    /** Called from the display frame callback (SdDisplayFrames.onFrame). */
    public static void onVsync(){
        if(!composeOnVsync)return;
        queue().post(composeFromVsync);
    }
    private static void scheduleRecovery(){
        if(recoveryScheduled)return;
        recoveryScheduled=true;
        queue().postDelayed(recoverFrame,COMPOSE_FALLBACK_MS);
    }
    private static final Runnable recoverFrame=new Runnable(){
        public void run(){
            recoveryScheduled=false;
            forceStaging=true;
            try{compose();}catch(Throwable failed){/* the window must survive this */}
            finally{forceStaging=false;}
            if(perfTrace)recoveries++;
        }
    };
    private static void requestCompose(){
        if(SdWindowHost.hardware())return;
        if(!composeOnVsync){compose();return;}
        composePending=true;
        if(!composeScheduled){
            composeScheduled=true;
            if(perfTrace)composeRequests++;
            queue().removeCallbacks(composeFallback);
            queue().postDelayed(composeFallback,COMPOSE_FALLBACK_MS);
            try{SdWindowHost.requestFrame();}catch(Throwable unavailable){/* no window yet */}
        }
    }
    private static void flushCompose(boolean fallback){
        synchronized(SdSurfaceStore.class){
            if(!composePending)return;
            composePending=false;composeScheduled=false;
            if(fallback&&perfTrace)composeFallbacks++;
        }
        queue().removeCallbacks(composeFallback);
        compose();
    }
    private static Layer singleFullScreenLayer(){
        if(!fastPathEnabled)return null;
        if(layers.size()!=1)return null;
        Layer layer=layers.values().iterator().next();
        if(!layer.visible||layer.removed||layer.bitmap==null)return null;
        if(layer.alpha!=1f||layer.dim!=0||layer.crop!=null)return null;
        if(!layer.matrix.isIdentity())return null;
        if(layer.frame.left!=0||layer.frame.top!=0)return null;
        if(layer.frame.width()!=SdDisplayShim.WIDTH||layer.frame.height()!=SdDisplayShim.HEIGHT)return null;
        if(layer.bitmap.getWidth()!=SdDisplayShim.WIDTH||layer.bitmap.getHeight()!=SdDisplayShim.HEIGHT)return null;
        return layer;
    }
    private static void observeLayers(Layer single){
        lastLayerCount=layers.size();
        Layer probe=single!=null?single:(layers.isEmpty()?null:layers.values().iterator().next());
        if(probe==null){lastLayerAlphaMilli=-1;lastLayerFull=-1;lastLayerIdentity=-1;return;}
        lastLayerAlphaMilli=Math.round(probe.alpha*1000);
        lastLayerFull=(probe.frame.left==0&&probe.frame.top==0&&
                       probe.frame.width()==SdDisplayShim.WIDTH&&probe.frame.height()==SdDisplayShim.HEIGHT)?1:0;
        lastLayerIdentity=probe.matrix.isIdentity()?1:0;
    }
    private static void compositeToScene(){
        long startedErase=perfTrace?System.nanoTime():0;
        scene.eraseColor(0xff101820);
        long startedDraw=perfTrace?System.nanoTime():0;
        orderedLayers.clear();orderedLayers.addAll(layers.values());java.util.Collections.sort(orderedLayers,byDepth);
        for(Layer layer:orderedLayers)if(layer.visible&&!layer.removed&&layer.bitmap!=null){
            if(layer.dim>0)compositor.drawColor(Math.round(layer.dim*255)<<24);
            int save=compositor.save();compositor.translate(layer.frame.left,layer.frame.top);compositor.concat(layer.matrix);
            if(layer.crop!=null)compositor.clipRect(layer.crop);
            layerPaint.setAlpha(Math.round(layer.alpha*255));
            compositor.drawBitmap(layer.bitmap,0,0,layerPaint);compositor.restoreToCount(save);
        }
        if(perfTrace){long finished=System.nanoTime();composeEraseNs+=startedDraw-startedErase;composeDrawNs+=finished-startedDraw;}
    }
    private static void compose(){
        if(perfTrace)composes++;
        if(pixels==null)pixels=new int[SdDisplayShim.WIDTH*SdDisplayShim.HEIGHT];
        Layer single=singleFullScreenLayer();
        if(perfTrace){observeLayers(single);fastPathFrames+=single!=null?1:0;}
        boolean sent=false;
        if(single!=null){
            /* One opaque full-screen layer with an identity transform: its pixels
               are the scene, so the erase, the blit and the compositor canvas are
               all redundant. */
            if(!forceStaging&&directCopyEnabled&&single.bitmap.getConfig()==Bitmap.Config.ARGB_8888
                    &&single.bitmap.getRowBytes()==SdDisplayShim.WIDTH*4){
                java.nio.ByteBuffer scratch=SdWindowHost.directAcquire();
                if(scratch==null){
                    directMissStreak++;
                    if(perfTrace)directMisses++;
                    /* Both buffers are still with the compositor. Once the direct path
                       has proven itself, drop this frame instead of paying the 48 ms
                       getPixels staging copy; three misses in a row fall back so a
                       stuck buffer release cannot freeze the window. */
                    if(directActive&&directMissStreak<4){sent=true;if(perfTrace)directDrops++;scheduleRecovery();}
                }else{
                    directMissStreak=0;
                    long startedCopy=perfTrace?System.nanoTime():0;
                    scratch.clear();
                    single.bitmap.copyPixelsToBuffer(scratch);
                    long copied=perfTrace?System.nanoTime():0;
                    if(SdWindowHost.directCommit()){
                        if(perfTrace){composePixelsNs+=copied-startedCopy;composePresentNs+=System.nanoTime()-copied;directCopies++;}
                        directActive=true;
                        sent=true;
                    }
                }
            }
            if(!sent){
                long startedPixels=perfTrace?System.nanoTime():0;
                single.bitmap.getPixels(pixels,0,SdDisplayShim.WIDTH,0,0,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT);
                long startedPresent=perfTrace?System.nanoTime():0;
                SdWindowHost.present(pixels);
                if(perfTrace){long finished=System.nanoTime();composePixelsNs+=startedPresent-startedPixels;composePresentNs+=finished-startedPresent;}
            }
        }else{
            if(scene==null){scene=Bitmap.createBitmap(SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT,Bitmap.Config.ARGB_8888);scene.setDensity(0);compositor=new Canvas(scene);}
            compositeToScene();
            long startedPixels=perfTrace?System.nanoTime():0;
            scene.getPixels(pixels,0,SdDisplayShim.WIDTH,0,0,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT);
            long startedPresent=perfTrace?System.nanoTime():0;
            SdWindowHost.present(pixels);
            if(perfTrace){long finished=System.nanoTime();composePixelsNs+=startedPresent-startedPixels;composePresentNs+=finished-startedPresent;}
        }
        if(++composedFrames==1||traceFrames)System.err.println("SDSURFACE=buffer_committed|layers="+layers.size()+"|frame="+composedFrames);
    }
}
