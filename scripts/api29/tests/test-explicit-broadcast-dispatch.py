#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import os
import re
import subprocess
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[3]
PATCH = REPO / 'scripts/api29/explicit-broadcast-dispatch-compat/patch.py'
spec = importlib.util.spec_from_file_location('broadcast_patch', PATCH)
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)
JAVA_HOME = os.environ.get('JAVA_HOME')
JAVA = str(Path(JAVA_HOME) / 'bin/java') if JAVA_HOME else 'java'
JAVAC = str(Path(JAVA_HOME) / 'bin/javac') if JAVA_HOME else 'javac'
BASELINE = '''.class public LSdActivityManagerService;
.super Ljava/lang/Object;
.method private blacklist broadcastIntent([Ljava/lang/Object;)I
    .registers 18
    check-cast v10, [Ljava/lang/String;
    move-result v11
''' + patch.ANCHOR + '''    invoke-virtual/range {v1 .. v9}, LSdActivityManagerService;->deliverBroadcast(Landroid/content/Intent;Ljava/lang/String;ILjava/lang/String;Landroid/os/Bundle;[Ljava/lang/String;IZ)V
    invoke-static/range {v1 .. v7}, LSdRemoteServices;->broadcast(Landroid/content/Intent;Ljava/lang/String;ILjava/lang/String;Landroid/os/Bundle;[Ljava/lang/String;I)V
    const-string v1, "Ordered/sticky/app-op/options broadcasts unavailable"
.end method
.method public other()V
    return-void
.end method
'''
STUBS = {
    'android/content/Intent.java': '''
        package android.content;
        public class Intent {
            public Object component;
            public Object getComponent() { return component; }
        }
    ''',
    'android/os/Bundle.java': 'package android.os; public class Bundle {}',
    'android/app/ActivityManager.java': '''
        package android.app;
        public class ActivityManager { public static final int BROADCAST_SUCCESS=0; }
    ''',
}
HARNESS = '''
import android.content.Intent;
import android.app.ActivityManager;
public class SdActivityManagerService {
    static int local;
    static Object[] received;
    METHOD
    void deliverBroadcast(Intent intent,String type,int result,String data,android.os.Bundle extras,
                          String[] permissions,int user,boolean remote) {
        if(intent.getComponent()!=null)throw new UnsupportedOperationException("Manifest receivers unavailable");
        local++;
    }
    static void require(boolean valid,String reason) { if(!valid)throw new AssertionError(reason); }
    public static void main(String[] arguments) throws Exception {
        String scenario=arguments[0];
        Intent intent=new Intent();
        Object[] values=new Object[13];
        values[1]=intent;values[2]="fixture/type";values[4]=7;values[5]="result-data";
        values[6]=new android.os.Bundle();values[7]=new String[]{"fixture.permission"};
        values[8]=-1;values[10]=false;values[11]=false;values[12]=0;
        intent.component=new Object();
        boolean rejected=false;
        if(scenario.equals("implicit"))intent.component=null;
        if(scenario.equals("no-kernel")){intent.component=null;SdKernelServices.active=false;}
        if(scenario.equals("null-intent")){values[1]=null;rejected=true;}
        if(scenario.equals("ordered")){values[10]=true;rejected=true;}
        if(scenario.equals("sticky")){values[11]=true;rejected=true;}
        if(scenario.equals("result-receiver")){values[3]=new Object();rejected=true;}
        if(scenario.equals("app-op")){values[8]=1;rejected=true;}
        if(scenario.equals("options")){values[9]=new Object();rejected=true;}
        if(scenario.equals("permission")){SdManifestReceivers.deny=true;rejected=true;}
        try {
            require(new SdActivityManagerService().broadcastIntent(values)==0,"Broadcast result");
            require(!rejected,"Guard was bypassed");
            if(intent.component!=null) {
                require(received!=null&&local==0&&SdRemoteServices.calls==0,"Explicit routing");
                require(received[0]==intent&&received[1].equals(values[4])&&received[2]==values[5]
                        &&received[3]==values[6]&&received[4]==values[7]&&received[5].equals(values[12]),"Payload");
            } else {
                require(received==null&&local==1,"Implicit routing");
                require(SdRemoteServices.calls==(SdKernelServices.active?1:0),"Remote routing");
            }
        } catch(IllegalArgumentException|UnsupportedOperationException|SecurityException failure) {
            require(rejected,"Unexpected rejection");
            require(local==0&&SdRemoteServices.calls==0&&received==null,"Delivery before rejection");
        }
        System.out.println("EXPLICIT_BROADCAST=PASS|case="+scenario);
    }
}
class SdManifestReceivers {
    static boolean deny;
    static void send(Intent intent,int result,String data,android.os.Bundle extras,String[] permissions,int user) {
        if(deny)throw new SecurityException("Fixture permission denied");
        SdActivityManagerService.received=new Object[]{intent,result,data,extras,permissions,user};
    }
}
class SdKernelServices { static boolean active=true;static boolean enabled(){return active;} }
class SdRemoteServices {
    static int calls;
    static void broadcast(Intent intent,String type,int result,String data,android.os.Bundle extras,
                          String[] permissions,int user){calls++;}
}
'''


class ExplicitBroadcastDispatchTest(unittest.TestCase):
    def test_narrow_patch(self):
        patched = patch.patch_broadcast_intent(BASELINE)
        self.assertEqual(patched.replace(patch.BRANCH + '\n', ''), BASELINE)
        self.assertEqual(patched.count(patch.DISPATCH), 1)

    def test_idempotent(self):
        patched = patch.patch_broadcast_intent(BASELINE)
        self.assertEqual(patch.patch_broadcast_intent(patched), patched)

    def test_reject_unknown_layout(self):
        for invalid in [BASELINE.replace('.registers 18', '.registers 19'),
                        BASELINE.replace('move-result v11', 'move-result v12'),
                        BASELINE + BASELINE, BASELINE.replace(patch.SIGNATURE, '.method private other()I')]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    patch.patch_broadcast_intent(invalid)

    def test_java_reference_routing(self):
        source = (REPO / 'scripts/api29/foreign-broadcast-compat/source/SdActivityManagerService.java').read_text()
        method = re.search(r'    private int broadcastIntent\(Object\[\] args\).*?\n    }', source, re.DOTALL).group()
        with tempfile.TemporaryDirectory(prefix='saildroid-explicit-broadcast-') as temporary:
            root = Path(temporary)
            sources = []
            for name, contents in {**STUBS, 'SdActivityManagerService.java': HARNESS.replace('METHOD', method)}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(contents))
                sources.append(str(path))
            subprocess.run([JAVAC, '--release', '8', '-d', str(root), *sources],
                           check=True, capture_output=True, text=True, timeout=30)
            for scenario in ['explicit', 'implicit', 'no-kernel', 'null-intent', 'ordered', 'sticky',
                             'result-receiver', 'app-op', 'options', 'permission']:
                with self.subTest(scenario=scenario):
                    result = subprocess.run([JAVA, '-cp', str(root), 'SdActivityManagerService', scenario],
                                            check=True, capture_output=True, text=True, timeout=10)
                    self.assertIn('EXPLICIT_BROADCAST=PASS|case=' + scenario, result.stdout)


if __name__ == '__main__':
    unittest.main()
