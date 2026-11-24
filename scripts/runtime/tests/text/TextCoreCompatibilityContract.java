import java.io.*;
import java.math.*;
import java.text.*;
import java.util.*;
/** Behavioral contract for the original Android10 ICU adapter/symbol boundary. */
public final class TextCoreCompatibilityContract {
 private static int checked;
 private static void equal(Object expected,Object actual) { if(!expected.equals(actual))throw new AssertionError("expected="+expected+" actual="+actual);checked++; }
 public static void main(String[] args) throws Exception {
  dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(29);
  equal("63.2",libcore.icu.ICU.getIcuVersion());
  equal(63,android.icu.util.VersionInfo.ICU_VERSION.getMajor());
  DecimalFormatSymbols us=new DecimalFormatSymbols(Locale.US);
  DecimalFormat currency=new DecimalFormat("¤¤0",us);currency.setCurrency(Currency.getInstance("USD"));currency.setMinimumFractionDigits(0);currency.setMaximumFractionDigits(0);
  equal("USD12",currency.format(12));equal("-USD12",currency.format(-12));
  java.lang.reflect.Field field=DecimalFormat.class.getDeclaredField("icuDecimalFormat");field.setAccessible(true);
  equal("android.icu.text.DecimalFormat_ICU58_Android",field.get(currency).getClass().getName());
  us.setGroupingSeparator(' ');us.setPerMill(';');
  DecimalFormat grouped=new DecimalFormat("#,##0.00",us);equal("1 234.50",grouped.format(1234.5));
  DecimalFormat money=new DecimalFormat("¤#,##0.00",us);equal("$1 234.50",money.format(1234.5));
  DecimalFormat permill=new DecimalFormat("0.0‰",us);equal("125.0;",permill.format(0.125));
  DecimalFormat arabic=new DecimalFormat("+0;-0",new DecimalFormatSymbols(Locale.forLanguageTag("ar-EG")));
  equal("+١٢٣",arabic.format(123));
  equal(Character.valueOf('\u061b'),Character.valueOf(arabic.getDecimalFormatSymbols().getPatternSeparator()));
  DecimalFormat localized=(DecimalFormat)NumberFormat.getInstance(Locale.forLanguageTag("ar-EG"));
  localized.applyLocalizedPattern("'AAA'+\u0660\u061b'BBB'-\u0660");equal("BBB-١٢٣",localized.format(-123));
  equal("'AAA'+#٠؛'BBB'-#٠",localized.toLocalizedPattern());
  DecimalFormat rounding=new DecimalFormat("0.00",new DecimalFormatSymbols(Locale.US));rounding.setRoundingMode(RoundingMode.HALF_EVEN);
  equal("2.34",rounding.format(new BigDecimal("2.345")));equal("2.36",rounding.format(new BigDecimal("2.355")));
  rounding.setParseBigDecimal(true);equal(new BigDecimal("1234.50"),rounding.parse("1234.50"));
  DecimalFormat clone=(DecimalFormat)money.clone();DecimalFormatSymbols symbols=clone.getDecimalFormatSymbols();symbols.setGroupingSeparator('_');clone.setDecimalFormatSymbols(symbols);equal("$1_234.50",clone.format(1234.5));equal("$1 234.50",money.format(1234.5));
  // Use the platform-supported numeric serialization shape. The historical
  // Android writer drops currency affix patterns; the separate strict currency
  // equality diagnostic remains recorded as a pre-existing limitation.
  DecimalFormat serial=(DecimalFormat)grouped.clone();
  ByteArrayOutputStream bytes=new ByteArrayOutputStream();ObjectOutputStream output=new ObjectOutputStream(bytes);output.writeObject(serial);output.close();DecimalFormat restored=(DecimalFormat)new ObjectInputStream(new ByteArrayInputStream(bytes.toByteArray())).readObject();equal(serial,restored);equal("1 234.50",restored.format(1234.5));equal(serial.getRoundingMode(),restored.getRoundingMode());
  DecimalFormatSymbols posix=new DecimalFormatSymbols(Locale.forLanguageTag("en-US-POSIX"));
  equal(Character.valueOf('\u2030'),Character.valueOf(posix.getPerMill()));
  equal("100\u2030",new DecimalFormat("0\u2030",posix).format(0.1));
  SimpleDateFormat dayPeriod=new SimpleDateFormat("b B",Locale.US);dayPeriod.setTimeZone(TimeZone.getTimeZone("UTC"));equal(" ",dayPeriod.format(new Date(0)));
  SimpleDateFormat utcName=new SimpleDateFormat("zzzz",Locale.US);utcName.setTimeZone(TimeZone.getTimeZone("UTC"));equal("Coordinated Universal Time",utcName.format(new Date(0)));
  SimpleDateFormat year=new SimpleDateFormat("HH:mm:ss MM/dd/yy",Locale.US);year.setTimeZone(TimeZone.getTimeZone("UTC"));year.set2DigitYearStart(new Date(0));Date parsedYear=year.parse("09:07:06 05/04/\t03");Calendar calendar=Calendar.getInstance(TimeZone.getTimeZone("UTC"),Locale.US);calendar.setTime(parsedYear);equal(2003,calendar.get(Calendar.YEAR));equal(Calendar.MAY,calendar.get(Calendar.MONTH));equal(4,calendar.get(Calendar.DAY_OF_MONTH));
  for(Locale locale:new Locale[]{Locale.US,Locale.GERMANY,Locale.FRANCE,Locale.JAPAN,Locale.forLanguageTag("ar-EG"),Locale.forLanguageTag("hi-IN"),Locale.forLanguageTag("fa-IR"),Locale.forLanguageTag("th-TH")}) {
   DecimalFormat format=(DecimalFormat)NumberFormat.getNumberInstance(locale);format.setGroupingUsed(false);format.setMinimumFractionDigits(2);format.setMaximumFractionDigits(2);format.setParseBigDecimal(true);
   String text=format.format(new BigDecimal("1234.50"));ParsePosition pos=new ParsePosition(0);Number parsed=format.parse(text,pos);equal(new BigDecimal("1234.50"),parsed);equal(text.length(),pos.getIndex());equal(-1,pos.getErrorIndex());
  }
  System.out.println("TEXT_CORE_COMPATIBILITY_CONTRACT=PASS|checks="+checked+"|uid="+android.system.Os.getuid());
 }
}
