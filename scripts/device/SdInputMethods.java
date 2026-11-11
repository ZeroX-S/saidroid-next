import android.os.*;
import android.os.Process;
import android.graphics.Rect;
import android.graphics.Color;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.view.*;
import android.view.inputmethod.*;
import android.text.InputType;
import com.android.internal.view.*;
import java.lang.reflect.*;
import java.util.*;

/** Real Android InputConnection sessions backed by the existing Sailfish IME. */
public final class SdInputMethods implements InvocationHandler,SdMaliit.Listener {
    private static final String ID="org.saildroid.runtime/.Maliit";
    private static final SdInputMethods instance=new SdInputMethods();
    private final Binder binder=new Binder();private final IInputMethodManager service;
    private final IdentityHashMap<IBinder,Client> clients=new IdentityHashMap<IBinder,Client>();
    private Client focused;private long generation;private int sequence,extractSequence,keyboardHeight;
    private boolean hostActive=true;
    private FrameLayout dismissRoot;private TextView dismissButton;private Client dismissClient;
    private final View.OnLayoutChangeListener dismissLayout=new View.OnLayoutChangeListener(){
        public void onLayoutChange(View v,int l,int t,int r,int b,int ol,int ot,int or,int ob){positionDismiss();}
    };
    private void positionDismiss(){
        if(dismissRoot==null||dismissButton==null)return;
        float density=dismissRoot.getResources().getDisplayMetrics().density;
        Rect visible=new Rect();dismissRoot.getWindowVisibleDisplayFrame(visible);int[] origin=new int[2];dismissRoot.getLocationOnScreen(origin);
        int bottom=Math.min(dismissRoot.getHeight(),Math.min(visible.bottom,SdDisplayShim.HEIGHT-keyboardHeight)-origin[1]);
        int height=Math.round(44*density),width=Math.round(80*density),gap=Math.round(8*density);
        FrameLayout.LayoutParams lp=new FrameLayout.LayoutParams(width,height);lp.gravity=Gravity.TOP|Gravity.LEFT;
        lp.leftMargin=Math.max(0,dismissRoot.getWidth()-width-gap);lp.topMargin=Math.max(0,bottom-height-Math.round(104*density));
        FrameLayout.LayoutParams old=(FrameLayout.LayoutParams)dismissButton.getLayoutParams();
        if(old==null||old.width!=lp.width||old.height!=lp.height||old.leftMargin!=lp.leftMargin||old.topMargin!=lp.topMargin)dismissButton.setLayoutParams(lp);
    }
    private void removeDismiss(){
        if(dismissRoot!=null){dismissRoot.removeOnLayoutChangeListener(dismissLayout);if(dismissButton!=null)dismissRoot.removeView(dismissButton);}
        dismissRoot=null;dismissButton=null;dismissClient=null;
    }
    private void syncDismiss(){
        final Client c=focused;
        View root=c==null?null:WindowManagerGlobal.getInstance().getWindowView(c.window);
        if(!hostActive||keyboardHeight==0||c==null||c.editor==null||!(root instanceof FrameLayout)){removeDismiss();return;}
        if(dismissRoot!=root||dismissClient!=c){
            removeDismiss();dismissClient=c;dismissRoot=(FrameLayout)root;dismissButton=new TextView(root.getContext());
            dismissButton.setText("收起 ⌄");dismissButton.setContentDescription("收起键盘");dismissButton.setTextColor(Color.WHITE);dismissButton.setTextSize(14);dismissButton.setGravity(Gravity.CENTER);dismissButton.setBackgroundColor(0xe630343b);
            dismissButton.setFocusable(false);dismissButton.setClickable(true);dismissButton.setElevation(16*root.getResources().getDisplayMetrics().density);
            dismissButton.setOnClickListener(new View.OnClickListener(){public void onClick(View view){
                if(focused==c&&keyboardHeight>0&&hostActive){show(c,false,null);System.err.println("SDIME=dismiss_button_handled|source=touch|wants_show=false");}
            }});
            dismissRoot.addView(dismissButton);dismissRoot.addOnLayoutChangeListener(dismissLayout);
            System.err.println("SDIME=dismiss_button_visible|window=focused-editor");
        }
        positionDismiss();
    }
    private static final class Client {
        final IInputMethodClient callback;IInputContext context;EditorInfo editor;IBinder window;IInputMethodSession session;
        long generation;int sequence,start,end,offset,composingStart=-1;String surrounding="",language;
        boolean wantsShow,correction,bound;ResultReceiver receiver;Rect cursor;CompletionInfo[] completions;String privateAction;
        Client(IInputMethodClient callback,IInputContext context){this.callback=callback;this.context=context;}
    }
    private SdInputMethods(){service=(IInputMethodManager)Proxy.newProxyInstance(IInputMethodManager.class.getClassLoader(),new Class<?>[]{IInputMethodManager.class},this);binder.attachInterface(service,"com.android.internal.view.IInputMethodManager");}
    public static IBinder binder(){return instance.binder;}public static IInputMethodManager service(){return instance.service;}
    public static void registerClient(IInputMethodClient callback,IInputContext context){
        Client c=new Client(callback,context);c.session=instance.session(c);
        instance.clients.put(callback.asBinder(),c);
    }
    public static void requestShow(){ Client c=instance.focused; if(c!=null&&c.editor!=null)instance.show(c,true,null); }
    private Client client(Object object){Client c=clients.get(((IInputMethodClient)object).asBinder());if(c==null)throw new IllegalArgumentException("Input client was not registered");return c;}
    private boolean hidden(Client c){int type=c.editor.inputType,variation=type&InputType.TYPE_MASK_VARIATION;return(type&InputType.TYPE_MASK_CLASS)==InputType.TYPE_CLASS_NUMBER?variation==InputType.TYPE_NUMBER_VARIATION_PASSWORD:variation==InputType.TYPE_TEXT_VARIATION_PASSWORD||variation==InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD||variation==InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD;}
    private InputBindResult result(Client c){return new InputBindResult(SdMaliit.connected()?InputBindResult.ResultCode.SUCCESS_WITH_IME_SESSION:InputBindResult.ResultCode.SUCCESS_WAITING_IME_BINDING,SdMaliit.connected()?c.session:null,null,ID,c.sequence,0);}
    private void widget(Client c,boolean changed){
        if(c!=focused||c.editor==null)return;int input=c.editor.inputType,kind=input&InputType.TYPE_MASK_CLASS,variation=input&InputType.TYPE_MASK_VARIATION;
        int content=kind==InputType.TYPE_CLASS_PHONE?2:kind==InputType.TYPE_CLASS_NUMBER?1:variation==InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS||variation==InputType.TYPE_TEXT_VARIATION_WEB_EMAIL_ADDRESS?3:variation==InputType.TYPE_TEXT_VARIATION_URI?4:0;
        int action=c.editor.imeOptions&EditorInfo.IME_MASK_ACTION;int enter=action==EditorInfo.IME_ACTION_GO?3:action==EditorInfo.IME_ACTION_SEARCH?5:action==EditorInfo.IME_ACTION_SEND?4:action==EditorInfo.IME_ACTION_NEXT?6:action==EditorInfo.IME_ACTION_DONE?2:action==EditorInfo.IME_ACTION_PREVIOUS?7:action==EditorInfo.IME_ACTION_NONE?1:0;
        boolean secret=hidden(c);boolean prediction=!secret&&(input&InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS)==0;
        SdMaliit.widget(c.generation,hostActive,changed,content,secret,prediction,(input&(InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS|InputType.TYPE_TEXT_FLAG_CAP_WORDS|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES))!=0,c.surrounding,c.start-c.offset,c.end-c.offset,enter);
    }
    private IInputMethodSession session(final Client c){
        final Binder token=new Binder();IInputMethodSession proxy=(IInputMethodSession)Proxy.newProxyInstance(IInputMethodSession.class.getClassLoader(),new Class<?>[]{IInputMethodSession.class},new InvocationHandler(){
            public Object invoke(Object p,Method m,Object[] a)throws Throwable{
                String n=m.getName();if(n.equals("asBinder"))return token;if(n.equals("toString"))return "Sailfish keyboard session";if(n.equals("hashCode"))return System.identityHashCode(p);if(n.equals("equals"))return p==a[0];
                if(n.equals("finishSession")){if(focused==c)finish(c);return null;}
                if(focused!=c||c.editor==null)return null;
                if(n.equals("updateSelection")){c.start=(Integer)a[2];c.end=(Integer)a[3];c.composingStart=(Integer)a[4];extract(c);return null;}
                if(n.equals("updateExtractedText")){updateExtracted(c,(ExtractedText)a[1]);return null;}
                if(n.equals("updateCursor")){c.cursor=a[0]==null?null:new Rect((Rect)a[0]);return null;}
                if(n.equals("viewClicked")){widget(c,false);return null;}
                if(n.equals("displayCompletions")){c.completions=a[0]==null?null:((CompletionInfo[])a[0]).clone();return null;}
                if(n.equals("appPrivateCommand")){c.privateAction=(String)a[0];return null;/* No private command extension is advertised. */}
                if(n.equals("updateCursorAnchorInfo")){CursorAnchorInfo info=(CursorAnchorInfo)a[0];if(info!=null){float x=info.getInsertionMarkerHorizontal(),top=info.getInsertionMarkerTop(),bottom=info.getInsertionMarkerBottom();c.cursor=new Rect((int)x,(int)top,(int)x+1,(int)bottom);}return null;}
                if(n.equals("toggleSoftInput")){show(c,keyboardHeight==0,null);return null;}
                if(n.equals("notifyImeHidden")){show(c,false,null);return null;}
                throw SdRuntimeDiagnostics.unsupported("Keyboard session",m);
            }
        });token.attachInterface(proxy,"com.android.internal.view.IInputMethodSession");return proxy;
    }
    private void updateExtracted(Client c,ExtractedText text){if(c!=focused||c.editor==null||text==null||hidden(c))return;c.surrounding=text.text==null?"":text.text.toString();c.offset=text.startOffset;c.start=c.offset+text.selectionStart;c.end=c.offset+text.selectionEnd;widget(c,false);}
    private void extract(final Client c)throws android.os.RemoteException{
        if(c.context==null||hidden(c)){c.surrounding="";widget(c,false);return;}
        final long gen=c.generation;final Binder token=new Binder();IInputContextCallback callback=(IInputContextCallback)Proxy.newProxyInstance(IInputContextCallback.class.getClassLoader(),new Class<?>[]{IInputContextCallback.class},new InvocationHandler(){public Object invoke(Object p,Method m,Object[] a){if(m.getName().equals("asBinder"))return token;if(m.getName().equals("setExtractedText")){if(focused==c&&c.generation==gen)updateExtracted(c,(ExtractedText)a[0]);return null;}throw new UnsupportedOperationException(m.toString());}});token.attachInterface(callback,"com.android.internal.view.IInputContextCallback");
        ExtractedTextRequest request=new ExtractedTextRequest();request.hintMaxChars=2048;request.hintMaxLines=20;c.context.getExtractedText(request,0,++extractSequence,callback);
    }
    private void show(Client c,boolean visible,ResultReceiver receiver){c.wantsShow=visible;c.receiver=receiver;if(!visible){if(!SdMaliit.connected()||keyboardHeight==0){if(receiver!=null)receiver.send(1,null);c.receiver=null;}else SdMaliit.show(false);return;}SdMaliit.start(this);widget(c,false);if(SdMaliit.connected())SdMaliit.show(true);}
    private void finish(Client c){
        if(c!=focused)return;
        IInputContext context=c.context;
        // Finishing composition can synchronously report selection and re-enter
        // finishInput. Retire this editor before calling its input connection.
        focused=null;
        c.editor=null;
        c.surrounding="";
        generation++;
        show(c,false,null);
        syncDismiss();
        if(context!=null)try{context.finishComposingText();}catch(RemoteException ignored){}
    }
    public static void hostFocus(boolean active){instance.hostActive=active;instance.syncDismiss();Client c=instance.focused;if(c==null||c.editor==null)return;if(active){instance.widget(c,true);if(c.wantsShow)SdMaliit.show(true);}else{instance.widget(c,true);SdMaliit.show(false);}}
    @Override public Object invoke(Object p,Method m,Object[] a)throws Throwable{
        String n=m.getName();if(n.equals("asBinder"))return binder;if(n.equals("toString"))return "SailDroid Maliit input methods";if(n.equals("hashCode"))return System.identityHashCode(p);if(n.equals("equals"))return p==a[0];
        if(n.equals("getInputMethodList")||n.equals("getEnabledInputMethodList")){return Arrays.asList(new InputMethodInfo("org.saildroid.runtime","org.saildroid.runtime.Maliit","Sailfish keyboard",null));}
        if(n.equals("getEnabledInputMethodSubtypeList")||n.equals("getShortcutInputMethodsAndSubtypes"))return new ArrayList<Object>();
        if(n.equals("getCurrentInputMethodSubtype")||n.equals("getLastInputMethodSubtype"))return null;
        if(n.equals("addClient")){
            if(Build.VERSION.SDK_INT<29){
                if((Integer)a[2]!=Process.myUid()||(Integer)a[3]!=Process.myPid())
                    throw new IllegalArgumentException("Input client belongs to another process");
            }else if((Integer)a[2]!=SdDisplayShim.DISPLAY_ID){
                throw new IllegalArgumentException("Unknown input display");
            }
            registerClient((IInputMethodClient)a[0],(IInputContext)a[1]);return null;
        }
        if(n.equals("removeClient")){
            Client c=clients.remove(((IInputMethodClient)a[0]).asBinder());
            if(c!=null)finish(c);return null;
        }
        if(n.equals("startInputOrWindowGainedFocus")){
            Client c=client(a[1]);c.window=(IBinder)a[2];EditorInfo editor=(EditorInfo)a[6];
            // A focus-only report has no new EditorInfo/InputContext. Android
            // sends this when an already-bound editor regains window focus;
            // it must not destroy that editor's existing input connection.
            if(editor==null){if(focused!=null&&focused!=c)finish(focused);System.err.println("SDIME=window_focus_only|retained_editor="+(focused==c&&c.editor!=null));return InputBindResult.NO_EDITOR;}
            c.context=(IInputContext)a[7];
            if(!SdApkPackage.NAME.equals(editor.packageName))return InputBindResult.INVALID_PACKAGE_NAME;
            if(focused!=null&&focused!=c)finish(focused);focused=c;c.editor=editor;c.generation=++generation;c.sequence=++sequence;c.start=editor.initialSelStart;c.end=editor.initialSelEnd;c.surrounding="";c.offset=0;c.composingStart=-1;
            SdMaliit.start(this);c.callback.setActive(true,false);widget(c,true);extract(c);c.bound=SdMaliit.connected();
            // Window focus can restart input after the host already restored
            // this editor. Reapply its show request after the context reset.
            if(c.wantsShow&&hostActive&&SdMaliit.connected())SdMaliit.show(true);
            return result(c);
        }
        if(n.equals("finishInput")){finish(client(a[0]));return null;}
        if(n.equals("showSoftInput")||n.equals("hideSoftInput")){Client c=client(a[0]);boolean visible=n.equals("showSoftInput");if(visible&&(c!=focused||c.editor==null))return false;show(c,visible,(ResultReceiver)a[2]);return true;}
        if(n.equals("getInputMethodWindowVisibleHeight"))return keyboardHeight;
        if(n.equals("notifyUserAction"))return null; // This bridge selects no predictive input subtype.
        if(n.equals("shouldOfferSwitchingToNextInputMethod"))return false;
        throw SdRuntimeDiagnostics.unsupported("Maliit input manager",m);
    }
    private void area(int height)throws RemoteException{
        keyboardHeight=Math.max(0,Math.min(SdDisplayShim.HEIGHT,height));SdWindowSession.imeHeight(keyboardHeight);syncDismiss();Client c=focused;if(c!=null&&c.receiver!=null&&c.wantsShow==(keyboardHeight>0)){c.receiver.send(keyboardHeight>0?2:3,null);c.receiver=null;}System.err.println("SDIME=area|height="+keyboardHeight);
    }
    @Override public void event(long gen,int type,String text,int a,int b,int c,int d){
        try{
            final Client current=focused;
            if(type==0){
                if(a!=0){if(current!=null&&current.editor!=null){if(!current.bound){current.callback.onBindMethod(result(current));current.bound=true;}widget(current,true);extract(current);if(current.wantsShow&&hostActive)SdMaliit.show(true);}System.err.println("SDIME=connected");}
                else{area(0);if(current!=null&&current.editor!=null)new Handler(Looper.getMainLooper()).postDelayed(new Runnable(){public void run(){if(focused==current&&current.editor!=null&&hostActive)SdMaliit.start(SdInputMethods.this);}},2000);}
                return;
            }
            if(type==4){int clientHeight=SdWindowHost.clientHeight();area(b<0?0:Math.round(d*(float)SdDisplayShim.HEIGHT/Math.max(1,clientHeight)));return;}
            if(type==6||type==5){if(type==6&&current!=null)current.wantsShow=false;area(0);return;}
            if(current==null||current.editor==null||!hostActive||gen!=current.generation)return;
            if(type==8){current.language=text;return;}if(type==9){current.correction=a!=0;return;}
            IInputContext context=current.context;if(context==null)return;
            if(type==1||type==2){
                int base=current.composingStart>=0?current.composingStart:Math.max(0,Math.min(current.start,current.end));
                if(a!=0||b!=0){context.finishComposingText();base=Math.max(0,Math.min(current.start,current.end)+a);context.setSelection(base,base+Math.max(0,b));}
                if(type==1){context.commitText(text,1);current.composingStart=-1;if(c>=0)context.setSelection(base+c,base+c);System.err.println("SDIME=commit_handled");}
                else{context.setComposingText(text,1);current.composingStart=base;if(c>=0)context.setSelection(base+c,base+c);}
                extract(current);return;
            }
            if(type==7){context.setSelection(a,a+b);extract(current);return;}
            if(type==3){
                int key=b==0x01000003?KeyEvent.KEYCODE_DEL:b==0x01000004||b==0x01000005?KeyEvent.KEYCODE_ENTER:b==0x01000012?KeyEvent.KEYCODE_DPAD_LEFT:b==0x01000014?KeyEvent.KEYCODE_DPAD_RIGHT:b==0x01000013?KeyEvent.KEYCODE_DPAD_UP:b==0x01000015?KeyEvent.KEYCODE_DPAD_DOWN:KeyEvent.KEYCODE_UNKNOWN;
                if(key==KeyEvent.KEYCODE_ENTER&&a==6){int action=current.editor.imeOptions&EditorInfo.IME_MASK_ACTION;if(action!=EditorInfo.IME_ACTION_NONE&&action!=EditorInfo.IME_ACTION_UNSPECIFIED){context.performEditorAction(action);return;}}
                int modifiers=((c&0x02000000)!=0?KeyEvent.META_SHIFT_ON:0)|((c&0x04000000)!=0?KeyEvent.META_CTRL_ON:0)|((c&0x08000000)!=0?KeyEvent.META_ALT_ON:0)|((c&0x10000000)!=0?KeyEvent.META_META_ON:0);
                if(key!=KeyEvent.KEYCODE_UNKNOWN){long now=SystemClock.uptimeMillis();context.sendKeyEvent(new KeyEvent(now,now,a==7?KeyEvent.ACTION_UP:KeyEvent.ACTION_DOWN,key,Math.max(0,d-1),modifiers));}
                else if(a==6&&text!=null&&!text.isEmpty())context.commitText(text,1);
                extract(current);
            }
        }catch(RemoteException failure){throw new IllegalStateException("Input connection failed",failure);}
    }
}
