import java.io.IOException;
import java.lang.reflect.*;

/** VM-side agent transport and native debugging permission contract. */
public final class JvmtiAgentContract {
    private static native void allow(boolean allowed);
    public static void main(String[] args)throws Exception {
        System.load(args[0]);
        Method attach=dalvik.system.VMDebug.class.getMethod("attachAgent",String.class,ClassLoader.class);
        if(!dalvik.system.VMRuntime.getRuntime().isJavaDebuggable())throw new AssertionError("Explicit debuggable VM expected");
        allow(false);
        boolean rejected=false;
        try{attach.invoke(null,args[1],JvmtiAgentContract.class.getClassLoader());}
        catch(InvocationTargetException error){if(error.getCause()instanceof SecurityException)rejected=true;else throw error;}
        if(!rejected||System.getProperty("saidroid.jvmti.contract")!=null)throw new AssertionError("Agent ran without native debugging authorization");
        allow(true);
        attach.invoke(null,args[1],JvmtiAgentContract.class.getClassLoader());
        if(!"actual-live-capabilities".equals(System.getProperty("saidroid.jvmti.contract")))throw new AssertionError("Real JVMTI callback did not complete");
        System.out.println("JVMTI_AGENT=PASS|native_denial=enforced|agent_handle=private-bionic|phase=live|retransform_callback=actual|tagged_objects_query=actual|loaded_classes=actual");
    }
}
