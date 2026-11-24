#!/usr/bin/env python3
"""Exercise the actual API28 text-service client with a local Binder fixture."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


BINDER = r'''
package android.os;
import java.io.FileDescriptor;
public class Binder implements IBinder {
    private IInterface owner;
    private String descriptor;
    public void attachInterface(IInterface owner, String descriptor) {
        this.owner = owner;
        this.descriptor = descriptor;
    }
    public String getInterfaceDescriptor() { return descriptor; }
    public IInterface queryLocalInterface(String descriptor) {
        return this.descriptor.equals(descriptor) ? owner : null;
    }
    public boolean pingBinder() { return true; }
    public boolean isBinderAlive() { return true; }
    public void dump(FileDescriptor descriptor, String[] arguments) {}
    public void dumpAsync(FileDescriptor descriptor, String[] arguments) {}
    public void shellCommand(FileDescriptor in, FileDescriptor out, FileDescriptor error,
                             String[] arguments, ShellCallback callback, ResultReceiver receiver) {}
    public boolean transact(int code, Parcel data, Parcel reply, int flags) throws RemoteException {
        return onTransact(code, data, reply, flags);
    }
    protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) throws RemoteException {
        return false;
    }
    public void linkToDeath(DeathRecipient recipient, int flags) {}
    public boolean unlinkToDeath(DeathRecipient recipient, int flags) { return true; }
}
'''

SERVICE_MANAGER = r'''
package android.os;
import java.util.HashMap;
public final class ServiceManager {
    private static final HashMap<String, IBinder> services = new HashMap<String, IBinder>();
    public static IBinder getServiceOrThrow(String name) throws ServiceNotFoundException {
        IBinder service = services.get(name);
        if (service == null) throw new ServiceNotFoundException(name);
        return service;
    }
    public static void addService(String name, IBinder service) { services.put(name, service); }
    public static final class ServiceNotFoundException extends Exception {
        public ServiceNotFoundException(String name) { super("No service published for: " + name); }
    }
}
'''

PROBE = r'''
import android.os.IBinder;
import android.os.ServiceManager;
import android.view.textservice.*;
import com.android.internal.textservice.ITextServicesManager;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.concurrent.FutureTask;

public final class TextServicesProbe {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 0 && arguments[0].equals("before")) {
            try {
                TextServicesManager.getInstance();
                throw new AssertionError("Missing text services failed to reproduce");
            } catch (IllegalStateException expected) {
                check(expected.getCause() instanceof ServiceManager.ServiceNotFoundException,
                      "Failure differs from the captured TextServicesManager constructor");
                System.err.println("TEXT_SERVICES_REGRESSION=FAIL|" + expected.getCause().getMessage());
                System.exit(1);
            }
        }
        IBinder binder = SdTextServices.binder();
        ITextServicesManager service = ITextServicesManager.Stub.asInterface(binder);
        check(service != null && service == binder.queryLocalInterface(
              "com.android.internal.textservice.ITextServicesManager"), "Local text-service interface mismatch");
        check(service.asBinder() == binder, "Text-service Binder identity changed");
        check(service.equals(service) && !service.equals(null)
              && service.hashCode() == System.identityHashCode(service)
              && service.toString().equals("Saildroid text services"), "Proxy object contract changed");
        HashSet<String> methods = new HashSet<String>();
        for (java.lang.reflect.Method method : ITextServicesManager.class.getDeclaredMethods()) methods.add(method.getName());
        check(methods.equals(new HashSet<String>(Arrays.asList("getCurrentSpellChecker",
              "getCurrentSpellCheckerSubtype", "getSpellCheckerService", "finishSpellCheckerService",
              "isSpellCheckerEnabled", "getEnabledSpellCheckers"))), "API28 interface coverage changed");
        ServiceManager.addService("textservices", binder);
        TextServicesManager manager = TextServicesManager.getInstance();
        check(manager == TextServicesManager.getInstance(), "Framework singleton initialization changed");
        check(!manager.isSpellCheckerEnabled() && !service.isSpellCheckerEnabled(), "Empty inventory was enabled");
        check(manager.getEnabledSpellCheckers().length == 0 && service.getEnabledSpellCheckers().length == 0,
              "Unexpected spell-checker provider");
        check(manager.getCurrentSpellChecker() == null && service.getCurrentSpellChecker(null) == null
              && service.getCurrentSpellChecker("missing") == null, "Unexpected selected provider");
        check(manager.getCurrentSpellCheckerSubtype(true) == null && manager.getCurrentSpellCheckerSubtype(false) == null
              && service.getCurrentSpellCheckerSubtype("zh_CN", true) == null, "Unexpected selected subtype");
        SpellCheckerSession.SpellCheckerSessionListener listener = new SpellCheckerSession.SpellCheckerSessionListener() {
            public void onGetSuggestions(SuggestionsInfo[] results) { throw new AssertionError("Unexpected session callback"); }
            public void onGetSentenceSuggestions(SentenceSuggestionsInfo[] results) { throw new AssertionError("Unexpected session callback"); }
        };
        check(manager.newSpellCheckerSession(null, Locale.CHINA, listener, true) == null
              && manager.newSpellCheckerSession(null, Locale.CHINA, listener, false) == null,
              "Framework created an unavailable session");
        service.getSpellCheckerService("missing", "zh_CN", null, null, null);
        service.finishSpellCheckerService(null);
        InvocationHandler handler = Proxy.getInvocationHandler(service);
        try {
            handler.invoke(service, Runnable.class.getMethod("run"), null);
            throw new AssertionError("Unknown text-service request accepted");
        } catch (UnsupportedOperationException expected) {
            check(expected.getMessage().contains("Text services"), "Unsupported request lost its owner");
        } catch (Throwable unexpected) {
            throw new AssertionError("Unexpected request failure", unexpected);
        }
        FutureTask<Void> worker = new FutureTask<Void>(new java.util.concurrent.Callable<Void>() {
            public Void call() {
                for (int i = 0; i < 50; i++) {
                    TextServicesManager current = TextServicesManager.getInstance();
                    check(current == manager && !current.isSpellCheckerEnabled()
                          && current.getCurrentSpellCheckerSubtype(true) == null
                          && current.getEnabledSpellCheckers().length == 0, "Background text-service query failed");
                }
                return null;
            }
        });
        Thread thread = new Thread(worker, "text-services-async-fixture");
        thread.start();
        worker.get();
        thread.join();
        System.out.println("TEXT_SERVICES_REGRESSION=PASS|cases=13|framework=API28");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--classes', type=Path, required=True)
    parser.add_argument('--before', action='store_true')
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    services = repository / 'scripts/device/SdServices.java'
    assert 'register("textservices", SdTextServices.binder());' in services.read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='saildroid-text-services-') as temporary:
        root = Path(temporary)
        sources = []
        for name, code in (('android/os/Binder.java', BINDER),
                           ('android/os/ServiceManager.java', SERVICE_MANAGER), ('TextServicesProbe.java', PROBE)):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding='utf-8', newline='\n')
            sources.append(path)
        classes = root / 'classes'
        classes.mkdir()
        classpath = os.pathsep.join(map(str, (arguments.framework, arguments.classes)))
        subprocess.run(['javac', '--release', '8', '-nowarn', '-encoding', 'UTF-8', '-classpath', classpath,
                        '-d', str(classes), *map(str, sources), str(repository / 'scripts/device/SdTextServices.java')], check=True)
        classpath = os.pathsep.join(map(str, (classes, arguments.framework, arguments.classes)))
        subprocess.run(['java', '-classpath', classpath, 'TextServicesProbe', *(['before'] if arguments.before else [])], check=True)


if __name__ == '__main__':
    main()
