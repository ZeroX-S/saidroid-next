import java.util.Arrays;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** API behavior and compatibility boundary checks on the actual ART core. */
public final class RegexCompatibilityContract {
    private static void invalidGroup(Matcher matcher, int group, int operation) {
        try {
            if (operation == 0) matcher.start(group);
            else if (operation == 1) matcher.end(group);
            else matcher.group(group);
            throw new AssertionError("Invalid group accepted: " + group);
        } catch (IndexOutOfBoundsException expected) {
            if (expected.getClass() != IndexOutOfBoundsException.class)
                throw new AssertionError("Internal array exception escaped", expected);
        }
    }
    public static void main(String[] args) {
        int sdk = Integer.parseInt(args[0]);
        dalvik.system.VMRuntime.getRuntime().setTargetSdkVersion(sdk);
        Matcher matcher = Pattern.compile("(a)(b)?").matcher("a");
        if (!matcher.matches() || matcher.start(0) != 0 || matcher.end(1) != 1
                || !"a".equals(matcher.group(1)) || matcher.group(2) != null)
            throw new AssertionError("Valid capture semantics changed");
        for (int group : new int[]{-1, 3, Integer.MIN_VALUE, Integer.MAX_VALUE})
            for (int operation = 0; operation < 3; operation++) invalidGroup(matcher, group, operation);
        try {
            Pattern.compile("missing").matcher("a").replaceFirst(null);
            throw new AssertionError("Null replacement accepted without a match");
        } catch (NullPointerException expected) { }
        Matcher unattempted = Pattern.compile("a").matcher("a");
        try {
            unattempted.start(-1);
            throw new AssertionError("Unattempted matcher accepted");
        } catch (IllegalStateException expected) { }
        String[] actual = Pattern.compile("").split("ab", -1);
        String[] expected = sdk > 28 ? new String[]{"a", "b", ""} : new String[]{"", "a", "b", ""};
        if (!Arrays.equals(actual, expected))
            throw new AssertionError("SDK split boundary: " + Arrays.toString(actual));
        if (!Arrays.equals(Pattern.compile(":").split("a:b:", -1), new String[]{"a", "b", ""}))
            throw new AssertionError("Positive-width delimiters changed");
        System.out.println("REGEX_COMPATIBILITY=PASS|targetSdk=" + sdk + "|split=" + Arrays.toString(actual));
    }
}
