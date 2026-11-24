/** Per-DEX native trust gate: debug opt-in never relaxes another app loader. */
public final class TrustedDexContract {
    private static int run(ClassLoader loader)throws Exception {
        Class<?> probe=Class.forName("HiddenApiAppProbe",true,loader);
        if(probe.getClassLoader()!=loader)throw new AssertionError("Wrong probe owner");
        return (Integer)probe.getDeclaredMethod("run").invoke(null);
    }
    public static void main(String[]args)throws Exception {
        boolean debug=Boolean.parseBoolean(args[1]);
        if(dalvik.system.VMRuntime.getRuntime().isJavaDebuggable()!=debug)
            throw new AssertionError("Real VM debug flag differs");
        ClassLoader parent=ClassLoader.getSystemClassLoader();
        ClassLoader ordinary=new dalvik.system.PathClassLoader(args[0],parent);
        if(run(ordinary)!=3)throw new AssertionError("Initial application access was not denied");
        boolean denied=false;
        try {
            ClassLoader trusted=new dalvik.system.BaseDexClassLoader(args[0],null,null,parent,true);
            if(!debug)throw new AssertionError("Nondebug process accepted trusted DEX");
            if(run(trusted)!=0)throw new AssertionError("Native per-DEX trust was not applied");
        }catch(SecurityException failure){
            denied=true;if(debug)throw failure;
            if(!"Can't exempt class, process is not debuggable.".equals(failure.getMessage()))
                throw new AssertionError("Denial did not come from the real ART native",failure);
        }
        if(!debug&&!denied)throw new AssertionError("Native nondebug denial absent");
        if(run(ordinary)!=3)throw new AssertionError("Trust leaked to ordinary DEX");
        ClassLoader appended=new dalvik.system.PathClassLoader("",parent);
        java.lang.reflect.Method add=dalvik.system.BaseDexClassLoader.class.getDeclaredMethod("addDexPath",String.class,boolean.class);
        try {
            add.invoke(appended,args[0],true);
            if(!debug)throw new AssertionError("Nondebug process accepted trusted DEX append");
            if(run(appended)!=0)throw new AssertionError("Appended native DEX trust missing");
        }catch(java.lang.reflect.InvocationTargetException failure){
            if(debug||!(failure.getCause()instanceof SecurityException))throw failure;
            if(!"Can't exempt class, process is not debuggable.".equals(failure.getCause().getMessage()))
                throw new AssertionError("Append denial did not come from ART",failure);
        }
        if(run(ordinary)!=3)throw new AssertionError("Appended trust leaked globally");
        System.out.println("TRUSTED_DEX=PASS|debug="+debug+"|native_gate=actual|append=checked|ordinary_loader=denied|global_exemptions=none");
    }
}
