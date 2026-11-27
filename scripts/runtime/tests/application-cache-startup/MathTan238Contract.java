/** Original binary64 counterexample through actual native, interpreter and hot Java calls. */
public final class MathTan238Contract {
    private static volatile double sink;
    public static double hot(double value) { return Math.tan(value); }
    public static void run(String mode) throws Exception {
        double input = Double.longBitsToDouble(0x7506ac5b262ca1ffL);
        long correct = 0xc3bd9ba9a7975636L;
        long old = 0xc3bd9ba9a7975644L;
        java.lang.reflect.Method method = Math.class.getMethod("tan", double.class);
        long reflected = Double.doubleToRawLongBits((Double) method.invoke(null, input));
        long cold = Double.doubleToRawLongBits(hot(input));
        for (int i = 0; i < 400000; i++) sink = hot(input + (i & 1) * Math.ulp(input));
        long warmed = Double.doubleToRawLongBits(hot(input));
        long strict = Double.doubleToRawLongBits(StrictMath.tan(input));
        if (strict != correct) throw new AssertionError("Existing StrictMath backend changed");
        if (!(mode.equals("before237") || mode.equals("companion238") || mode.equals("full238")))
            throw new AssertionError("Unknown boundary");
        if (reflected != (mode.equals("before237") ? old : correct))
            throw new AssertionError("Reflected native boundary differed: " + Long.toHexString(reflected));
        if (mode.equals("full238") && (cold != correct || warmed != correct))
            throw new AssertionError("Intrinsic path differed: cold=" + Long.toHexString(cold) + " hot=" + Long.toHexString(warmed));
        if (mode.equals("before237") && (cold != old || warmed != old))
            throw new AssertionError("Baseline intrinsic path not reproduced");
        if (mode.equals("companion238") && cold != old)
            throw new AssertionError("Companion-only unexpectedly changed interpreter intrinsic");
        System.out.println("MATH_TAN238_CONTRACT=PASS|boundary=" + mode + "|reflected=" + Long.toHexString(reflected)
                + "|cold=" + Long.toHexString(cold) + "|warm=" + Long.toHexString(warmed)
                + "|strict=" + Long.toHexString(strict) + "|warmup_calls=400000");
    }
}
