import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Independent Android10 replacement syntax/lifecycle contract; no CTS class replacement. */
public final class RegexReplacement248Contract {
    private static int checks;
    private static void equal(String actual,String expected) {
        checks++;
        if(!expected.equals(actual))throw new AssertionError("expected=["+expected+"] actual=["+actual+"]");
    }
    private static void fail(String replacement,Class<? extends Throwable> type,String message) {
        Matcher matcher=Pattern.compile("(?<letter>a)(b)").matcher("ab");
        if(!matcher.find())throw new AssertionError("fixture match");
        try { matcher.appendReplacement(new StringBuffer(),replacement); }
        catch(Throwable error) {
            checks++;
            if(!type.isInstance(error))throw new AssertionError("wrong exception for "+replacement,error);
            if(message!=null)equal(error.getMessage(),message);
            // A malformed replacement must not poison later matching after reset.
            equal(matcher.reset("zabz").replaceAll("[$2$1]"),"z[ba]z");
            return;
        }
        throw new AssertionError("missing exception for "+replacement);
    }
    public static void run(String ignored) {
        equal(Pattern.compile("(a)(b)").matcher("xab ab!").replaceAll("$2$1"),"xba ba!");
        equal(Pattern.compile("(a)(b)").matcher("xab ab!").replaceFirst("[$0]"),"x[ab] ab!");
        equal(Pattern.compile("(?<left>a)(?<right>b)").matcher("ab").replaceAll("${right}${left}"),"ba");
        equal(Pattern.compile("(a)").matcher("a").replaceAll("$12"),"a2");
        equal(Pattern.compile("(a)").matcher("a").replaceAll("$0"),"a");
        equal(Pattern.compile("a").matcher("aa").replaceAll("\\$"),"$$");
        equal(Pattern.compile("a").matcher("a").replaceAll("\\\\"),"\\");
        equal(Pattern.compile("a").matcher("a").replaceAll("\\x"),"x");
        equal(Pattern.compile("a").matcher("a").replaceAll(""),"");
        String literal="$1\\${left}";
        equal(Pattern.compile("a").matcher("a").replaceAll(Matcher.quoteReplacement(literal)),literal);
        Matcher stream=Pattern.compile("(?<word>[a-z]+)").matcher("one, two!");
        StringBuffer output=new StringBuffer();
        if(!stream.find())throw new AssertionError();
        stream.appendReplacement(output,"[${word}]");
        if(!stream.find())throw new AssertionError();
        stream.appendReplacement(output,"<$0>");
        stream.appendTail(output);
        equal(output.toString(),"[one], <two>!");
        equal(stream.reset("three?").replaceAll("<$0>"),"<three>?");
        equal(Pattern.compile("a").matcher("bbb").replaceAll("$"),"bbb");
        fail("\\",IllegalArgumentException.class,"character to be escaped is missing");
        fail("$",IllegalArgumentException.class,"Illegal group reference: group index is missing");
        fail("prefix\\",IllegalArgumentException.class,"character to be escaped is missing");
        fail("prefix$",IllegalArgumentException.class,"Illegal group reference: group index is missing");
        fail("${letter",IllegalArgumentException.class,"Illegal group reference: group index is missing");
        fail("${absent}",IllegalArgumentException.class,null);
        fail("$9",IndexOutOfBoundsException.class,null);
        System.out.println("REGEX_REPLACEMENT248_CONTRACT=PASS|checks="+checks+"|backend=actual-android10-matcher|cts_replaced=false");
    }
}
