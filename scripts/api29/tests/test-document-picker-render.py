from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / 'scripts/api29/document-picker-render-compat/source/SdDocumentPicker.java'
JAVA_HOME = os.environ.get('JAVA_HOME')
JAVA = str(Path(JAVA_HOME) / 'bin/java') if JAVA_HOME else shutil.which('java')
JAVAC = str(Path(JAVA_HOME) / 'bin/javac') if JAVA_HOME else shutil.which('javac')
STUBS = {
    'android/content/pm/ApplicationInfo.java': '''
package android.content.pm;
public class ApplicationInfo { public int flags; }
''',
    'android/content/pm/ActivityInfo.java': '''
package android.content.pm;
public class ActivityInfo {
    public static final int FLAG_HARDWARE_ACCELERATED = 0x200;
    public String packageName, name, processName;
    public ApplicationInfo applicationInfo;
    public int theme, flags;
    public boolean enabled, exported;
    public CharSequence nonLocalizedLabel;
}
''',
    'android/R.java': '''
package android;
public class R {
    public static class style {
        public static final int Theme_Material_Light_NoActionBar = 0x1030241;
    }
}
''',
    'SdApkPackage.java': '''
public class SdApkPackage {
    public static final String NAME = "org.example.picker";
    public static final android.content.pm.ApplicationInfo application =
        new android.content.pm.ApplicationInfo();
    public static String processName() { return NAME + ":files"; }
    public static android.content.pm.ApplicationInfo applicationInfo() { return application; }
}
''',
    'PickerRenderContract.java': '''
import android.content.pm.ActivityInfo;
public class PickerRenderContract {
    public static void main(String[] arguments) {
        int flags = Integer.parseInt(arguments[0]);
        SdApkPackage.application.flags = flags;
        ActivityInfo info = SdDocumentPicker.activityInfo();
        if ((info.flags & ActivityInfo.FLAG_HARDWARE_ACCELERATED) == 0)
            throw new AssertionError("Picker uses software drawing");
        if (SdApkPackage.application.flags != flags)
            throw new AssertionError("Caller flags were modified");
        if (info.applicationInfo != SdApkPackage.application)
            throw new AssertionError("Caller metadata was replaced");
        if (!SdApkPackage.NAME.equals(info.packageName) ||
            !"SdDocumentPicker".equals(info.name) ||
            !SdApkPackage.processName().equals(info.processName) ||
            info.theme != android.R.style.Theme_Material_Light_NoActionBar ||
            !info.enabled || !info.exported)
            throw new AssertionError("Picker identity changed");
        System.out.println("DOCUMENT_PICKER_RENDER=PASS|caller_flags=" + flags);
    }
}
''',
}


@unittest.skipUnless(JAVA and JAVAC, 'JDK is required')
class DocumentPickerRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='saildroid-picker-render-')
        cls.root = Path(cls.workspace.name)
        method = re.search(r'    public static ActivityInfo activityInfo\(\) \{\n.*?^    \}',
                           SOURCE.read_text(), re.S | re.M)
        if method is None:
            raise AssertionError('Picker Activity metadata method is missing')
        sources = dict(STUBS)
        sources['SdDocumentPicker.java'] = ('import android.content.pm.ActivityInfo;\n'
            'public class SdDocumentPicker {\n' + method.group(0) + '\n}\n')
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

    def test_picker_hardware_without_changing_caller(self):
        for flags in [0, 0x200, 0x10400000]:
            with self.subTest(caller_flags=flags):
                result = subprocess.run([JAVA, '-cp', str(self.classes),
                                         'PickerRenderContract', str(flags)],
                                        check=True, capture_output=True, text=True, timeout=10)
                self.assertIn('DOCUMENT_PICKER_RENDER=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
