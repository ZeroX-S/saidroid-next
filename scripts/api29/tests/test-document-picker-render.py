#!/usr/bin/env python3
"""Verify SdDocumentPicker matches hardware acceleration to SdWindowHost.hardware()."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / 'scripts/device/SdDocumentPicker.java'
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
    'SdWindowHost.java': '''
public class SdWindowHost {
    public static boolean hw = true;
    public static boolean hardware() { return hw; }
}
''',
    'SdDocumentPicker.java': '''
import android.content.pm.ActivityInfo;
public class SdDocumentPicker {
    METHOD
    public static void main(String[] arguments) {
        int flags = Integer.parseInt(arguments[0]);
        boolean hardware = Boolean.parseBoolean(arguments[1]);
        SdWindowHost.hw = hardware;
        SdApkPackage.application.flags = flags;
        ActivityInfo info = activityInfo();
        boolean accelerated = (info.flags & ActivityInfo.FLAG_HARDWARE_ACCELERATED) != 0;
        if (accelerated != hardware)
            throw new AssertionError("Picker acceleration mismatch for hardware=" + hardware);
        if (SdApkPackage.application.flags != flags)
            throw new AssertionError("Caller flags were modified");
        if (info.applicationInfo != SdApkPackage.application)
            throw new AssertionError("Caller metadata was replaced");
        if (!SdApkPackage.NAME.equals(info.packageName) ||
            !"SdDocumentPicker".equals(info.name) ||
            !SdApkPackage.processName().equals(info.processName) ||
            info.theme != android.R.style.Theme_Material_Light_NoActionBar ||
            !info.enabled || !info.exported)
            throw new AssertionError("Picker ActivityInfo contract changed");
        System.out.println("DOCUMENT_PICKER_RENDER=PASS|flags=" + flags + "|hardware=" + hardware);
    }
}
''',
}


@unittest.skipUnless(JAVA and JAVAC, 'JDK is required')
class DocumentPickerRenderTest(unittest.TestCase):
    def test_window_backend_matching(self):
        source = SOURCE.read_text(encoding='utf-8')
        match = re.search(r'    public static ActivityInfo activityInfo\(\)\s*\{.*?\n    \}', source, re.S)
        self.assertIsNotNone(match, 'SdDocumentPicker.activityInfo() not found')
        with tempfile.TemporaryDirectory(prefix='saildroid-picker-render-') as temporary:
            root = Path(temporary)
            files = []
            for name, content in STUBS.items():
                if name == 'SdDocumentPicker.java':
                    content = content.replace('    METHOD', match.group(0))
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
                files.append(str(target))
            subprocess.run([JAVAC, '--release', '8', '-encoding', 'UTF-8', '-d', str(root), *files],
                           check=True, capture_output=True, text=True, timeout=30)
            for flags in (0, 0x200, 0x1234):
                for hardware in ('true', 'false'):
                    with self.subTest(flags=flags, hardware=hardware):
                        out = subprocess.run([JAVA, '-cp', str(root), 'SdDocumentPicker',
                                              str(flags), hardware],
                                             check=True, capture_output=True, text=True, timeout=10)
                        self.assertIn(f'DOCUMENT_PICKER_RENDER=PASS|flags={flags}|hardware={hardware}',
                                      out.stdout)


if __name__ == '__main__':
    unittest.main()
