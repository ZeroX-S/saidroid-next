import android.os.Binder;
import android.os.IBinder;
import com.android.internal.appwidget.IAppWidgetService;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

/** Reports widget bindings and pinning capabilities of the Sailfish desktop. */
public final class SdAppWidgets implements InvocationHandler {
    private static final SdAppWidgets instance = new SdAppWidgets();
    private final Binder binder = new Binder();
    private final IAppWidgetService service;

    private SdAppWidgets() {
        service = (IAppWidgetService) Proxy.newProxyInstance(
                IAppWidgetService.class.getClassLoader(),
                new Class<?>[]{IAppWidgetService.class}, this);
        binder.attachInterface(service, "com.android.internal.appwidget.IAppWidgetService");
    }

    public static IBinder binder() {
        return instance.binder;
    }

    @Override
    public Object invoke(Object proxy, Method method, Object[] arguments) throws Throwable {
        String name = method.getName();
        if (name.equals("asBinder")) {
            return binder;
        }
        if (name.equals("toString")) {
            return "Saildroid app widgets";
        }
        if (name.equals("hashCode")) {
            return System.identityHashCode(proxy);
        }
        if (name.equals("equals")) {
            return proxy == arguments[0];
        }
        if (name.equals("getAppWidgetIds") || name.equals("getAppWidgetIdsForHost")) {
            return new int[0];
        }
        if (name.equals("getAppWidgetInfo") || name.equals("getAppWidgetViews")) {
            return null;
        }
        if (name.equals("hasBindAppWidgetPermission") || name.equals("bindAppWidgetId")
                || name.equals("isBoundWidgetPackage") || name.equals("requestPinAppWidget")
                || name.equals("isRequestPinAppWidgetSupported")) {
            return false;
        }
        throw SdRuntimeDiagnostics.unsupported("App widgets", method);
    }
}
