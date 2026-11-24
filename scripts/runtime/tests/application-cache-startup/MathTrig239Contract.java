/** Independent binary64 oracle values through native/reflection/cold/hot ART. */
public final class MathTrig239Contract {
    private static volatile double sink;
    public static double hotSin(double value) { return Math.sin(value); }
    public static double hotCos(double value) { return Math.cos(value); }
    public static double hotTan(double value) { return Math.tan(value); }
    private static double call(int function, double value) {
        switch (function) { case 0: return hotSin(value); case 1: return hotCos(value); default: return hotTan(value); }
    }
    private static void near(double actual, double expected, String path) {
        if (Double.isNaN(expected)) { if (!Double.isNaN(actual)) throw new AssertionError(path); return; }
        if (expected == 0) {
            if (Double.doubleToRawLongBits(actual) != Double.doubleToRawLongBits(expected)) throw new AssertionError(path);
        } else if (Math.abs(actual - expected) > Math.ulp(expected)) throw new AssertionError(path + ": " + actual + " / " + expected);
    }
    public static void run(String mode) throws Exception {
        String[] names = {"sin", "cos", "tan"};
        // Inputs/answers are supplied by an independent MPFR4096bit oracle file.
        String[] rows = System.getProperty("saidroid.test.trig.oracle").split(";");
        int checks = 0;
        for (int function = 0; function < 3; function++) {
            String[] fields = rows[function].split(",");
            double input = Double.longBitsToDouble(Long.parseUnsignedLong(fields[0], 16));
            double expected = Double.longBitsToDouble(Long.parseUnsignedLong(fields[1], 16));
            java.lang.reflect.Method method = Math.class.getMethod(names[function], double.class);
            double reflected = (Double) method.invoke(null, input), cold = call(function, input);
            for (int i = 0; i < 400000; i++) sink = call(function, input + (i & 1) * Math.ulp(input));
            double warm = call(function, input);
            if (!mode.equals("before237")) { near(reflected, expected, names[function] + " reflection"); checks++; }
            if (mode.equals("full239")) {
                near(cold, expected, names[function] + " cold"); near(warm, expected, names[function] + " hot"); checks += 2;
                java.util.function.DoubleUnaryOperator op = function == 0 ? Math::sin : function == 1 ? Math::cos : Math::tan;
                near(op.applyAsDouble(0.0), function == 1 ? 1.0 : 0.0, "positive zero");
                near(op.applyAsDouble(-0.0), function == 1 ? 1.0 : -0.0, "negative zero");
                near(op.applyAsDouble(Double.POSITIVE_INFINITY), Double.NaN, "infinite domain");
                near(op.applyAsDouble(Double.NaN), Double.NaN, "NaN domain"); checks += 4;
            }
            System.out.println("MATH_TRIG239_PATH=verified|boundary=" + mode + "|function=" + names[function]
                + "|reflected=" + Long.toHexString(Double.doubleToRawLongBits(reflected))
                + "|cold=" + Long.toHexString(Double.doubleToRawLongBits(cold))
                + "|warm=" + Long.toHexString(Double.doubleToRawLongBits(warm)) + "|warmup_calls=400000");
        }
        System.out.println("MATH_TRIG239_CONTRACT=PASS|boundary=" + mode + "|checks=" + checks);
    }
}
