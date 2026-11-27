package org.example.saildroid.jvmticontract;
import android.app.Instrumentation;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;

/** Internal real-agent permission/retransform contract, separate from CTS. */
public final class JvmtiContractInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    private void checks()throws Exception {
        boolean declared=(getTargetContext().getApplicationInfo().flags&ApplicationInfo.FLAG_DEBUGGABLE)!=0;
        boolean expected=getTargetContext().getPackageName().endsWith(".debug");
        if(declared!=expected||Boolean.getBoolean("saidroid.package.debuggable")!=declared)
            throw new AssertionError("APK and VM debugging policy differ");
        String actualArt=System.getProperty("saidroid.art.library");
        String expectedArt=new java.io.File(System.getenv("ANDROID_ROOT"),"lib/libart.so").getCanonicalPath();
        if(!expectedArt.equals(actualArt))throw new AssertionError("Component ART was not explicitly selected");
        boolean mapped=false;
        try(java.io.BufferedReader maps=new java.io.BufferedReader(new java.io.FileReader("/proc/self/maps"))){
            for(String line;(line=maps.readLine())!=null;){
                if(line.endsWith("/libart.so")){
                    if(!line.endsWith(" "+actualArt))throw new AssertionError("Foreign ART mapping "+line);
                    mapped=true;
                }
            }
        }
        if(!mapped)throw new AssertionError("Actual component ART mapping missing");
        java.io.File agent=new java.io.File(getTargetContext().getApplicationInfo().nativeLibraryDir,"libcontractagent.so");
        if(!agent.isFile())throw new AssertionError("Signed APK agent missing");
        String signature="Lorg/example/saildroid/jvmticontract/JvmtiContractInstrumentation;";
        boolean denied=false;
        try{android.os.Debug.attachJvmtiAgent(agent.getCanonicalPath(),signature,getClass().getClassLoader());}
        catch(SecurityException failure){denied=true;if(declared)throw failure;}
        if(declared){
            if(denied||!"actual-live-capabilities".equals(System.getProperty("saidroid.jvmti.contract")))
                throw new AssertionError("Real JVMTI callback did not complete");
        }else if(!denied||System.getProperty("saidroid.jvmti.contract")!=null)
            throw new AssertionError("Agent ran without manifest debugging permission");
        System.out.println("JVMTI_MANIFEST=PASS|debuggable="+declared+"|native_denial="+denied+"|callback="+System.getProperty("saidroid.jvmti.contract"));
    }
    @Override public void onStart(){
        Bundle event=new Bundle();event.putString("class",getClass().getName());event.putString("test","manifestNativeAgentPolicy");event.putInt("numtests",1);sendStatus(1,event);
        Bundle result=new Bundle();
        try{checks();sendStatus(0,event);result.putString("stream","OK (1 test)\n");finish(-1,result);}
        catch(Throwable failure){event.putString("stack",android.util.Log.getStackTraceString(failure));sendStatus(-2,event);result.putString("stream","FAILURES!!! Tests run: 1, Failures: 1\n");result.putString("shortMsg",failure.toString());finish(-1,result);}
    }
}
