import android.view.View;
import android.view.ViewGroup;

/** Crash-time view hierarchy dump.
 *
 * A measure-time NullPointerException ("margin layout params is null") names only the
 * framework frame, not the child View whose params are missing. This walks every window
 * still registered with the window session and prints each attached View's class, id,
 * visibility and whether getLayoutParams() returned null, so the failing child and its
 * parent chain appear in the application log before the process exits.
 *
 * Also available through the authenticated host diagnostic request. */
public final class SdViewDump {
    private static final int MAX_DEPTH=64,MAX_VIEWS=800;

    public static void dump(){
        StringBuilder out=new StringBuilder(8192);
        try{
            Object[] clients=SdWindowSession.windowClients();
            out.append("SDVIEWS=windows|count=").append(clients.length).append('\n');
            for(int i=0;i<clients.length;i++){
                Object client=clients[i];
                out.append("SDVIEWS=window|index=").append(i).append("|client=").append(client.getClass().getName()).append('\n');
                Object root;
                try{report(client,out,i);}catch(Throwable failure){out.append("SDVIEWS=viewroot_unavailable|index=").append(i).append("|type=").append(failure.getClass().getName()).append("|message=").append(failure.getMessage()).append('\n');}
                try{root=decorView(client);}catch(Throwable failure){out.append("SDVIEWS=root_unavailable|index=").append(i).append("|type=").append(failure.getClass().getName()).append("|message=").append(failure.getMessage()).append('\n');continue;}
                if(!(root instanceof View)){out.append("SDVIEWS=root_unavailable|index=").append(i).append("|type=not_a_view|actual=").append(root==null?"null":root.getClass().getName()).append('\n');continue;}
                walk((View)root,0,out,new int[]{MAX_VIEWS});
            }
        }catch(Throwable failure){
            out.append("SDVIEWS=dump_failed|type=").append(failure.getClass().getName()).append("|message=").append(failure.getMessage()).append('\n');
        }
        System.err.print(out);
        System.err.flush();
    }

    /** ViewRootImpl 的输入接收端到底建没建：事件"写进 channel 成功"并不等于"有人读"。 */
    private static void report(Object client,java.lang.StringBuilder out,int index)throws ReflectiveOperationException{
        Object viewRoot=viewRootOf(client);
        if(viewRoot==null){out.append("SDVIEWS=viewroot|index=").append(index).append("|null=true\n");return;}
        Object receiver=value(viewRoot,"mInputEventReceiver");
        Object first=value(viewRoot,"mFirst");
        Object added=value(viewRoot,"mAdded");
        Object view=value(viewRoot,"mView");
        out.append("SDVIEWS=viewroot|index=").append(index)
           .append("|added=").append(added)
           .append("|receiver=").append(receiver==null?"null":receiver.getClass().getName())
           .append("|firstStage=").append(first==null?"null":first.getClass().getName())
           .append("|view=").append(view==null?"null":view.getClass().getName())
           .append('\n');
    }

    private static Object value(Object target,String name){
        try{return field(target.getClass(),name).get(target);}catch(Throwable failure){return "?"+failure.getClass().getSimpleName();}
    }

    private static Object viewRootOf(Object client)throws ReflectiveOperationException{
        Object viewRoot=null;
        try{
            Object holder=field(client.getClass(),"mViewAncestor").get(client);
            if(holder instanceof java.lang.ref.WeakReference)viewRoot=((java.lang.ref.WeakReference<?>)holder).get();
            else if(holder!=null)viewRoot=holder;
        }catch(NoSuchFieldException older){/* 回退到 this$0 */}
        if(viewRoot==null){
            java.lang.reflect.Field outer=field(client.getClass(),"this$0");
            viewRoot=outer.get(client);
        }
        return viewRoot;
    }

    private static Object decorView(Object client)throws ReflectiveOperationException{
        /* ViewRootImpl.W 在不同 AOSP 版本里保存外围实例的方式不同：
           API 29 是 `private final WeakReference<ViewRootImpl> mViewAncestor`，
           更老的实现才有合成字段 `this$0`。两种都要试，否则诊断代码自己在
           最需要它的时候抛 NoSuchFieldException（2026-10-27 真机实测）。 */
        Object viewRoot=null;
        try{
            Object holder=field(client.getClass(),"mViewAncestor").get(client);
            if(holder instanceof java.lang.ref.WeakReference)viewRoot=((java.lang.ref.WeakReference<?>)holder).get();
            else if(holder!=null)viewRoot=holder;
        }catch(NoSuchFieldException older){/* 回退到 this$0 */}
        if(viewRoot==null){
            java.lang.reflect.Field outer=field(client.getClass(),"this$0");
            viewRoot=outer.get(client);
        }
        if(viewRoot==null)throw new IllegalStateException("no ViewRootImpl for client");
        return field(viewRoot.getClass(),"mView").get(viewRoot);
    }

    private static java.lang.reflect.Field field(Class<?> type,String name)throws NoSuchFieldException{
        for(Class<?> current=type;current!=null;current=current.getSuperclass()){
            try{
                java.lang.reflect.Field found=current.getDeclaredField(name);
                found.setAccessible(true);
                return found;
            }catch(NoSuchFieldException missing){/* keep walking up */}
        }
        throw new NoSuchFieldException(type.getName()+"."+name);
    }

    private static void walk(View view,int depth,StringBuilder out,int[] budget){
        if(view==null||depth>=MAX_DEPTH||budget[0]<=0)return;
        budget[0]--;
        String params;
        try{
            Object layoutParams=view.getLayoutParams();
            params=layoutParams==null?"null":layoutParams.getClass().getName();
        }catch(Throwable failure){params="error:"+failure.getClass().getSimpleName();}
        int[] location=new int[2];view.getLocationOnScreen(location);
        out.append("SDVIEWS=view|d=").append(depth).append("|class=").append(view.getClass().getName())
            .append("|id=").append(describeId(view))
            .append("|vis=").append(view.getVisibility())
            .append("|screen=").append(location[0]).append(',').append(location[1])
            .append("|layout=").append(view.getWidth()).append('x').append(view.getHeight())
            .append("|measured=").append(view.getMeasuredWidth()).append('x').append(view.getMeasuredHeight())
            .append("|params=").append(params);
        if(view instanceof ViewGroup)out.append("|children=").append(((ViewGroup)view).getChildCount());
        out.append('\n');
        if(!(view instanceof ViewGroup))return;
        ViewGroup group=(ViewGroup)view;
        int count=group.getChildCount();
        for(int index=0;index<count;index++){
            View child;
            try{child=group.getChildAt(index);}catch(Throwable failure){
                out.append("SDVIEWS=child_unavailable|d=").append(depth+1).append("|i=").append(index).append("|type=").append(failure.getClass().getName()).append('\n');
                continue;
            }
            walk(child,depth+1,out,budget);
        }
    }

    private static String describeId(View view){
        try{
            int id=view.getId();
            if(id==View.NO_ID)return "none";
            try{return id+"(0x"+Integer.toHexString(id)+","+view.getResources().getResourceEntryName(id)+")";}
            catch(Throwable unresolved){return id+"(0x"+Integer.toHexString(id)+")";}
        }catch(Throwable failure){return "unavailable:"+failure.getClass().getSimpleName();}
    }
}
