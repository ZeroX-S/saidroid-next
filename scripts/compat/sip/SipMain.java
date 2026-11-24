package org.saildroid.compat.sip;

/** Ordinary application-loader entry for the root-owned contract bridge. */
public final class SipMain {
    public static void main(String[] args) throws Throwable {
        try {
            Class.forName("SipContracts").getMethod("run", String[].class).invoke(null, (Object) args);
            Runtime.getRuntime().halt(0);
        } catch (java.lang.reflect.InvocationTargetException failure) {
            throw failure.getCause();
        }
    }
}
