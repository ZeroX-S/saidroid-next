#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / 'scripts/api29/receiver-process-compat/source/SdReceiverProcess.java'
spec = importlib.util.spec_from_file_location('receiver_patch', SOURCE.parent.parent / 'patch.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)
JAVA_HOME = os.environ.get('JAVA_HOME')
JAVA = str(Path(JAVA_HOME) / 'bin/java') if JAVA_HOME else 'java'
JAVAC = str(Path(JAVA_HOME) / 'bin/javac') if JAVA_HOME else 'javac'
STUBS = {
    'android/content/ComponentName.java': '''package android.content;
        public class ComponentName { public ComponentName(String owner,String name) {} }''',
    'android/content/Intent.java': '''package android.content;
        public class Intent {
            public static final Creator CREATOR=new Creator();
            public static class Creator {
                public Intent createFromParcel(android.os.Parcel data){return (Intent)data.next();}
            }
        }''',
    'android/content/pm/ApplicationInfo.java': '''package android.content.pm;
        public class ApplicationInfo { public boolean enabled=true; }''',
    'android/content/pm/ActivityInfo.java': '''package android.content.pm;
        public class ActivityInfo {
            public ApplicationInfo applicationInfo=new ApplicationInfo();
            public String processName="fixture.app:tool";
        }''',
    'android/content/pm/ProviderInfo.java': '''package android.content.pm;
        public class ProviderInfo {
            public boolean enabled=true;
            public ApplicationInfo applicationInfo=new ApplicationInfo();
            public String name="fixture.Provider",packageName="fixture.app",processName="fixture.app:tool";
        }''',
    'android/content/pm/PackageParser.java': '''package android.content.pm;
        public class PackageParser {
            public static class Package { public java.util.ArrayList<Provider> providers=new java.util.ArrayList<>(); }
            public static class Provider { public ProviderInfo info=new ProviderInfo(); }
        }''',
    'android/os/Bundle.java': 'package android.os; public class Bundle {}',
    'android/os/Binder.java': '''package android.os;
        public class Binder { public static int caller=100000;public static int getCallingUid(){return caller;} }''',
    'android/os/Process.java': '''package android.os;
        public class Process { public static int myUid(){return 100000;} }''',
    'android/os/Parcel.java': '''package android.os;
        public class Parcel {
            public final java.util.ArrayList<Object> values=new java.util.ArrayList<>();
            public int position;public boolean succeeded;
            public Object next(){return values.get(position++);}
            public String readString(){return (String)next();}
            public int readInt(){return (Integer)next();}
            public Bundle readBundle(){return (Bundle)next();}
            public String[] createStringArray(){return (String[])next();}
            public void writeNoException(){succeeded=true;}
        }''',
    'org/saildroid/host/HostApi.java': '''package org.saildroid.host;
        public class HostApi {
            public static String[] launch;
            public static void startProviderProcess(String owner,String provider,String process){
                launch=new String[]{owner,provider,process};
            }
        }''',
}
HARNESS = '''
import android.content.*;
import android.content.pm.*;
import android.os.*;
public class ReceiverProcessContract {
    static void require(boolean valid,String reason){if(!valid)throw new AssertionError(reason);}
    public static void main(String[] arguments) throws Exception {
        String scenario=arguments[0];
        if(scenario.startsWith("start-")) {
            PackageParser.Provider provider=new PackageParser.Provider();
            SdApkPackage.metadata.providers.add(provider);
            String owner=SdApkPackage.NAME,process="fixture.app:tool";
            boolean rejected=false;
            if(scenario.equals("start-foreign")){owner="other.app";rejected=true;}
            if(scenario.equals("start-process")){process="fixture.app:other";rejected=true;}
            if(scenario.equals("start-undeclared")){SdApkPackage.receiver=null;rejected=true;}
            if(scenario.equals("start-disabled-receiver")){SdApkPackage.receiver.applicationInfo.enabled=false;rejected=true;}
            if(scenario.equals("start-disabled-provider")){provider.info.enabled=false;rejected=true;}
            if(scenario.equals("start-disabled-provider-app")){provider.info.applicationInfo.enabled=false;rejected=true;}
            if(scenario.equals("start-provider-other-process")){provider.info.processName="fixture.app";rejected=true;}
            if(scenario.equals("start-provider-foreign")){provider.info.packageName="other.app";rejected=true;}
            if(scenario.equals("start-null-provider-name")){provider.info.name=null;rejected=true;}
            if(scenario.equals("start-no-provider")){SdApkPackage.metadata.providers.clear();rejected=true;}
            if(scenario.equals("start-skip-disabled")){
                provider.info.enabled=false;SdApkPackage.metadata.providers.add(new PackageParser.Provider());
            }
            try {
                SdReceiverProcess.start(owner,"fixture.Receiver",process);
                require(!rejected,"Startup guard bypassed");
                require(org.saildroid.host.HostApi.launch[1].equals("fixture.Provider"),"Not the declared provider");
                require(org.saildroid.host.HostApi.launch[0].equals(owner)
                        &&org.saildroid.host.HostApi.launch[2].equals(process),"Provider identity lost");
            } catch(SecurityException|UnsupportedOperationException failure) {
                require(rejected,"Unexpected startup rejection");
                require(org.saildroid.host.HostApi.launch==null,"Invalid native launch");
            }
        } else {
            Parcel data=new Parcel(),reply=new Parcel();Intent intent=new Intent();Bundle extras=new Bundle();
            String[] permissions={"fixture.permission"};
            java.util.Collections.addAll(data.values,SdApkPackage.NAME,intent,7,"payload",extras,permissions,3);
            boolean rejected=false;
            if(scenario.equals("dispatch-uid")){Binder.caller=1;rejected=true;}
            if(scenario.equals("dispatch-package")){data.values.set(0,"other.app");rejected=true;}
            if(scenario.equals("dispatch-permission")){SdManifestReceivers.failure=new SecurityException("Denied");rejected=true;}
            if(scenario.equals("dispatch-runtime")){SdManifestReceivers.failure=new IllegalArgumentException("Invalid receiver");rejected=true;}
            if(scenario.equals("dispatch-checked")){SdManifestReceivers.failure=new Exception("Transport");rejected=true;}
            try {
                require(SdReceiverProcess.dispatch(data,reply),"Transaction result");
                require(!rejected&&reply.succeeded,"Success reply");
                Object[] received=SdManifestReceivers.received;
                require(received[0]==intent&&received[1].equals(7)&&received[2].equals("payload")
                        &&received[3]==extras&&received[4]==permissions&&received[5].equals(3),"Receiver payload lost");
            } catch(RuntimeException failure) {
                require(rejected&&!reply.succeeded,"Incorrect failure reply");
                require(SdManifestReceivers.received==null,"Delivery despite rejection");
                if(scenario.equals("dispatch-checked"))require(failure.getCause()==SdManifestReceivers.failure,"Checked cause lost");
                if(scenario.equals("dispatch-permission")||scenario.equals("dispatch-runtime"))
                    require(failure==SdManifestReceivers.failure,"Runtime exception changed");
            }
        }
        System.out.println("RECEIVER_PROCESS=PASS|case="+scenario);
    }
}
class SdApkPackage {
    static final String NAME="fixture.app";
    static ActivityInfo receiver=new ActivityInfo();
    static final PackageParser.Package metadata=new PackageParser.Package();
    static ActivityInfo receiverInfo(ComponentName component,int flags){return receiver;}
    static PackageParser.Package parsed(){return metadata;}
    static String providerProcess(ProviderInfo info){return info.processName;}
}
class SdManifestReceivers {
    static Object[] received;static Exception failure;
    static void deliverLocal(Intent intent,int result,String resultData,Bundle extras,String[] permissions,int user)throws Exception {
        if(failure!=null)throw failure;
        received=new Object[]{intent,result,resultData,extras,permissions,user};
    }
}
'''


class ReceiverProcessTest(unittest.TestCase):
    def test_reference(self):
        with tempfile.TemporaryDirectory(prefix='saildroid-receiver-process-') as temporary:
            root = Path(temporary)
            sources = [str(SOURCE)]
            for name, contents in {**STUBS, 'ReceiverProcessContract.java': HARNESS}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(contents))
                sources.append(str(path))
            subprocess.run([JAVAC, '--release', '8', '-d', str(root), *sources],
                           check=True, capture_output=True, text=True, timeout=30)
            scenarios = ['start-valid', 'start-foreign', 'start-process', 'start-undeclared',
                         'start-disabled-receiver', 'start-disabled-provider', 'start-disabled-provider-app',
                         'start-provider-other-process', 'start-provider-foreign', 'start-null-provider-name',
                         'start-no-provider', 'start-skip-disabled', 'dispatch-valid', 'dispatch-uid',
                         'dispatch-package', 'dispatch-permission', 'dispatch-runtime', 'dispatch-checked']
            for scenario in scenarios:
                with self.subTest(scenario=scenario):
                    result = subprocess.run([JAVA, '-cp', str(root), 'ReceiverProcessContract', scenario],
                                            check=True, capture_output=True, text=True, timeout=10)
                    self.assertIn('RECEIVER_PROCESS=PASS|case=' + scenario, result.stdout)

    def test_endpoint_patch(self):
        method = patch.ENDPOINT_SIGNATURE + '''
    .registers 20
    const/16 v3, 0x8

    if-le v0, v3, :cond_1a
    :cond_1a
    invoke-static {}, Landroid/os/Binder;->getCallingUid()I
    if-ne v6, v7, :cond_16f
    invoke-virtual {v1, v4}, Landroid/os/Parcel;->enforceInterface(Ljava/lang/String;)V
    const/4 v4, 0x0

    if-ne v0, v3, :cond_7d
.end method
'''
        patched = patch.patch_endpoint(method)
        self.assertIn('const/16 v3, 0x9\n\n    if-le', patched)
        self.assertIn(':cond_1a\n    const/16 v3, 0x8', patched)
        self.assertLess(patched.index('enforceInterface'), patched.index(patch.DISPATCH))
        self.assertEqual(patch.patch_endpoint(patched), patched)
        with self.assertRaises(ValueError):
            patch.patch_endpoint(method.replace('.registers 20', '.registers 21'))

    def test_worker_patch(self):
        method = patch.WORKER_SIGNATURE + '''
    .registers 6
    invoke-static {v1, v2, v3}, Lorg/saildroid/host/HostApi;->startReceiverProcess(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V
    mul-long/2addr v1, v3
    .line 64
    :cond_52
    :catch_a5
    move-exception v0
.end method
'''
        patched = patch.patch_worker(method)
        self.assertNotIn('HostApi;->startReceiverProcess', patched)
        self.assertNotIn('mul-long', patched)
        self.assertIn(patch.STARTUP, patched)
        self.assertIn(patch.INTERRUPT, patched)
        self.assertEqual(patch.patch_worker(patched), patched)
        with self.assertRaises(ValueError):
            patch.patch_worker(method.replace('.registers 6', '.registers 7'))


if __name__ == '__main__':
    unittest.main()
