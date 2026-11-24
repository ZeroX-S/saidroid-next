#!/usr/bin/env python3
"""Exercise the API28 widget manager against the production local Binder service."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


CONTEXT = r'''
package android.content;
import android.content.res.Resources;
public class Context {
    public static final String APPWIDGET_SERVICE = "appwidget";
    public Object widgets;
    public String getOpPackageName() { return "com.tencent.mm"; }
    public Resources getResources() { return new Resources(); }
    public Object getSystemService(String name) { return APPWIDGET_SERVICE.equals(name) ? widgets : null; }
}
'''

RESOURCES = r'''
package android.content.res;
import android.util.DisplayMetrics;
public class Resources {
    public DisplayMetrics getDisplayMetrics() { return new DisplayMetrics(); }
}
'''

PROBE = r'''
import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Context;
import android.os.IBinder;
import com.android.internal.appwidget.IAppWidgetService;
import java.util.concurrent.FutureTask;

public final class AppWidgetsProbe {
    static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    public static void main(String[] arguments) throws Exception {
        Context context = new Context();
        final ComponentName provider = new ComponentName("com.tencent.mm", "com.tencent.mm.WidgetProvider");
        try {
            AppWidgetManager.getInstance(context).getAppWidgetIds(provider);
            throw new AssertionError("Missing manager failure did not reproduce");
        } catch (NullPointerException expected) {}
        IBinder binder = SdAppWidgets.binder();
        final IAppWidgetService service = IAppWidgetService.Stub.asInterface(binder);
        require(service == binder.queryLocalInterface("com.android.internal.appwidget.IAppWidgetService"),
                "Local interface identity changed");
        require(service.asBinder() == binder, "Binder identity changed");
        require(service.equals(service) && !service.equals(null), "Proxy equality changed");
        require(service.hashCode() == System.identityHashCode(service), "Proxy hash changed");
        require(service.toString().equals("Saildroid app widgets"), "Proxy description changed");
        context.widgets = new AppWidgetManager(context, service);
        final AppWidgetManager manager = AppWidgetManager.getInstance(context);
        require(manager != null && manager == AppWidgetManager.getInstance(context), "Public manager missing");
        require(manager.getAppWidgetIds(provider).length == 0, "Unexpected bound widget");
        require(service.getAppWidgetIdsForHost("com.tencent.mm", 42).length == 0, "Unexpected host widget");
        require(manager.getAppWidgetInfo(42) == null, "Unbound widget has provider info");
        require(service.getAppWidgetViews("com.tencent.mm", 42) == null, "Unbound widget has views");
        require(!manager.isRequestPinAppWidgetSupported(), "Unavailable pinning advertised");
        require(!manager.requestPinAppWidget(provider, null, null), "Unavailable pinning accepted");
        require(!service.bindAppWidgetId("com.tencent.mm", 42, 0, provider, null), "Unavailable binding accepted");
        require(!service.hasBindAppWidgetPermission("com.tencent.mm", 0), "Unexpected binding permission");
        require(!service.isBoundWidgetPackage("com.tencent.mm", 0), "Unexpected bound widget package");
        try {
            service.allocateAppWidgetId("com.tencent.mm", 42);
            throw new AssertionError("Unavailable allocation accepted");
        } catch (UnsupportedOperationException expected) {
            require(expected.getMessage().contains("App widgets"), "Allocation failure lost its owner");
        }
        FutureTask<Void> worker = new FutureTask<Void>(() -> {
            for (int i = 0; i < 100; i++) {
                require(manager.getAppWidgetIds(provider).length == 0, "Background manager query changed");
                require(service.getAppWidgetIds(provider).length == 0, "Background Binder query changed");
            }
            return null;
        });
        Thread thread = new Thread(worker, "widget-account-initialization");
        thread.start();
        worker.get();
        thread.join();
        System.out.println("APP_WIDGETS_REGRESSION=passed|framework=API28|public_manager=true|background_queries=200");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', required=True, type=Path)
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    service = repository / 'scripts/device/SdAppWidgets.java'
    assert 'register("appwidget", SdAppWidgets.binder());' in (service.parent / 'SdServices.java').read_text(encoding='utf-8')
    spec = importlib.util.spec_from_file_location('text_fixture', Path(__file__).with_name('check-text-services.py'))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory(prefix='saildroid-app-widgets-') as temporary:
        root = Path(temporary)
        sources = []
        for name, code in [('android/os/Binder.java', fixture.BINDER), ('android/content/Context.java', CONTEXT),
                           ('android/content/res/Resources.java', RESOURCES),
                           ('android/util/DisplayMetrics.java', 'package android.util; public class DisplayMetrics {}'),
                           ('SdRuntimeDiagnostics.java', 'public class SdRuntimeDiagnostics { public static UnsupportedOperationException unsupported(String owner, java.lang.reflect.Method method) { return new UnsupportedOperationException(owner + " " + method); } }'),
                           ('AppWidgetsProbe.java', PROBE)]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        classes = root / 'classes'
        classes.mkdir()
        subprocess.run(['javac', '--release', '8', '-nowarn', '-encoding', 'UTF-8', '-cp', str(arguments.framework),
                        '-d', str(classes), *map(str, sources), str(service)], check=True)
        subprocess.run(['java', '-cp', os.pathsep.join(map(str, [classes, arguments.framework])), 'AppWidgetsProbe'], check=True)


if __name__ == '__main__':
    main()
