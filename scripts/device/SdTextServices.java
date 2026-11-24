import android.os.Binder;
import android.os.IBinder;
import android.view.textservice.SpellCheckerInfo;
import com.android.internal.textservice.ITextServicesManager;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

/** Exposes the runtime's empty Android spell-checker provider inventory. */
public final class SdTextServices implements InvocationHandler {
    private static final SdTextServices instance = new SdTextServices();
    private final Binder binder = new Binder();
    private final ITextServicesManager service;

    private SdTextServices() {
        service = (ITextServicesManager) Proxy.newProxyInstance(
                ITextServicesManager.class.getClassLoader(),
                new Class<?>[]{ITextServicesManager.class}, this);
        binder.attachInterface(service, "com.android.internal.textservice.ITextServicesManager");
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
            return "Saildroid text services";
        }
        if (name.equals("hashCode")) {
            return System.identityHashCode(proxy);
        }
        if (name.equals("equals")) {
            return proxy == arguments[0];
        }
        if (name.equals("getCurrentSpellChecker") || name.equals("getCurrentSpellCheckerSubtype")) {
            return null;
        }
        if (name.equals("getEnabledSpellCheckers")) {
            return new SpellCheckerInfo[0];
        }
        if (name.equals("isSpellCheckerEnabled")) {
            return false;
        }
        if (name.equals("getSpellCheckerService") || name.equals("finishSpellCheckerService")) {
            return null;
        }
        throw SdRuntimeDiagnostics.unsupported("Text services", method);
    }
}
