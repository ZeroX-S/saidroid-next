import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

/** Real SDK boundary for the obsolete overload; normal loading remains usable. */
public final class RuntimeLoadCompatibilityContract {
    private static int checks;
    private static void check(boolean value, String label) {
        ++checks;
        if (!value) throw new AssertionError(label);
    }
    private static Throwable hiddenFailure(Method method, String name) throws Exception {
        try {
            method.invoke(Runtime.getRuntime(), name, null);
            throw new AssertionError("Missing library unexpectedly loaded");
        } catch (InvocationTargetException failure) {
            return failure.getCause();
        }
    }
    public static void main(String[] args) throws Exception {
        dalvik.system.VMRuntime vm = dalvik.system.VMRuntime.getRuntime();
        int saved = vm.getTargetSdkVersion();
        Method hidden = Runtime.class.getDeclaredMethod("loadLibrary", String.class, ClassLoader.class);
        hidden.setAccessible(true);
        try {
            for (int sdk : new int[]{24, 25, 29}) {
                vm.setTargetSdkVersion(sdk);
                check(vm.getTargetSdkVersion() == sdk, "Actual VM SDK bound");
                Throwable missing = hiddenFailure(hidden, "saidroid_contract_library_does_not_exist");
                System.out.println("RUNTIME_LOAD_BOUNDARY|actualSdk=" + sdk
                        + "|hiddenError=" + missing.getClass().getName());
                check(sdk <= 24 ? missing instanceof UnsatisfiedLinkError
                        : missing instanceof UnsupportedOperationException, "Deprecated SDK boundary");
                Throwable nullName = hiddenFailure(hidden, null);
                check(sdk <= 24 ? nullName instanceof NullPointerException
                        : nullName instanceof UnsupportedOperationException, "Guard before name lookup");
                try {
                    System.loadLibrary("saidroid_contract_library_does_not_exist");
                    throw new AssertionError("Public System load unexpectedly succeeded");
                } catch (UnsatisfiedLinkError expected) {
                    check(true, "Public System missing-library behavior unchanged");
                }
                try {
                    Runtime.getRuntime().loadLibrary("saidroid_contract_library_does_not_exist");
                    throw new AssertionError("Public Runtime load unexpectedly succeeded");
                } catch (UnsatisfiedLinkError expected) {
                    check(true, "Public Runtime missing-library behavior unchanged");
                }
                System.loadLibrary("javacore");
                Runtime.getRuntime().loadLibrary("javacore");
                check(libcore.icu.ICU.getIcuVersion().startsWith("63.2"), "Real native loading retained");
            }
        } finally {
            vm.setTargetSdkVersion(saved);
        }
        check(vm.getTargetSdkVersion() == saved, "SDK restored");
        System.out.println("RUNTIME_LOAD_COMPATIBILITY=PASS|checks=" + checks
                + "|actualSdkBoundary=24/25|publicNativeLoading=retained");
    }
}
