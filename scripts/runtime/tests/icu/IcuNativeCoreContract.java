import java.nio.charset.Charset;
import java.util.Arrays;
import java.util.Locale;
import java.util.regex.Pattern;

/** Real libcore JNI/data behavior, separate from the original CTS results. */
public final class IcuNativeCoreContract {
    private static void same(Object expected,Object actual){if(!expected.equals(actual))throw new AssertionError("Expected "+expected+", actual "+actual);}
    public static void main(String[] args)throws Exception {
        String nativeVersion=libcore.icu.ICU.getIcuVersion();
        String unicode=libcore.icu.ICU.getUnicodeVersion();
        String cldr=libcore.icu.ICU.getCldrVersion();
        System.out.println("ICU_NATIVE_VERSION="+nativeVersion+"|unicode="+unicode+"|cldr="+cldr);
        same("63.2",nativeVersion);
        same("11.0",unicode);same("34.0",cldr);
        same("63.2.0.0",android.icu.util.VersionInfo.ICU_VERSION.toString());
        same("French",Locale.FRENCH.getDisplayLanguage(Locale.ENGLISH));
        same("fra",libcore.icu.ICU.getISO3Language("fr"));
        same(0,libcore.icu.ICU.getCurrencyFractionDigits("JPY"));
        same(840,libcore.icu.ICU.getCurrencyNumericCode("USD"));
        String value="English 中文 😀";
        same(value,new String(value.getBytes("UTF-8"),"UTF-8"));
        same("中文",new String("中文".getBytes(Charset.forName("GB18030")),Charset.forName("GB18030")));
        same(true,Pattern.compile("\\p{L}+").matcher("中文").matches());
        same(false,Pattern.compile("\\p{L}+").matcher("123").matches());
        same("en-Latn-US",libcore.icu.ICU.addLikelySubtags("en").replace('_','-'));
        String maps=new String(java.nio.file.Files.readAllBytes(java.nio.file.Paths.get("/proc/self/maps")),"UTF-8");
        String expectedLibrary=args.length==0?"/var/tmp/saidroid-javacore-icu63-20261031-v2/libjavacore.so":args[0];
        if(!maps.contains(expectedLibrary))throw new AssertionError("Expected JNI library is not actually mapped: "+expectedLibrary);
        if(!maps.contains("libicuuc.so.63.2"))throw new AssertionError("Real ICU63 is not actually mapped");
        for(String line:maps.split("\n"))if(line.contains("libjavacore.so")||line.contains("libicuuc.so.63")||line.contains("libicui18n.so.63"))System.out.println("ICU_NATIVE_MAP="+line);
        IcuCompatibilityContract.main(new String[0]);
        System.out.println("ICU_NATIVE_CORE_CONTRACT=PASS|real_native_data_and_regex=true|private_icu63_mapped=true");
    }
}
