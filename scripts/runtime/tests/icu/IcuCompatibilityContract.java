import java.text.Normalizer;
import java.util.Locale;

/** Real Unicode/locale operations against the platform's matching ICU data. */
public final class IcuCompatibilityContract {
    private static void same(Object expected,Object actual) {
        if(!expected.equals(actual))throw new AssertionError("Expected "+expected+", actual "+actual);
    }
    public static void main(String[]args)throws Exception {
        for(String line:java.nio.file.Files.readAllLines(java.nio.file.Paths.get("/proc/self/maps")))
            if(line.contains("/libart.so")||line.contains("/boot.oat"))System.out.println("ICU_ACTUAL_MAP="+line);
        Class<?> vm=Class.forName("java.lang.VMClassLoader");
        java.lang.reflect.Method entries=vm.getDeclaredMethod("getBootClassPathEntries");entries.setAccessible(true);
        for(String entry:(String[])entries.invoke(null))System.out.println("ICU_RESOURCE_INPUT="+entry);
        java.lang.reflect.Field name=Class.forName("android.icu.impl.ICUData").getDeclaredField("ICU_BASE_NAME");
        name.setAccessible(true);
        same("android/icu/impl/data/icudt63b",name.get(null));
        same("\u00e4",Normalizer.normalize("a\u0308",Normalizer.Form.NFC));
        same("A\u030a",Normalizer.normalize("\u00c5",Normalizer.Form.NFD));
        same("fi",Normalizer.normalize("\ufb01",Normalizer.Form.NFKD));
        same(true,Normalizer.isNormalized("\u00e4",Normalizer.Form.NFC));
        same(false,Normalizer.isNormalized("a\u0308",Normalizer.Form.NFC));
        android.icu.text.DecimalFormat numbers=new android.icu.text.DecimalFormat("#,##0.00",
                new android.icu.text.DecimalFormatSymbols(Locale.US));
        same("1,234.50",numbers.format(1234.5));
        same("en_US",android.icu.util.ULocale.forLocale(Locale.US).toString());
        same("USD",android.icu.util.Currency.getInstance(Locale.US).getCurrencyCode());
        android.icu.text.SimpleDateFormat date=new android.icu.text.SimpleDateFormat("yyyy-MM-dd",Locale.US);
        date.setTimeZone(android.icu.util.TimeZone.getTimeZone("UTC"));
        same("1970-01-01",date.format(new java.util.Date(0)));
        java.util.TimeZone original=java.util.TimeZone.getDefault();
        try {
            java.util.TimeZone.setDefault(new java.util.SimpleTimeZone(0,"GMT+00:00"));
            android.icu.util.TimeZone previous=android.icu.util.TimeZone.getDefault();
            same(0,previous.getRawOffset());
            java.util.TimeZone.setDefault(new java.util.SimpleTimeZone(2*3600000,"GMT+02:00"));
            same("GMT+02:00",android.icu.util.TimeZone.getDefault().getID());
            same(2*3600000,android.icu.util.TimeZone.getDefault().getRawOffset());
            same(0,previous.getRawOffset());
            java.util.TimeZone.setDefault(null);
            same(java.util.TimeZone.getDefault().getRawOffset(),android.icu.util.TimeZone.getDefault().getRawOffset());
        }finally{java.util.TimeZone.setDefault(original);}
        System.out.println("ICU_COMPATIBILITY=PASS|checks=15|data=icudt63b|normalization=actual|locale=actual|default_timezone_cache=actual");
    }
}
