from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
JAVA_HOME = os.environ.get('JAVA_HOME')
JAVA = str(Path(JAVA_HOME) / 'bin/java') if JAVA_HOME else shutil.which('java')
JAVAC = str(Path(JAVA_HOME) / 'bin/javac') if JAVA_HOME else shutil.which('javac')
STUBS = {
    'android/content/ComponentName.java': '''
package android.content;
public class ComponentName {
    public final String packageName, name;
    public ComponentName(String packageName, String name) { this.packageName=packageName; this.name=name; }
}
''',
    'android/content/Intent.java': '''
package android.content;
public class Intent {
    public static final int FLAG_ACTIVITY_CLEAR_TOP=0x04000000, FLAG_ACTIVITY_SINGLE_TOP=0x20000000;
    public int flags;
    public Object album;
    public ComponentName component;
    public Intent() {}
    public Intent(Intent original) { flags=original.flags; album=original.album; component=original.component; }
    public int getFlags() { return flags; }
    public Intent setComponent(ComponentName value) { component=value; return this; }
}
''',
    'android/content/pm/ActivityInfo.java': '''
package android.content.pm;
public class ActivityInfo {
    public static final int LAUNCH_MULTIPLE=0, LAUNCH_SINGLE_TOP=1, LAUNCH_SINGLE_TASK=2, LAUNCH_SINGLE_INSTANCE=3;
    public String packageName="fixture", name;
    public int launchMode;
}
''',
    'android/os/IBinder.java': '''
package android.os;
public interface IBinder {}
''',
    'android/app/Activity.java': '''
package android.app;
public class Activity {
    public static final int RESULT_CANCELED=0;
    public android.content.Intent delivered;
}
''',
    'android/app/ActivityThread.java': '''
package android.app;
public class ActivityThread {
    public static final ActivityThread INSTANCE=new ActivityThread();
    public static final java.util.ArrayList<String> events=new java.util.ArrayList<String>();
    public static ActivityThread currentActivityThread() { return INSTANCE; }
    public Instrumentation getInstrumentation() { return new Instrumentation(); }
    public static class Instrumentation {
        public void callActivityOnNewIntent(Activity activity, android.content.Intent intent) {
            activity.delivered=intent;
            events.add("new-intent");
        }
    }
}
''',
}
HARNESS = '''
import android.app.*;
import android.content.*;
import android.content.pm.*;
import android.os.*;
import java.util.*;
public class SdActivityHost {
    static final ArrayList<Entry> stack=new ArrayList<Entry>();
    static final ArrayList<Runnable> queue=new ArrayList<Runnable>();
    static final class Entry {
        ActivityInfo info=new ActivityInfo();
        Activity activity=new Activity();
        IBinder token=new IBinder(){};
        Intent intent;
        Entry(String name) { info.name=name; }
    }
    static void refreshTask() {}
    static boolean requestFinish(IBinder token,int code,Intent result) {
        Entry selected=null;
        for(Entry entry:stack)if(entry.token==token)selected=entry;
        final Entry captured=selected;
        queue.add(() -> {
            if(!stack.contains(captured))return;
            stack.remove(captured);
            ActivityThread.events.add("canceled");
            ActivityThread.events.add("resume");
        });
        return true;
    }
    METHOD
    static void require(boolean value,String message) { if(!value)throw new AssertionError(message); }
    public static void main(String[] arguments) {
        String scenario=arguments[0];
        Entry root=new Entry("Chat"), child=new Entry("Album");
        stack.add(root);stack.add(child);
        Intent request=new Intent();request.flags=0x24000000;request.album=new Object();
        ActivityInfo info=root.info;
        int requestCode=-1;
        IBinder remote=null;
        boolean expected=true;
        if(scenario.equals("single-top-mode")) { request.flags=0x04000000;info.launchMode=1; }
        if(scenario.equals("single-task-mode")) { request.flags=0x04000000;info.launchMode=2; }
        if(scenario.equals("standard-clear-only")) { request.flags=0x04000000;expected=false; }
        if(scenario.equals("no-clear")) { request.flags=0x20000000;expected=false; }
        if(scenario.equals("for-result")) { requestCode=42;expected=false; }
        if(scenario.equals("remote")) { remote=new IBinder(){};expected=false; }
        if(scenario.equals("absent")) { info=new ActivityInfo();info.name="Missing";expected=false; }
        if(scenario.equals("unready")) { root.activity=null;expected=false; }
        if(scenario.equals("same-top")) { info=child.info;expected=false; }
        if(scenario.equals("nested")) stack.add(new Entry("Preview"));
        if(scenario.equals("already-finishing")) requestFinish(child.token,0,null);
        int originalSize=stack.size();
        boolean reused=reuseClearTop(request,info,requestCode,remote);
        require(reused==expected,"Reuse policy: "+scenario);
        if(expected) {
            require(root.activity.delivered!=request,"Intent was not copied");
            require(root.activity.delivered.album==request.album,"Photo payload was lost");
            require(request.component==null,"Original request was changed");
            for(int index=0;index<queue.size();index++)queue.get(index).run();
            require(stack.size()==1&&stack.get(0)==root,"Chat instance was replaced");
            require(ActivityThread.events.indexOf("new-intent")<ActivityThread.events.indexOf("resume"),"Intent arrived after resume");
            require(Collections.frequency(ActivityThread.events,"canceled")==originalSize-1,"Child result delivered twice");
        } else {
            require(stack.size()==originalSize&&queue.isEmpty(),"Rejected reuse changed stack");
            require(root.activity==null||root.activity.delivered==null,"Rejected reuse delivered intent");
        }
        System.out.println("ACTIVITY_CLEAR_TOP=PASS|case="+scenario);
    }
}
'''


@unittest.skipUnless(JAVA and JAVAC, 'JDK is required')
class ActivityClearTopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='saildroid-clear-top-')
        cls.root = Path(cls.workspace.name)
        source = (REPO / 'scripts/device/SdActivityHost.java').read_text()
        if 'if(reuseClearTop(request,info,requestCode,remoteResult))return;' not in source:
            raise AssertionError('Clear-top handling is not wired into Activity launch')
        method = re.search(r'    private static boolean reuseClearTop\([^\n]*\{\n.*?^    \}', source, re.S | re.M)
        if method is None:
            raise AssertionError('Clear-top reuse method is missing')
        sources = dict(STUBS)
        sources['SdActivityHost.java'] = HARNESS.replace('    METHOD', method.group(0))
        files = []
        for name, content in sources.items():
            path = cls.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            files.append(str(path))
        cls.classes = cls.root / 'classes'
        cls.classes.mkdir()
        subprocess.run([JAVAC, '--release', '8', '-d', str(cls.classes), *files],
                       check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def test_clear_top_delivery(self):
        scenarios = ['combined-flags', 'single-top-mode', 'single-task-mode', 'standard-clear-only',
                     'no-clear', 'for-result', 'remote', 'absent', 'unready', 'same-top',
                     'nested', 'already-finishing']
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result = subprocess.run([JAVA, '-cp', str(self.classes), 'SdActivityHost', scenario],
                                        check=True, capture_output=True, text=True, timeout=10)
                self.assertIn('ACTIVITY_CLEAR_TOP=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
