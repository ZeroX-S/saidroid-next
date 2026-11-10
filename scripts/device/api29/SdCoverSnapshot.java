import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.HardwareRenderer;
import android.graphics.Paint;
import android.graphics.RecordingCanvas;
import android.graphics.Rect;
import android.graphics.RenderNode;
import android.os.Looper;
import android.view.View;
import android.view.WindowManager;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;

/** One app-owned HWUI render-tree snapshot per foreground-to-background event.
 * Nothing runs on the steady-state draw path and no screen/compositor is read. */
final class SdCoverSnapshot {
    static final class Frame {
        final int[] pixels;
        final int width,height;
        Frame(int[] p,int w,int h){pixels=p;width=w;height=h;}
    }
    private static final class Layer {
        final View view;
        final WindowManager.LayoutParams attributes;
        final Rect frame;
        final int order;
        Layer(View v,WindowManager.LayoutParams p,Rect r,int o){view=v;attributes=p;frame=r;order=o;}
    }
    private static Field field(Class<?> type,String name)throws NoSuchFieldException{
        for(Class<?> c=type;c!=null;c=c.getSuperclass())try{Field f=c.getDeclaredField(name);f.setAccessible(true);return f;}catch(NoSuchFieldException ignored){}
        throw new NoSuchFieldException(name);
    }
    private static Object root(Object client)throws ReflectiveOperationException{
        Object holder=field(client.getClass(),"mViewAncestor").get(client);
        return holder instanceof java.lang.ref.WeakReference?((java.lang.ref.WeakReference<?>)holder).get():holder;
    }
    static Frame capture(){
        if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("Cover capture requires the UI thread");
        long started=android.os.SystemClock.uptimeMillis();
        Bitmap hardware=null,cpu=null;RenderNode composition=null;
        try{
            ArrayList<Layer> layers=new ArrayList<Layer>();
            for(Object client:SdWindowSession.windowClients()){
                Object root=root(client);if(root==null)continue;
                View view=(View)field(root.getClass(),"mView").get(root);
                if(view==null||view.getVisibility()!=View.VISIBLE||view.getWidth()<1||view.getHeight()<1)continue;
                WindowManager.LayoutParams attributes=(WindowManager.LayoutParams)field(root.getClass(),"mWindowAttributes").get(root);
                if((attributes.flags&WindowManager.LayoutParams.FLAG_SECURE)!=0){System.err.println("SDCOVER=skipped|reason=secure-window");return null;}
                Rect frame=new Rect((Rect)field(root.getClass(),"mWinFrame").get(root));
                layers.add(new Layer(view,attributes,frame,layers.size()));
            }
            if(layers.isEmpty())return null;
            Collections.sort(layers,new Comparator<Layer>(){public int compare(Layer a,Layer b){int type=Integer.compare(a.attributes.type,b.attributes.type);return type!=0?type:Integer.compare(a.order,b.order);}});
            final int width=540,height=Math.max(1,Math.round(SdDisplayShim.HEIGHT*(540f/SdDisplayShim.WIDTH)));
            composition=new RenderNode("SailDroid background cover");composition.setPosition(0,0,width,height);
            RecordingCanvas canvas=composition.beginRecording(width,height);
            try{
                canvas.drawColor(0xff101820);canvas.scale(width/(float)SdDisplayShim.WIDTH,height/(float)SdDisplayShim.HEIGHT);
                Paint dim=new Paint();dim.setColor(Color.BLACK);
                for(Layer layer:layers){
                    if((layer.attributes.flags&WindowManager.LayoutParams.FLAG_DIM_BEHIND)!=0){dim.setAlpha(Math.round(255*layer.attributes.dimAmount));canvas.drawRect(0,0,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT,dim);}
                    canvas.save();canvas.translate(layer.frame.left-layer.attributes.surfaceInsets.left,layer.frame.top-layer.attributes.surfaceInsets.top);
                    canvas.drawRenderNode(layer.view.updateDisplayListIfDirty());canvas.restore();
                }
            }finally{composition.endRecording();}
            hardware=HardwareRenderer.createHardwareBitmap(composition,width,height);
            if(hardware==null)throw new IllegalStateException("HWUI snapshot returned no bitmap");
            cpu=hardware.copy(Bitmap.Config.ARGB_8888,false);if(cpu==null)throw new IllegalStateException("HWUI snapshot readback failed");
            int[] pixels=new int[width*height];cpu.getPixels(pixels,0,width,0,0,width,height);
            System.err.println("SDCOVER=snapshot|source=hwui-rendernode|width="+width+"|height="+height+"|windows="+layers.size()+"|elapsed_ms="+(android.os.SystemClock.uptimeMillis()-started));
            return new Frame(pixels,width,height);
        }catch(ReflectiveOperationException|RuntimeException failure){
            System.err.println("SDCOVER=failed|type="+failure.getClass().getName()+"|reason="+failure.getMessage());return null;
        }finally{
            if(cpu!=null)cpu.recycle();if(hardware!=null)hardware.recycle();if(composition!=null)composition.discardDisplayList();
        }
    }
    private SdCoverSnapshot(){}
}
