import java.time.LocalDate;
import java.time.chrono.JapaneseChronology;
import java.time.chrono.JapaneseDate;
import java.time.chrono.JapaneseEra;
import java.time.format.DateTimeFormatter;
import java.time.format.TextStyle;
import java.time.temporal.ChronoField;
import java.util.Locale;
public final class JavaTimeCompatibilityContract {
    static int checks;
    static void eq(Object actual, Object expected) {
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", actual " + actual);
        checks++;
    }
    public static void main(String[] args) throws Exception {
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(29);
        if (args[0].equals("eras")) {
            eq(JapaneseEra.values().length, 5);
            eq(JapaneseEra.of(3).toString(), "Reiwa");
            eq(JapaneseEra.valueOf("Reiwa"), JapaneseEra.of(3));
            eq(JapaneseChronology.INSTANCE.eraOf(3), JapaneseEra.of(3));
            eq(JapaneseDate.from(LocalDate.of(2019,4,30)).getEra(), JapaneseEra.HEISEI);
            eq(JapaneseDate.from(LocalDate.of(2019,5,1)).getEra(), JapaneseEra.of(3));
            eq(JapaneseDate.from(LocalDate.of(2019,5,1)).get(ChronoField.YEAR_OF_ERA), 1);
            eq(JapaneseDate.from(LocalDate.of(2020,1,6)).toString(), "Japanese Reiwa 2-01-06");
            eq(JapaneseDate.of(JapaneseEra.of(3),1,5,1).toEpochDay(), LocalDate.of(2019,5,1).toEpochDay());
            eq(JapaneseEra.of(3).getDisplayName(TextStyle.FULL, Locale.JAPAN), "令和");
            eq(JapaneseChronology.INSTANCE.range(ChronoField.ERA).getMaximum(), 3L);
            boolean denied = false;
            try { JapaneseEra.of(4); } catch (java.time.DateTimeException expected) { denied = true; }
            eq(denied,true);
        } else if (args[0].equals("quarters")) {
            eq(DateTimeFormatter.ofPattern("QQQ",Locale.UK).format(LocalDate.of(2020,1,6)),"Q1");
            eq(DateTimeFormatter.ofPattern("QQQQ",Locale.UK).format(LocalDate.of(2020,4,6)),"2nd quarter");
            eq(DateTimeFormatter.ofPattern("qqq",Locale.UK).format(LocalDate.of(2020,7,6)),"Q3");
            eq(DateTimeFormatter.ofPattern("qqqq",Locale.UK).format(LocalDate.of(2020,10,6)),"4th quarter");
            eq(DateTimeFormatter.ofPattern("Q",Locale.UK).format(LocalDate.of(2020,10,6)),"4");
            eq(DateTimeFormatter.ofPattern("QQQQ",Locale.FRANCE).format(LocalDate.of(2020,1,6)),"1er trimestre");
            eq(DateTimeFormatter.ofPattern("yyyy-MM-dd",Locale.UK).format(LocalDate.of(2020,1,6)),"2020-01-06");
        } else throw new AssertionError("Unknown case");
        System.out.println("JAVA_TIME_CONTRACT=PASS|case="+args[0]+"|checks="+checks+"|sdk="+dalvik.system.VMRuntime.getRuntime().getTargetSdkVersion());
    }
}
