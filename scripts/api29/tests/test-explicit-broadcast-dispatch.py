#!/usr/bin/env python3
"""Verify SdActivityManagerService.broadcastIntent routes explicit component broadcasts."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


REPO = Path(__file__).resolve().parents[3]
JAVA_HOME = os.environ.get('JAVA_HOME')
JAVA = str(Path(JAVA_HOME) / 'bin/java') if JAVA_HOME else shutil.which('java')
JAVAC = str(Path(JAVA_HOME) / 'bin/javac') if JAVA_HOME else shutil.which('javac')

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
        values[6]=new android.os.Bundle();values[7]=new String[]{"perm.a"};
        values[8]=-1;values[10]=false;values[11]=false;values[12]=0;
        if("explicit".equals(scenario))intent.component=new Object();
        if("no-kernel".equals(scenario))SdKernelServices.active=false;
        if("null-intent".equals(scenario))values[1]=null;
        if("ordered".equals(scenario))values[10]=true;
        if("sticky".equals(scenario))values[11]=true;
        if("result-receiver".equals(scenario))values[3]=new Object();
        if("app-op".equals(scenario))values[8]=5;
        if("options".equals(scenario))values[9]=new Object();
        if("permission".equals(scenario)){intent.component=new Object();SdManifestReceivers.deny=true;}
        SdActivityManagerService service=new SdActivityManagerService();
        try {
            int out=service.broadcastIntent(values);
            require(out==ActivityManager.BROADCAST_SUCCESS,"Unexpected return code");
            if("explicit".equals(scenario)){
                require(local==0&&SdRemoteServices.calls==0,"Explicit broadcast reached dynamic receivers");
                require(received!=null&&received[0]==intent&&(Integer)received[1]==7
                        &&"result-data".equals(received[2])&&received[3]==values[6]
                        &&received[4]==values[7]&&(Integer)received[5]==0,"Payload changed");
            } else if("implicit".equals(scenario)){
                require(received==null&&local==1&&SdRemoteServices.calls==1,"Implicit broadcast mismatch");
            } else if("no-kernel".equals(scenario)){
                require(received==null&&local==1&&SdRemoteServices.calls==0,"No-kernel broadcast mismatch");
            } else {
                throw new AssertionError("Invalid broadcast was accepted: "+scenario);
            }
        } catch (IllegalArgumentException expected) {
            require("null-intent".equals(scenario),"Unexpected IllegalArgumentException");
        } catch (UnsupportedOperationException expected) {
            require("ordered".equals(scenario)||"sticky".equals(scenario)||"result-receiver".equals(scenario)
                    ||"app-op".equals(scenario)||"options".equals(scenario),"Unexpected UnsupportedOperationException");
        } catch (SecurityException expected) {
            require("permission".equals(scenario),"Unexpected SecurityException");
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


@unittest.skipUnless(JAVA and JAVAC, 'JDK is required')
class ExplicitBroadcastDispatchTest(unittest.TestCase):
    def test_production_broadcast_routing(self):
        source = (REPO / 'scripts/device/SdActivityManagerService.java').read_text(encoding='utf-8')
        match = re.search(r'    private int broadcastIntent\(Object\[\] args\).*?\n    \}', source, re.DOTALL)
        self.assertIsNotNone(match, 'SdActivityManagerService.broadcastIntent not found')
        with tempfile.TemporaryDirectory(prefix='saildroid-explicit-broadcast-') as temporary:
            root = Path(temporary)
            sources = []
            for name, contents in {**STUBS, 'SdActivityManagerService.java': HARNESS.replace('METHOD', match.group())}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(contents), encoding='utf-8')
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
