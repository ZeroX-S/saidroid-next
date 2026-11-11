import java.io.File;
import java.util.*;

/** Native search bindings for the one Android application in this Linux process.
 * App/boot loaders share that process's bionic link map; ART retains each JNI
 * library's real defining ClassLoader. This does not create kernel namespaces.
 */
public final class SdClassLoaderNamespaces {
    /** Android permits generated native code in this application's code cache.
     * Register only canonical cache roots; the linker canonicalizes each loaded
     * file's parent, so symlinks outside the root do not match its wildcard. */
    public static void registerApplicationCodeCache(android.content.pm.ApplicationInfo app)throws java.io.IOException {
        File data=new File(app.dataDir).getCanonicalFile();
        ArrayList<File> roots=new ArrayList<File>();roots.add(data);
        if(app.deviceProtectedDataDir!=null){
            File device=new File(app.deviceProtectedDataDir).getCanonicalFile();
            if(!device.equals(new File(data,"device-protected")))throw new SecurityException("Device code cache escaped private application data");
            roots.add(device);
        }
        ArrayList<String> paths=new ArrayList<String>();
        for(File root:roots)for(String kind:new String[]{"code_cache","cache"}){
            File cache=new File(root,kind);
            if(!cache.isDirectory()&&!cache.mkdirs())throw new java.io.IOException("Cannot create application native cache");
            if(!cache.getCanonicalFile().equals(cache))throw new SecurityException("Application native cache is a symbolic link");
            String path=cache.getPath();paths.add(path);paths.add(path+"/*");
        }
        // Validate every root before one atomic append to the native loader.
        // Native RS C++ callers legitimately use Context.getCacheDir(), while
        // Java RS uses code_cache. Both remain within this installed app.
        if(!SdBridge.addBionicLibraryPath(String.join(File.pathSeparator,paths)))throw new IllegalStateException("Application native cache path registration failed");
        System.err.println("SDNAMESPACE=code_cache_bound|package="+app.packageName+"|roots="+roots.size()+"|cacheDirectories="+(paths.size()/2)+"|scope=private-application-native-cache");
    }
    private static final WeakHashMap<ClassLoader,Binding> bindings=new WeakHashMap<ClassLoader,Binding>();
    public static String bindLegacy(ClassLoader loader,int sdk,String libraries,String permitted,boolean shared,boolean vendor){
        if(!(loader instanceof dalvik.system.BaseDexClassLoader))return "Only DEX class loaders are supported";
        if(vendor)return "Vendor class loaders are outside this application runtime";
        try{
            java.lang.reflect.Field pathList=dalvik.system.BaseDexClassLoader.class.getDeclaredField("pathList");pathList.setAccessible(true);
            Object paths=pathList.get(loader);
            java.lang.reflect.Field elements=paths.getClass().getDeclaredField("dexElements");elements.setAccessible(true);
            ArrayList<String> dexPaths=new ArrayList<String>();
            for(Object element:(Object[])elements.get(paths)){
                java.lang.reflect.Field file=element.getClass().getDeclaredField("dexFile");file.setAccessible(true);
                dalvik.system.DexFile dex=(dalvik.system.DexFile)file.get(element);
                if(dex!=null)dexPaths.add(dex.getName());
            }
            return bind(loader,sdk,libraries,permitted,shared,String.join(File.pathSeparator,dexPaths));
        }catch(ReflectiveOperationException failure){return "Cannot read the DEX class loader identity: "+failure;}
    }
    private static final class Binding {
        final int sdk;final String libraries,permitted,dex;final boolean shared;
        Binding(int sdk,String libraries,String permitted,boolean shared,String dex){this.sdk=sdk;this.libraries=libraries;this.permitted=permitted;this.shared=shared;this.dex=dex;}
    }
    public static void installNativePathListener()throws Exception{
        final Class<?> listener=Class.forName("dalvik.system.BaseDexClassLoader$NativeLibraryPathListener");
        Object callback=java.lang.reflect.Proxy.newProxyInstance(listener.getClassLoader(),new Class<?>[]{listener},new java.lang.reflect.InvocationHandler(){
            public Object invoke(Object proxy,java.lang.reflect.Method method,Object[] args){
                if(method.getName().equals("pathsAdded")){
                    Collection<String> paths=(Collection<String>)args[1];String joined=String.join(File.pathSeparator,paths);
                    if(!joined.isEmpty()&&!SdBridge.addBionicLibraryPath(joined))throw new IllegalStateException("Native library search update failed");
                    return null;
                }
                if(method.getName().equals("toString"))return "SailDroid native library search updates";
                if(method.getName().equals("hashCode"))return System.identityHashCode(proxy);
                if(method.getName().equals("equals"))return proxy==args[0];
                throw new UnsupportedOperationException(method.toString());
            }
        });
        dalvik.system.BaseDexClassLoader.class.getMethod("setNativeLibraryPathListener",listener).invoke(null,callback);
    }
    public static synchronized String bind(ClassLoader loader,int sdk,String libraries,String permitted,boolean shared,String dex){
        if(loader==null)return "ClassLoader is required";
        if(!(loader instanceof dalvik.system.BaseDexClassLoader))return "Only DEX class loaders are supported";
        if(sdk<1||dex==null||dex.isEmpty())return "Complete namespace identity is required";
        Binding existing=bindings.get(loader);
        if(existing!=null){return existing.sdk==sdk&&Objects.equals(existing.libraries,libraries)&&Objects.equals(existing.permitted,permitted)&&existing.shared==shared&&existing.dex.equals(dex)?null:"ClassLoader namespace identity changed";}
        try{
            if(libraries!=null&&!libraries.isEmpty()){
                for(String path:libraries.split(File.pathSeparator))if(!path.isEmpty()&&!path.startsWith("/"))return "Library paths must be absolute";
                if(!SdBridge.addBionicLibraryPath(libraries))return "Bionic library path could not be registered";
            }
            bindings.put(loader,new Binding(sdk,libraries,permitted,shared,dex));
            System.err.println("SDNAMESPACE=bound|sdk="+sdk+"|shared="+shared+"|scope=application-process");return null;
        }catch(RuntimeException failure){return failure.getMessage()==null?failure.getClass().getName():failure.getMessage();}
    }
}
