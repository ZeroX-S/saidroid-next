#!/usr/bin/env python3
"""Compile and exercise the API29 AppOps service contract in isolation.

The fixture invokes the production proxy through the API29 framework interface;
it does not access a device, camera, microphone, or package data.
"""
from pathlib import Path
import os, subprocess, tempfile

STUBS = {
    'SdServiceManagerStub.java': 'final class SdServiceManagerStub { static void put(String name, android.os.IBinder binder) {} }\n',
    'SdApkPackage.java': 'final class SdApkPackage { static final String NAME="org.example.app"; static final String APK="fixture.apk"; }\n',
    'SdRuntimeDiagnostics.java': 'final class SdRuntimeDiagnostics { static UnsupportedOperationException unsupported(String what, java.lang.reflect.Method method) { return new UnsupportedOperationException(what+": "+method); } }\n',
    'SdAppPermissions.java': '''final class SdAppPermissions {
        SdAppPermissions(String apk,String packageName) {}
        boolean holds(String permission) { return Boolean.getBoolean("test.permission.granted"); }
    }
''',
    'AppOpsContract.java': '''import android.app.AppOpsManager;
import com.android.internal.app.IAppOpsService;
import java.lang.reflect.*;
public final class AppOpsContract {
  static void check(boolean ok,String msg){if(!ok)throw new AssertionError(msg);}
  static Object call(InvocationHandler h,Method m,Object[] args)throws Exception{try{return h.invoke(null,m,args);}catch(Throwable t){if(t instanceof Exception)throw (Exception)t;throw new AssertionError(t);}}
  public static void main(String[] args)throws Exception {
    Constructor<?> ctor=Class.forName("SdCameraAppOps").getDeclaredConstructor();ctor.setAccessible(true);
    Class<?> unsafeClass=Class.forName("sun.misc.Unsafe");
    Field uf=unsafeClass.getDeclaredField("theUnsafe");uf.setAccessible(true);
    Object handler=unsafeClass.getMethod("allocateInstance",Class.class).invoke(uf.get(null),Class.forName("SdCameraAppOps"));
    InvocationHandler invocation=(InvocationHandler)handler;
    int uid=android.os.Process.myUid();String pkg="org.example.app";
    Method checkOperation=IAppOpsService.class.getMethod("checkOperation",int.class,int.class,String.class);
    Method noteOperation=IAppOpsService.class.getMethod("noteOperation",int.class,int.class,String.class);
    Method checkPackage=IAppOpsService.class.getMethod("checkPackage",int.class,String.class);
    int camera=(Integer)call(invocation,checkOperation,new Object[]{AppOpsManager.OP_CAMERA,uid,pkg});
    check(camera==AppOpsManager.MODE_IGNORED,"camera default mode="+camera);
    check((Integer)call(invocation,checkOperation,new Object[]{AppOpsManager.OP_PLAY_AUDIO,uid,pkg})==AppOpsManager.MODE_ALLOWED,"playback not allowed");
    check((Integer)call(invocation,checkOperation,new Object[]{999,uid,pkg})==AppOpsManager.MODE_IGNORED,"unknown owner operation not ignored");
    check((Integer)call(invocation,checkOperation,new Object[]{AppOpsManager.OP_CAMERA,uid+1,pkg})==AppOpsManager.MODE_ERRORED,"foreign uid not denied");
    check((Integer)call(invocation,checkPackage,new Object[]{uid,pkg})==AppOpsManager.MODE_ALLOWED,"owner package not allowed");
    check((Integer)call(invocation,checkPackage,new Object[]{uid+1,pkg})==AppOpsManager.MODE_ERRORED,"foreign package check not denied");
    check((Integer)call(invocation,noteOperation,new Object[]{AppOpsManager.OP_CAMERA,uid,pkg})==AppOpsManager.MODE_IGNORED,"note operation unsupported");
    System.out.println("APPOPS_CONTRACT=passed|checkOperation|noteOperation|checkPackage|foreign-denial");
  }
}
''',
}

def main():
    repo=Path(__file__).resolve().parents[3]
    jar=Path(os.environ.get('ANDROID_ALL_JAR',str(repo.parent/'saidroid-pr3-integration-validation/inputs/android-all-10-robolectric-5803371.jar')))
    jdk=Path(os.environ.get('JDK','/tmp/jdkfull/jdk-21.0.13+9'))
    assert jar.is_file(), jar
    with tempfile.TemporaryDirectory(prefix='saidroid-appops-contract-') as d:
        root=Path(d)
        for n,s in STUBS.items():(root/n).write_text(s)
        (root/'android/os').mkdir(parents=True)
        (root/'android/os/Process.java').write_text('package android.os; public final class Process { public static int myUid(){ return 100000; } }\n')
        source=Path(os.environ.get('APPOPS_SOURCE',str(repo/'scripts/device/api29/SdCameraAppOps.java')))
        (root/'SdCameraAppOps.java').write_text(source.read_text())
        classes=root/'classes';classes.mkdir()
        sources=[str(x)for x in root.glob('*.java')]+[str(root/'android/os/Process.java')]
        subprocess.run([str(jdk/'bin/javac'),'--release','8','-cp',str(jar),'-d',str(classes),*sources],check=True)
        subprocess.run([str(jdk/'bin/java'),'-cp',str(classes)+os.pathsep+str(jar),'AppOpsContract'],check=True)
if __name__=='__main__':main()
