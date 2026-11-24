import java.net.IDN;

/** Root-label fallback, real ICU conversion and unchanged invalid-domain rejection. */
public final class IdnRootLabel254Contract {
    private static int checks;
    private static void eq(String actual,String expected) {
        checks++;
        if(!expected.equals(actual))throw new AssertionError("expected="+expected+" actual="+actual);
    }
    private static void invalid(String value,int flags) {
        try { IDN.toASCII(value,flags); }
        catch(IllegalArgumentException expected) { checks++; return; }
        throw new AssertionError("accepted invalid domain "+value);
    }
    public static void run(String ignored) {
        for(int flags=0;flags<4;flags++) {
            eq(IDN.toASCII(".",flags),".");
            eq(IDN.toUnicode(".",flags),".");
            eq(IDN.toASCII("example.com.",flags),"example.com.");
            eq(IDN.toASCII("bücher.example",flags),"xn--bcher-kva.example");
            eq(IDN.toUnicode("xn--bcher-kva.example",flags),"bücher.example");
            eq(IDN.toASCII("例え。テスト",flags),"xn--r8jz45g.xn--zckzah");
            eq(IDN.toUnicode("xn--r8jz45g。xn--zckzah",flags),"例え.テスト");
            invalid("example..com",flags);
            invalid(".example",flags);
            StringBuilder tooLong=new StringBuilder();for(int i=0;i<64;i++)tooLong.append('a');
            invalid(tooLong+".com",flags);
        }
        invalid("a_b.example",IDN.USE_STD3_ASCII_RULES);
        invalid("-leading.example",IDN.USE_STD3_ASCII_RULES);
        invalid("trailing-.example",IDN.USE_STD3_ASCII_RULES);
        for(int flags=0;flags<4;flags++) {
            try { IDN.toASCII(null,flags);throw new AssertionError("null accepted"); }
            catch(NullPointerException expected) { checks++; }
        }
        System.out.println("IDN_ROOT_LABEL254_CONTRACT=PASS|checks="+checks+"|backend=actual-ICU63|invalid_domains_rejected=true");
    }
}
