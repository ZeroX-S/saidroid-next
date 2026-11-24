#!/usr/bin/env python3
"""Exercise the production haptic dispatch with real API28 and API29 signatures."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


PROBE = r'''
import android.view.IWindow;
import android.view.IWindowSession;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

public final class WindowHapticsProbe {
    private static final IWindow owner = (IWindow) Proxy.newProxyInstance(
            IWindow.class.getClassLoader(), new Class<?>[]{IWindow.class},
            (proxy, method, arguments) -> null);
    private static int validated;

    private static Object window(Object candidate) {
        if (candidate != owner) throw new IllegalArgumentException("Unregistered window");
        validated++;
        return candidate;
    }

    private static Object invoke(Method m, Object[] a) {
        String n = m.getName();
        HANDLER
        throw new AssertionError("Unexpected method " + n);
    }

    public static void main(String[] arguments) throws Exception {
        int api = Integer.parseInt(arguments[0]);
        int expectedCount = api == 28 ? 3 : 2;
        Method method = null;
        for (Method candidate : IWindowSession.class.getMethods()) {
            if (candidate.getName().equals("performHapticFeedback")) method = candidate;
        }
        if (method == null || method.getParameterCount() != expectedCount) {
            throw new AssertionError("Framework haptic signature differs");
        }
        int calls = 0;
        for (int effect : new int[]{0, 1, 3, 7}) {
            for (boolean always : new boolean[]{false, true}) {
                Object[] values = api == 28 ? new Object[]{owner, effect, always}
                        : new Object[]{effect, always};
                if (!Boolean.FALSE.equals(invoke(method, values))) {
                    throw new AssertionError("Unavailable vibrator advertised");
                }
                calls++;
            }
        }
        if (validated != (api == 28 ? calls : 0)) {
            throw new AssertionError("Window owner validation differs");
        }
        if (api == 28) {
            for (Object foreign : new Object[]{null, new Object()}) {
                try {
                    invoke(method, new Object[]{foreign, 0, false});
                    throw new AssertionError("Unregistered window accepted");
                } catch (IllegalArgumentException expected) {
                    calls++;
                }
            }
        }
        System.out.println("WINDOW_HAPTICS=PASS|api=" + api + "|cases=" + calls);
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework28', required=True, type=Path)
    parser.add_argument('--framework29', required=True, type=Path)
    parser.add_argument('--source', type=Path)
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    source = arguments.source or repository / 'scripts/device/SdWindowSession.java'
    text = source.read_text(encoding='utf-8')
    start = '        if(n.equals("performHapticFeedback")){'
    assert text.count(start) == 1
    begin = text.index(start)
    end = text.index('\n        }', begin) + len('\n        }')
    branch = text[begin:end]
    with tempfile.TemporaryDirectory(prefix='saildroid-window-haptics-') as directory:
        work = Path(directory)
        probe = work / 'WindowHapticsProbe.java'
        probe.write_text(PROBE.replace('HANDLER', branch), encoding='utf-8', newline='\n')
        for api, framework in [(28, arguments.framework28), (29, arguments.framework29)]:
            classes = work / ('classes-' + str(api))
            classes.mkdir()
            subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn',
                            '-cp', str(framework), '-d', str(classes), str(probe)], check=True)
            subprocess.run(['java', '-cp', str(classes) + os.pathsep + str(framework),
                            'WindowHapticsProbe', str(api)], check=True)


if __name__ == '__main__':
    main()
