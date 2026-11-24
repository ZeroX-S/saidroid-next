#!/usr/bin/env python3
"""Exercise the production haptic dispatch with the real API28 signature."""
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
        Method method = null;
        for (Method candidate : IWindowSession.class.getMethods()) {
            if (candidate.getName().equals("performHapticFeedback")) method = candidate;
        }
        if (method == null || method.getParameterCount() != 3) {
            throw new AssertionError("Framework haptic signature differs");
        }
        int calls = 0;
        for (int effect : new int[]{0, 1, 3, 7}) {
            for (boolean always : new boolean[]{false, true}) {
                Object[] values = new Object[]{owner, effect, always};
                if (!Boolean.FALSE.equals(invoke(method, values))) {
                    throw new AssertionError("Unavailable vibrator advertised");
                }
                calls++;
            }
        }
        if (validated != calls) {
            throw new AssertionError("Window owner validation differs");
        }
        for (Object foreign : new Object[]{null, new Object()}) {
            try {
                invoke(method, new Object[]{foreign, 0, false});
                throw new AssertionError("Unregistered window accepted");
            } catch (IllegalArgumentException expected) {
                calls++;
            }
        }
        System.out.println("WINDOW_HAPTICS=PASS|api=28|cases=" + calls);
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', '--framework28', dest='framework', required=True, type=Path)
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
        classes = work / 'classes-28'
        classes.mkdir()
        subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn',
                        '-cp', str(arguments.framework), '-d', str(classes), str(probe)], check=True)
        subprocess.run(['java', '-cp', str(classes) + os.pathsep + str(arguments.framework),
                        'WindowHapticsProbe'], check=True)


if __name__ == '__main__':
    main()
