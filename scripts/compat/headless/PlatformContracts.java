package org.saildroid.compat;

import java.lang.reflect.InvocationTargetException;

/** Application-owned entry into the one exposed test-bootstrap method. */
public final class PlatformContracts {
    public static void main(String[] arguments) throws Throwable {
        if (arguments.length != 1) throw new IllegalArgumentException("One contract group required");
        try {
            Class<?> bridge = Class.forName("org.saildroid.compat.RuntimeContracts");
            bridge.getMethod("run", String.class, ClassLoader.class).invoke(null, arguments[0],
                    PlatformContracts.class.getClassLoader());
            System.out.println("COMPAT_EVENT=" + arguments[0] + "|PASS|");
        } catch (InvocationTargetException failure) {
            System.out.println("COMPAT_EVENT=" + arguments[0] + "|FAIL|" + failure.getCause());
            throw failure.getCause();
        }
    }
}
