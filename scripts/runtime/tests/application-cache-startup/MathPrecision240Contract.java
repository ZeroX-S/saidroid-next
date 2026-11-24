/** Independent oracle through native/reflection, cold ART and actual JIT calls. */
public final class MathPrecision240Contract {
    private static volatile double sink;
    public static double hotSin(double x) { return Math.sin(x); }
    public static double hotCos(double x) { return Math.cos(x); }
    public static double hotTan(double x) { return Math.tan(x); }
    public static double hotCbrt(double x) { return Math.cbrt(x); }
    public static double hotPow(double x, double y) { return Math.pow(x, y); }
    private static double call(int f, double x, double y) {
        switch(f) {case 0:return hotSin(x);case 1:return hotCos(x);case 2:return hotTan(x);case 3:return hotCbrt(x);default:return hotPow(x,y);}
    }
    private static void near(double actual, double expected, String path) {
        if(Double.isNaN(expected)) {if(!Double.isNaN(actual))throw new AssertionError(path);return;}
        if(expected==0 || Double.isInfinite(expected)) {
            if(Double.doubleToRawLongBits(actual)!=Double.doubleToRawLongBits(expected))throw new AssertionError(path);
        } else if(!Double.isFinite(actual)||Math.abs(actual-expected)>Math.ulp(expected))throw new AssertionError(path+": "+actual+" / "+expected);
    }
    public static void run(String mode) throws Exception {
        String[] names={"sin","cos","tan","cbrt","pow"};
        String[] rows=System.getProperty("saidroid.test.precision.oracle").split(";");int checks=0;
        for(int f=0;f<5;f++) {
            String[] fields=rows[f].split(",");
            double x=Double.longBitsToDouble(Long.parseUnsignedLong(fields[0],16));
            double y=Double.longBitsToDouble(Long.parseUnsignedLong(fields[1],16));
            double expected=Double.longBitsToDouble(Long.parseUnsignedLong(fields[2],16));
            java.lang.reflect.Method method=f==4?Math.class.getMethod(names[f],double.class,double.class):Math.class.getMethod(names[f],double.class);
            double reflection=(Double)(f==4?method.invoke(null,x,y):method.invoke(null,x)),cold=call(f,x,y);
            for(int i=0;i<400000;i++)sink=call(f,x+(i&1)*Math.ulp(x),y);
            double warm=call(f,x,y);
            if(!mode.equals("before237")){near(reflection,expected,names[f]+" reflection");checks++;}
            if(mode.equals("full240")){near(cold,expected,names[f]+" cold");near(warm,expected,names[f]+" hot");checks+=2;}
            System.out.println("MATH_PRECISION240_PATH=verified|boundary="+mode+"|function="+names[f]+"|reflected="+Long.toHexString(Double.doubleToRawLongBits(reflection))+"|cold="+Long.toHexString(Double.doubleToRawLongBits(cold))+"|warm="+Long.toHexString(Double.doubleToRawLongBits(warm))+"|warmup_calls=400000");
        }
        if(mode.equals("full240")) {
            for(int f=0;f<4;f++) {
                near(call(f,0.0,0),f==1?1:0,"positive zero");
                near(call(f,-0.0,0),f==1?1:-0.0,"negative zero");
                near(call(f,Double.POSITIVE_INFINITY,0),f==3?Double.POSITIVE_INFINITY:Double.NaN,"infinity");
                near(call(f,Double.NaN,0),Double.NaN,"NaN");checks+=4;
            }
            double[][] cases={{1,Double.NaN,Double.NaN},{Double.NaN,0,1},{-0.0,3,-0.0},{-0.0,-3,Double.NEGATIVE_INFINITY},{-2,0.5,Double.NaN},{-2,3,-8},{2,3,8},{Double.POSITIVE_INFINITY,-1,0.0},{-1,Double.POSITIVE_INFINITY,Double.NaN},{0.0,2,0.0}};
            for(double[] c:cases){near(hotPow(c[0],c[1]),c[2],"pow domain");checks++;}
            near(hotCbrt(27),3,"exact cube");near(hotCbrt(-27),-3,"negative cube");checks+=2;
        }
        System.out.println("MATH_PRECISION240_CONTRACT=PASS|boundary="+mode+"|checks="+checks);
    }
}
