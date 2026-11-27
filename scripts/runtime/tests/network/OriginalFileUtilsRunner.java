import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;

/** Six declared original FileUtils tests; a standalone diagnostic, not instrumentation. */
public final class OriginalFileUtilsRunner {
    public static void main(String[] args)throws Exception{
        NativeNetworkRegistrationContract.bootstrap(Boolean.parseBoolean(args[0]),args[1]);
        int sdk=Integer.parseInt(args[4]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        if(dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion()!=sdk)
            throw new AssertionError("Actual APK SDK not bound");
        ClassLoader loader=new dalvik.system.PathClassLoader(args[2],Object.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?> test=Class.forName(args[3],true,loader);
        ArrayList<String> methods=new ArrayList<>();
        for(Method method:test.getDeclaredMethods())
            if(method.getName().startsWith("test")&&method.getParameterTypes().length==0)
                methods.add(method.getName());
        Collections.sort(methods);
        if(methods.size()!=6)throw new AssertionError("Original declared method inventory changed");
        int failures=0;
        for(String name:methods){
            Object instance=test.newInstance();test.getMethod("setName",String.class).invoke(instance,name);
            try{test.getMethod("runBare").invoke(instance);System.out.println("ORIGINAL_FILEUTILS|test="+name+"|result=PASS");}
            catch(InvocationTargetException failure){failures++;System.out.println("ORIGINAL_FILEUTILS|test="+name+"|result=FAIL");failure.getCause().printStackTrace();}
        }
        System.out.println("ORIGINAL_FILEUTILS_VM|tests="+methods.size()+"|failures="+failures+"|targetSdk="+sdk);
        // The listener cases leave AsyncTask executor threads alive. End only
        // this diagnostic process after all original assertions have returned.
        System.out.flush();System.err.flush();System.exit(failures==0?0:1);
    }
}
