#!/usr/bin/env python3
"""Exercise the real input manager's synchronous finish callbacks on the JVM."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile


BINDER_STUB = """
package android.os;

public class Binder implements IBinder {
    private IInterface owner;
    private String descriptor;

    public Binder() {}
    public void attachInterface(IInterface value, String name) {
        owner = value;
        descriptor = name;
    }
    public String getInterfaceDescriptor() { return descriptor; }
    public boolean pingBinder() { return true; }
    public boolean isBinderAlive() { return true; }
    public IInterface queryLocalInterface(String name) {
        return name.equals(descriptor) ? owner : null;
    }
    public void dump(java.io.FileDescriptor fd, String[] arguments) {}
    public void dumpAsync(java.io.FileDescriptor fd, String[] arguments) {}
    public void shellCommand(java.io.FileDescriptor in, java.io.FileDescriptor out,
            java.io.FileDescriptor err, String[] arguments, ShellCallback callback,
            ResultReceiver receiver) {}
    public boolean transact(int code, Parcel data, Parcel reply, int flags) {
        throw new UnsupportedOperationException("Host Binder transaction");
    }
    public void linkToDeath(DeathRecipient recipient, int flags) {}
    public boolean unlinkToDeath(DeathRecipient recipient, int flags) { return true; }
}
"""

PROBE = """
import android.os.Binder;
import android.os.RemoteException;
import android.view.inputmethod.EditorInfo;
import com.android.internal.view.IInputContext;
import com.android.internal.view.IInputMethodClient;
import com.android.internal.view.IInputMethodSession;
import java.lang.reflect.Field;
import java.lang.reflect.Proxy;
import java.util.Map;

public final class InputMethodFinishProbe {
    private static final Object manager = readStatic("instance");
    private static int passed;

    private static Field field(Object object, String name) {
        try {
            Field result = object.getClass().getDeclaredField(name);
            result.setAccessible(true);
            return result;
        } catch (ReflectiveOperationException failure) {
            throw new AssertionError(failure);
        }
    }

    private static Object readStatic(String name) {
        try {
            Field result = SdInputMethods.class.getDeclaredField(name);
            result.setAccessible(true);
            return result.get(null);
        } catch (ReflectiveOperationException failure) {
            throw new AssertionError(failure);
        }
    }

    private static Object read(Object object, String name) {
        try { return field(object, name).get(object); }
        catch (IllegalAccessException failure) { throw new AssertionError(failure); }
    }

    private static void write(Object object, String name, Object value) {
        try { field(object, name).set(object, value); }
        catch (IllegalAccessException failure) { throw new AssertionError(failure); }
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static final class Editor {
        final Binder token = new Binder();
        final IInputMethodClient callback;
        final Object client;
        int compositionCalls;
        Runnable compositionCallback;
        boolean remoteFailure;

        Editor() {
            callback = (IInputMethodClient) Proxy.newProxyInstance(
                IInputMethodClient.class.getClassLoader(),
                new Class<?>[] { IInputMethodClient.class }, (proxy, method, arguments) -> {
                    if (method.getName().equals("asBinder")) return token;
                    return null;
                });
            IInputContext context = (IInputContext) Proxy.newProxyInstance(
                IInputContext.class.getClassLoader(),
                new Class<?>[] { IInputContext.class }, (proxy, method, arguments) -> {
                    if (method.getName().equals("finishComposingText")) {
                        compositionCalls++;
                        if (compositionCallback != null) compositionCallback.run();
                        if (remoteFailure) throw new RemoteException("Disconnected editor");
                    }
                    return null;
                });
            SdInputMethods.registerClient(callback, context);
            client = ((Map<?, ?>) read(manager, "clients")).get(token);
        }

        void focus() {
            write(manager, "focused", client);
            write(client, "editor", new EditorInfo());
            write(client, "surrounding", "editor contents");
            write(client, "wantsShow", true);
            write(manager, "generation", (Long) read(manager, "generation") + 1);
        }

        void finish() {
            try { SdInputMethods.service().finishInput(callback); }
            catch (RemoteException failure) { throw new AssertionError(failure); }
        }
    }

    private static void reset() {
        write(manager, "focused", null);
        write(manager, "generation", 0L);
        ((Map<?, ?>) read(manager, "clients")).clear();
    }

    private static void retired(Editor editor) {
        check(read(manager, "focused") == null, "Focus remains on finished editor");
        check(read(editor.client, "editor") == null, "Finished EditorInfo remains active");
        check(read(editor.client, "surrounding").equals(""), "Finished surrounding text remains");
        check(!(Boolean) read(editor.client, "wantsShow"), "Finished editor still requests IME");
    }

    private static void run(String name, Runnable test) {
        reset();
        test.run();
        passed++;
        System.out.println("INPUT_FINISH_CASE=PASS|name=" + name);
    }

    public static void main(String[] arguments) {
        run("synchronous_finishInput_reentry", () -> {
            Editor editor = new Editor();
            editor.focus();
            editor.compositionCallback = () -> {
                if (editor.compositionCalls == 1) editor.finish();
            };
            editor.finish();
            check(editor.compositionCalls == 1, "Composition callback recursively finishes input");
            check((Long) read(manager, "generation") == 2L, "Reentry retires input twice");
            retired(editor);
        });
        run("callback_observes_retired_editor", () -> {
            Editor editor = new Editor();
            editor.focus();
            editor.compositionCallback = () -> retired(editor);
            editor.finish();
        });
        run("callback_focuses_other_client", () -> {
            Editor previous = new Editor();
            Editor next = new Editor();
            previous.focus();
            previous.compositionCallback = () -> next.focus();
            previous.finish();
            check(read(manager, "focused") == next.client, "Callback's new focus is cleared");
            check(read(next.client, "editor") != null, "Callback's new editor is cleared");
            check((Boolean) read(next.client, "wantsShow"), "Callback's IME request is cleared");
            previous.finish();
            check(previous.compositionCalls == 1, "Nonfocused client is finished again");
        });
        run("callback_restarts_same_client", () -> {
            Editor editor = new Editor();
            editor.focus();
            editor.compositionCallback = () -> editor.focus();
            editor.finish();
            check(read(manager, "focused") == editor.client, "Restarted focus is cleared");
            check(read(editor.client, "editor") != null, "Restarted EditorInfo is cleared");
            check(read(editor.client, "surrounding").equals("editor contents"),
                  "Restarted surrounding text is cleared");
            check((Boolean) read(editor.client, "wantsShow"), "Restarted IME request is cleared");
        });
        run("disconnected_input_context", () -> {
            Editor editor = new Editor();
            editor.focus();
            editor.remoteFailure = true;
            editor.finish();
            retired(editor);
        });
        run("missing_input_context", () -> {
            Editor editor = new Editor();
            editor.focus();
            write(editor.client, "context", null);
            editor.finish();
            retired(editor);
            check(editor.compositionCalls == 0, "Absent context is called");
        });
        run("finishSession_entry", () -> {
            Editor editor = new Editor();
            editor.focus();
            try { ((IInputMethodSession) read(editor.client, "session")).finishSession(); }
            catch (RemoteException failure) { throw new AssertionError(failure); }
            retired(editor);
        });
        run("removeClient_entry", () -> {
            Editor editor = new Editor();
            editor.focus();
            try { SdInputMethods.service().removeClient(editor.callback); }
            catch (RemoteException failure) { throw new AssertionError(failure); }
            retired(editor);
            check(((Map<?, ?>) read(manager, "clients")).isEmpty(), "Client remains registered");
        });
        System.out.println("INPUT_FINISH_REGRESSION=PASS|cases=" + passed);
    }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--source", type=Path,
                        default=Path(__file__).resolve().parents[1] / "SdInputMethods.java")
    arguments = parser.parse_args()
    temp_parent = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="saildroid-ime-test-", dir=temp_parent) as temporary:
        work = Path(temporary).resolve()
        assert work.parent == temp_parent and work.name.startswith("saildroid-ime-test-")
        binder = work / "android/os/Binder.java"
        binder.parent.mkdir(parents=True)
        binder.write_text(BINDER_STUB, encoding="utf-8", newline="\n")
        probe = work / "InputMethodFinishProbe.java"
        probe.write_text(PROBE, encoding="utf-8", newline="\n")
        classes = work / "classes"
        classes.mkdir()
        dependencies = os.pathsep.join(map(str, (arguments.framework, arguments.classes)))
        subprocess.run(["javac", "-encoding", "UTF-8", "--release", "8", "-nowarn",
                        "-sourcepath", "", "-classpath", dependencies, "-d", str(classes),
                        str(binder), str(arguments.source), str(probe)], check=True)
        subprocess.run(["java", "-cp", str(classes) + os.pathsep + dependencies,
                        "InputMethodFinishProbe"], check=True)


if __name__ == "__main__":
    main()
