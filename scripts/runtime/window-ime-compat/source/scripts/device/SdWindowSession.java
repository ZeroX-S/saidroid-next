import android.content.res.Configuration;
import android.graphics.Rect;
import android.graphics.Region;
import android.os.Binder;
import android.os.IBinder;
import android.os.Looper;
import android.view.Gravity;
import android.view.IWindow;
import android.view.IWindowId;
import android.view.IWindowFocusObserver;
import android.view.IWindowSession;
import android.view.InputChannel;
import android.view.InputDevice;
import android.view.InputEventSender;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.View;
import android.view.WindowManager;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.LinkedHashMap;

/** Local windows own native GPU surfaces (or software diagnostic buffers) and kernel InputChannels. */
public final class SdWindowSession implements InvocationHandler {
    private static final SdWindowSession instance=new SdWindowSession();
    private final Binder binder=new Binder();
    private final IWindowSession service;
    private final LinkedHashMap<IBinder,Window> windows=new LinkedHashMap<IBinder,Window>();
    private volatile boolean touchMode=true;
    private boolean focused,everFocused;
    private boolean everVisible;
    private Window gesture;
    private long downTime;
    private int sequence;
    private int windowOrder;
    private int keyboardHeight;
    private final LinkedHashMap<Integer,Touch> touches=new LinkedHashMap<Integer,Touch>();
    private static final boolean traceInput=Boolean.getBoolean("saidroid.diagnostics.input")||System.getenv("SAILDROID_TRACE_INPUT")!=null;
    /* 环境变量门控（sdtool --env 能直接给）：触摸从 native 进来之后，Java 这一层
       在哪一步被丢掉，必须能一眼看出来——是没找到目标窗口、还是 InputChannel 拒收。
       系统属性走不通（launcher 不转发 -D），所以这里用 getenv。 */
    private static final boolean diagInput=System.getenv("SAILDROID_DIAG_INPUT")!=null;
    private static boolean diagDumped;
    private static final class Touch { final int pointerId;float x,y;Touch(int id,float x,float y){pointerId=id;this.x=x;this.y=y;} }
    private static final class Window {
        final IWindow client;
        final WindowManager.LayoutParams attributes=new WindowManager.LayoutParams();
        final Rect frame=new Rect(),contentInsets=new Rect(),visibleInsets=new Rect();
        final Region transparent=new Region(),touchable=new Region();
        final ArrayList<Rect> gestureExclusion=new ArrayList<Rect>();
        final ArrayList<IWindowFocusObserver> observers=new ArrayList<IWindowFocusObserver>();
        long surface;
        InputChannel channel;
        InputEventSender sender;
        IWindowId id;
        int visibility;
        int order;
        boolean drawn;
        boolean hasFocus;
        Window(IWindow client){this.client=client;}
    }
    private SdWindowSession(){service=(IWindowSession)Proxy.newProxyInstance(IWindowSession.class.getClassLoader(),new Class<?>[]{IWindowSession.class},this);binder.attachInterface(service,"android.view.IWindowSession");}
    public static IWindowSession service(){return instance.service;}
    /** One actual touch-mode state is shared by WindowManager and all local
     * window sessions; the host compositor remains outside this process scope. */
    public static void setInTouchMode(final boolean value){
        if(instance.touchMode==value)return;
        instance.touchMode=value;
        new android.os.Handler(Looper.getMainLooper()).post(new Runnable(){public void run(){
            try{for(Window window:instance.windows.values())window.client.windowFocusChanged(window.hasFocus,instance.touchMode);}
            catch(android.os.RemoteException failure){throw new IllegalStateException("Touch mode window notification failed",failure);}
        }});
    }
    /** Crash-time diagnostics: the client side of every registered window, in attach order. */
    static Object[] windowClients(){synchronized(instance.windows){Object[] clients=new Object[instance.windows.size()];int index=0;for(Window window:instance.windows.values())clients[index++]=window.client;return clients;}}
    private Window window(Object client){Window result=windows.get(((IWindow)client).asBinder());if(result==null)throw new IllegalArgumentException("Unregistered window");return result;}
    private int add(Object[] args,boolean display,boolean input)throws Exception{
        IWindow client=(IWindow)args[0];if(windows.containsKey(client.asBinder()))throw new IllegalStateException("Window already added");
        Window w=new Window(client);w.attributes.copyFrom((WindowManager.LayoutParams)args[2]);w.visibility=(Integer)args[3];
        if(display&&(Integer)args[4]!=SdDisplayShim.DISPLAY_ID)throw new IllegalArgumentException("Unknown display");
        w.surface=SdSurfaceStore.create();w.order=++windowOrder;
        for(Object argument:args)if(argument instanceof Rect)((Rect)argument).setEmpty();
        // ViewRoot measures WRAP_CONTENT against this initial display frame.
        // An empty frame constrains the first dialog measurement to one pixel.
        for(Object argument:args)if(argument instanceof Rect){((Rect)argument).set(0,0,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT);break;}
        for(Object argument:args){
            if(argument instanceof android.view.DisplayCutout.ParcelableWrapper)((android.view.DisplayCutout.ParcelableWrapper)argument).set(android.view.DisplayCutout.NO_CUTOUT);
            if(argument instanceof android.view.InsetsState)((android.view.InsetsState)argument).set(imeState());
        }
        if(input){
            InputChannel[] pair=InputChannel.openInputChannelPair("SailDroid:"+w.attributes.getTitle());
            /* 哪一端给 InputEventSender、哪一端 transfer 给应用，决定了事件到底流向谁。
               正常应是 pair[0] 留作 publisher、pair[1] 交给 ViewRootImpl；SAILDROID_INPUT_SWAP
               只是把两端调换的对照实验开关（默认关）。 */
            boolean swap=System.getenv("SAILDROID_INPUT_SWAP")!=null;
            InputChannel mine=swap?pair[1]:pair[0];InputChannel theirs=swap?pair[0]:pair[1];
            w.channel=mine;w.sender=new InputEventSender(w.channel,Looper.myLooper()){
                @Override public void onInputEventFinished(int seq,boolean handled){if(traceInput||diagInput)System.err.println("SDINPUT=finished|sequence="+seq+"|handled="+handled);}
            };
            InputChannel destination=null;for(Object arg:args)if(arg instanceof InputChannel)destination=(InputChannel)arg;
            if(destination==null)throw new IllegalArgumentException("InputChannel output required");theirs.transferTo(destination);
        }
        w.id=createId(w);windows.put(client.asBinder(),w);updateLayers();
        updateFocus();
        System.err.println("SDWINDOW_SESSION=added|title="+w.attributes.getTitle());
        return 2|(touchMode?1:0); // ADD_FLAG_APP_VISIBLE and actual touch-mode state.
    }
    private IWindowId createId(final Window window){
        final Binder token=new Binder();
        IWindowId result=(IWindowId)Proxy.newProxyInstance(IWindowId.class.getClassLoader(),new Class<?>[]{IWindowId.class},new InvocationHandler(){
            @Override public Object invoke(Object p,Method m,Object[] a){
                if(m.getName().equals("asBinder"))return token;
                if(m.getName().equals("isFocused"))return instance.focused&&top()==window;
                if(m.getName().equals("registerFocusObserver")){window.observers.add((IWindowFocusObserver)a[0]);return null;}
                if(m.getName().equals("unregisterFocusObserver")){window.observers.remove(a[0]);return null;}
                throw new UnsupportedOperationException(m.toString());
            }
        });token.attachInterface(result,"android.view.IWindowId");return result;
    }
    private int layerType(Window w){
        switch(w.attributes.type){
            case WindowManager.LayoutParams.TYPE_APPLICATION_MEDIA:return 0;
            case WindowManager.LayoutParams.TYPE_APPLICATION_MEDIA_OVERLAY:return 1;
            case WindowManager.LayoutParams.TYPE_BASE_APPLICATION:return 2;
            case WindowManager.LayoutParams.TYPE_APPLICATION:return 3;
            default:return 4;
        }
    }
    private ArrayList<Window> orderedWindows(){
        ArrayList<Window> ordered=new ArrayList<Window>(windows.values());
        java.util.Collections.sort(ordered,new java.util.Comparator<Window>(){public int compare(Window a,Window b){int type=Integer.compare(layerType(a),layerType(b));return type!=0?type:Integer.compare(a.order,b.order);}});
        return ordered;
    }
    private void updateLayers(){int z=0;for(Window w:orderedWindows())SdSurfaceStore.z(w.surface,z++);}
    private Window top(){Window result=null;for(Window w:orderedWindows())if(w.visibility==View.VISIBLE&&(w.attributes.flags&WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)==0)result=w;return result;}
    private void updateFocus()throws android.os.RemoteException{
        Window selected=top();
        for(Window w:windows.values()){
            boolean active=focused&&w==selected;if(w.hasFocus==active)continue;w.hasFocus=active;w.client.windowFocusChanged(active,touchMode);
            System.err.println("SDWINDOW_SESSION=focus|active="+active+"|title="+w.attributes.getTitle());
            for(IWindowFocusObserver observer:w.observers){if(active)observer.focusGained(w.id.asBinder());else observer.focusLost(w.id.asBinder());}
        }
    }
    private int relayout(Object[] a)throws Exception{
        Window w=window(a[0]);if(a[2]!=null)w.attributes.copyFrom((WindowManager.LayoutParams)a[2]);w.visibility=(Integer)a[5];
        int requestedW=(Integer)a[3],requestedH=(Integer)a[4];
        int width=w.attributes.width==WindowManager.LayoutParams.MATCH_PARENT?SdDisplayShim.WIDTH:Math.max(1,Math.min(SdDisplayShim.WIDTH,requestedW));
        int height=w.attributes.height==WindowManager.LayoutParams.MATCH_PARENT?SdDisplayShim.HEIGHT:Math.max(1,Math.min(SdDisplayShim.HEIGHT,requestedH));
        Gravity.apply(w.attributes.gravity==0?Gravity.TOP|Gravity.LEFT:w.attributes.gravity,width,height,new Rect(0,0,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT),w.attributes.x,w.attributes.y,w.frame);
        ((Rect)a[8]).set(w.frame);for(int i=9;i<=14;i++)((Rect)a[i]).setEmpty();
        if((w.attributes.softInputMode&WindowManager.LayoutParams.SOFT_INPUT_MASK_ADJUST)==WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)((Rect)a[10]).bottom=imeOverlap(w);
        ((Rect)a[11]).bottom=imeOverlap(w);
        ((android.view.DisplayCutout.ParcelableWrapper)a[15]).set(android.view.DisplayCutout.NO_CUTOUT);
        android.content.res.Configuration config=android.app.ActivityThread.currentApplication().getResources().getConfiguration();
        ((android.util.MergedConfiguration)a[16]).setConfiguration(config,new Configuration());
        ((android.view.InsetsState)a[18]).set(imeState());
        // DecorView draws its shadow padding inside the producer buffer. The
        // window frame and input coordinates exclude these surface insets.
        Rect bufferFrame=new Rect(w.frame);
        bufferFrame.left-=w.attributes.surfaceInsets.left;bufferFrame.top-=w.attributes.surfaceInsets.top;
        bufferFrame.right+=w.attributes.surfaceInsets.right;bufferFrame.bottom+=w.attributes.surfaceInsets.bottom;
        SdSurfaceStore.layout(w.surface,bufferFrame,w.visibility==View.VISIBLE);
        SdSurfaceStore.dim(w.surface,(w.attributes.flags&WindowManager.LayoutParams.FLAG_DIM_BEHIND)!=0?w.attributes.dimAmount:0);
        SdSurfaceStore.attachControl((android.view.SurfaceControl)a[17],w.surface,bufferFrame.width(),bufferFrame.height());
        // Activity windows are commonly added GONE and become VISIBLE only
        // during relayout. Deliver focus after that visibility transition.
        updateFocus();
        return 2|4|(touchMode?1:0); // Newly supplied local surface and valid layout.
    }
    @Override public Object invoke(Object p,Method m,Object[] a)throws Throwable{
        String n=m.getName();if(n.equals("asBinder"))return binder;
        if(n.equals("toString"))return "SailDroid local WindowSession";
        if(n.equals("hashCode"))return System.identityHashCode(p);if(n.equals("equals"))return p==a[0];
        if(n.equals("addToDisplay"))return add(a,true,true);
        if(n.equals("add"))return add(a,false,true);
        if(n.equals("addToDisplayWithoutInputChannel"))return add(a,true,false);
        if(n.equals("addWithoutInputChannel"))return add(a,false,false);
        if(n.equals("relayout"))return relayout(a);
        if(n.equals("remove")){
            Window w=window(a[0]);if(gesture==w)deliver(MotionEvent.ACTION_CANCEL,0,0,0,System.nanoTime());windows.remove(w.client.asBinder());if(w.sender!=null)w.sender.dispose();if(w.channel!=null)w.channel.dispose();SdSurfaceStore.remove(w.surface);updateLayers();updateFocus();return null;
        }
        if(n.equals("getInTouchMode"))return touchMode;
        if(n.equals("setInTouchMode")){setInTouchMode((Boolean)a[0]);return null;}
        if(n.equals("getDisplayFrame")){window(a[0]);((Rect)a[1]).set(0,0,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT);return null;}
        if(n.equals("finishDrawing")){Window w=window(a[0]);w.drawn=true;System.err.println("SDWINDOW_SESSION=drawn|title="+w.attributes.getTitle());return null;}
        if(n.equals("setTransparentRegion")){window(a[0]).transparent.set((Region)a[1]);return null;}
        if(n.equals("setInsets")){Window w=window(a[0]);w.contentInsets.set((Rect)a[2]);w.visibleInsets.set((Rect)a[3]);w.touchable.set((Region)a[4]);return null;}
        if(n.equals("getWindowId")){Window w=windows.get((IBinder)a[0]);if(w==null)throw new IllegalArgumentException("Unknown window token");return w.id;}
        if(n.equals("outOfMemory")){window(a[0]);return false;}
        if(n.equals("performHapticFeedback")){window(a[0]);return false; /* No host vibrator backend advertised. */}
        if(n.equals("performDeferredDestroy")){Window w=window(a[0]);if(w.visibility!=View.VISIBLE)SdSurfaceStore.layout(w.surface,w.frame,false);return null;}
        if(n.equals("onRectangleOnScreenRequested")){if(!windows.containsKey((IBinder)a[0]))throw new IllegalArgumentException("Unknown window token");return null; /* Entire Android display is inside this one host window. */}
        if(n.equals("reportSystemGestureExclusionChanged")){
            Window w=window(a[0]);ArrayList<Rect> copied=new ArrayList<Rect>();
            if(a[1]==null)throw new IllegalArgumentException("Gesture exclusion rectangles required");
            for(Object value:(java.util.List<?>)a[1]){
                if(!(value instanceof Rect))throw new IllegalArgumentException("Invalid gesture exclusion rectangle");
                copied.add(new Rect((Rect)value));
            }
            w.gestureExclusion.clear();w.gestureExclusion.addAll(copied);
            // App-local requests are accepted, but Sailfish compositor edge
            // gestures are outside this window/session and remain authoritative.
            System.err.println("SDWINDOW_SESSION=gesture_exclusion|requested="+copied.size()+"|host_applied=0|title="+w.attributes.getTitle());
            return null;
        }
        throw SdRuntimeDiagnostics.unsupported("Local WindowSession",m);
    }
    private int imeOverlap(Window w){
        return Math.max(0,Math.min(w.frame.height(),w.frame.bottom-(SdDisplayShim.HEIGHT-keyboardHeight)));
    }
    private android.view.InsetsState imeState(){
        android.view.InsetsState state=new android.view.InsetsState();state.setDisplayFrame(new Rect(0,0,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT));
        android.view.InsetsSource ime=state.getSource(android.view.InsetsState.TYPE_IME);ime.setFrame(new Rect(0,SdDisplayShim.HEIGHT-keyboardHeight,SdDisplayShim.WIDTH,SdDisplayShim.HEIGHT));ime.setVisible(keyboardHeight>0);return state;
    }
    public static void imeHeight(int height)throws android.os.RemoteException{
        if(instance.keyboardHeight==height)return;instance.keyboardHeight=height;
        for(Window w:instance.windows.values()){
            w.client.insetsChanged(instance.imeState());
            // API29 defaults to legacy insets. InsetsState alone does not update
            // ViewRoot's pending content/visible insets or trigger its resize.
            int overlap=instance.imeOverlap(w);
            boolean resize=(w.attributes.softInputMode&WindowManager.LayoutParams.SOFT_INPUT_MASK_ADJUST)==WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE;
            Rect content=new Rect(0,0,0,resize?overlap:0),visible=new Rect(0,0,0,overlap);
            Configuration config=android.app.ActivityThread.currentApplication().getResources().getConfiguration();
            w.client.resized(new Rect(w.frame),new Rect(),content,visible,new Rect(),new Rect(),false,
                    new android.util.MergedConfiguration(config,new Configuration()),new Rect(w.frame),true,false,
                    SdDisplayShim.DISPLAY_ID,new android.view.DisplayCutout.ParcelableWrapper(android.view.DisplayCutout.NO_CUTOUT));
            System.err.println("SDWINDOW_SESSION=ime_resize|keyboard="+height+"|overlap="+overlap+"|adjust_resize="+resize+"|title="+w.attributes.getTitle());
        }
    }
    public static void visibility(int value){
        boolean visible=value!=0&&value!=3;
        if(visible)instance.everVisible=true;
        if((visible&&!instance.everFocused)||(!visible&&instance.everVisible))SdActivityHost.hostVisibility(visible);
        System.err.println("SDWINDOW=visibility|state="+value);
    }
    public static void focus(boolean active){
        if(instance.focused==active)return;
        if(!active)instance.deliver(MotionEvent.ACTION_CANCEL,0,0,0,System.nanoTime());
        instance.focused=active;
        if(active)instance.everFocused=true;
        SdInputMethods.hostFocus(active);
        // An initial inactive configure precedes mapping. Complete the first
        // draw before interpreting a later deactivation as backgrounding.
        if(active||instance.everFocused)SdActivityHost.hostVisibility(active);
        try{instance.updateFocus();}
        catch(android.os.RemoteException failure){throw new IllegalStateException(failure);}
    }
    public static void input(int action,int id,float x,float y,long timestamp){instance.deliver(action,id,x,y,timestamp);}
    private void deliver(int action,int id,float x,float y,long timestamp){
        long time=timestamp/1000000;
        if(diagInput)System.err.println("SDINPUT=deliver|action="+action+"|id="+id+"|x="+x+"|y="+y+"|windows="+windows.size()+"|touches="+touches.size());
        /* 第一次按下时把目标窗口的坐标系和整棵 View 树打出来：坐标到底是"送错了地方"
           还是"送对了但没人接"，只能看真实 bounds 才能判定，不猜。 */
        if(diagInput&&action==MotionEvent.ACTION_DOWN&&(!diagDumped||System.getenv("SAILDROID_TRACE_VIEWS")!=null)){diagDumped=true;Window target=top();if(target!=null)System.err.println("SDINPUT=window|frame="+target.frame+"|layout="+target.attributes.width+"x"+target.attributes.height+"|vis="+target.visibility+"|flags="+target.attributes.flags+"|order="+target.order+"|surface="+target.surface+"|title="+target.attributes.getTitle());try{SdViewDump.dump();}catch(Throwable ignored){}}
        if(action==MotionEvent.ACTION_DOWN){
            if(touches.isEmpty()){gesture=top();if(gesture==null||gesture.sender==null){if(diagInput)System.err.println("SDINPUT=drop_no_window|gestureNull="+(gesture==null)+"|senderNull="+(gesture!=null&&gesture.sender==null)+"|windows="+windows.size());return;}downTime=time;}
            if(touches.containsKey(id))return;
            int pointerId=0;boolean used;
            do{used=false;for(Touch point:touches.values())if(point.pointerId==pointerId){used=true;pointerId++;break;}}while(used);
            if(pointerId>=32)return;
            touches.put(id,new Touch(pointerId,x,y));
        }else if(action==MotionEvent.ACTION_MOVE){
            Touch point=touches.get(id);if(point==null)return;point.x=x;point.y=y;
        }else if(action==MotionEvent.ACTION_UP&&!touches.containsKey(id))return;
        if(gesture==null||gesture.sender==null||touches.isEmpty()){
            if(diagInput)System.err.println("SDINPUT=drop_mid|gestureNull="+(gesture==null)+"|touches="+touches.size());
            if(action==MotionEvent.ACTION_UP)touches.remove(id);if(action==MotionEvent.ACTION_CANCEL)touches.clear();return;
        }
        if(traceInput)System.err.println("SDINPUT=wayland|action="+action+"|id="+id+"|x="+x+"|y="+y);
        int index=0,changed=0;MotionEvent.PointerProperties[] properties=new MotionEvent.PointerProperties[touches.size()];MotionEvent.PointerCoords[] coordinates=new MotionEvent.PointerCoords[touches.size()];
        for(java.util.Map.Entry<Integer,Touch> item:touches.entrySet()){
            Touch point=item.getValue();if(item.getKey()==id)changed=index;
            MotionEvent.PointerProperties property=new MotionEvent.PointerProperties();property.id=point.pointerId;property.toolType=MotionEvent.TOOL_TYPE_FINGER;properties[index]=property;
            MotionEvent.PointerCoords coordinate=new MotionEvent.PointerCoords();coordinate.x=point.x-gesture.frame.left;coordinate.y=point.y-gesture.frame.top;coordinate.pressure=action==MotionEvent.ACTION_CANCEL||(action==MotionEvent.ACTION_UP&&item.getKey()==id)?0:1;coordinate.size=1;coordinates[index]=coordinate;index++;
        }
        int eventAction=action;if(touches.size()>1&&(action==MotionEvent.ACTION_DOWN||action==MotionEvent.ACTION_UP))eventAction=(action==MotionEvent.ACTION_DOWN?MotionEvent.ACTION_POINTER_DOWN:MotionEvent.ACTION_POINTER_UP)|(changed<<MotionEvent.ACTION_POINTER_INDEX_SHIFT);
        MotionEvent event=MotionEvent.obtain(downTime,time,eventAction,touches.size(),properties,coordinates,0,0,1,1,0,0,InputDevice.SOURCE_TOUCHSCREEN,0);
        try{boolean accepted=gesture.sender.sendInputEvent(++sequence,event);if(diagInput)System.err.println("SDINPUT=sent|sequence="+sequence+"|accepted="+accepted+"|action="+eventAction);if(!accepted&&action!=MotionEvent.ACTION_CANCEL)throw new IllegalStateException("InputChannel rejected touch event");}finally{event.recycle();}
        if(action==MotionEvent.ACTION_UP)touches.remove(id);if(action==MotionEvent.ACTION_CANCEL)touches.clear();if(touches.isEmpty())gesture=null;
    }
}
