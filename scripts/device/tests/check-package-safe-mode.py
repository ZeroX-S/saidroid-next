#!/usr/bin/env python3
"""Exercise the public API28 package safe-mode query through its real proxy."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


PROBE = r'''
import android.app.ApplicationPackageManager;
import android.content.pm.IPackageManager;
import java.lang.reflect.Constructor;
import java.util.concurrent.FutureTask;

public class PackageSafeModeProbe {
    public static void main(String[] arguments) throws Exception {
        IPackageManager service = SdPackageManagerService.service();
        Constructor<?> constructor = ApplicationPackageManager.class.getDeclaredConstructors()[0];
        constructor.setAccessible(true);
        ApplicationPackageManager manager = (ApplicationPackageManager) constructor.newInstance(null, service);
        if (arguments.length != 0) {
            try { manager.isSafeMode(); throw new AssertionError("Baseline failure missing"); }
            catch (UnsupportedOperationException expected) {}
            System.out.println("PACKAGE_SAFE_MODE=baseline|failure=UnsupportedOperationException");
            return;
        }
        if (manager.isSafeMode() || manager.isSafeMode() || service.isSafeMode()) throw new AssertionError("Safe mode advertised");
        if (service.asBinder() != SdPackageManagerService.binder()) throw new AssertionError("Binder identity changed");
        if (!service.equals(service) || service.equals(null)) throw new AssertionError("Proxy identity changed");
        try { service.enterSafeMode(); throw new AssertionError("Unimplemented safe-mode transition accepted"); }
        catch (UnsupportedOperationException expected) {}
        FutureTask<Void> worker = new FutureTask<Void>(() -> {
            for (int index = 0; index < 100; index++) {
                if (manager.isSafeMode() || service.isSafeMode()) throw new AssertionError("Background query changed");
            }
            return null;
        });
        Thread thread = new Thread(worker, "wechat-preferences-initialization");
        thread.start(); worker.get(); thread.join();
        System.out.println("PACKAGE_SAFE_MODE=passed|public_api=28|background_queries=200|normal_boot=true|transition_rejected=true");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', required=True, type=Path)
    parser.add_argument('--classes', required=True, type=Path)
    parser.add_argument('--before', action='store_true')
    arguments = parser.parse_args()
    spec = importlib.util.spec_from_file_location('text_fixture', Path(__file__).with_name('check-text-services.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory(prefix='saildroid-package-safe-mode-') as temporary:
        root = Path(temporary)
        definitions = [
            ('android/os/Binder.java', fixture.BINDER),
            ('android/os/Process.java', 'package android.os; public class Process { public static final int SYSTEM_UID = 1000; public static int myUid() { return 100000; } }'),
            ('SdRuntimeDiagnostics.java', 'public class SdRuntimeDiagnostics { public static UnsupportedOperationException unsupported(String owner, java.lang.reflect.Method method) { return new UnsupportedOperationException(owner + " " + method); } }'),
            ('PackageSafeModeProbe.java', PROBE),
        ]
        sources = []
        for name, code in definitions:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        classes = root / 'classes'
        classes.mkdir()
        classpath = os.pathsep.join(map(str, [arguments.classes, arguments.framework]))
        subprocess.run(['javac', '--release', '8', '-nowarn', '-encoding', 'UTF-8', '-cp',
                        classpath, '-d', str(classes), *map(str, sources)], check=True)
        subprocess.run(['java', '-cp', os.pathsep.join([str(classes), classpath]),
                        'PackageSafeModeProbe', *(['before'] if arguments.before else [])], check=True)


if __name__ == '__main__':
    main()
