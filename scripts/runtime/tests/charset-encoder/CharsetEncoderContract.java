import java.nio.*;
import java.nio.charset.*;
import java.util.*;

/** Independent real ICU encoding and CharsetEncoder state/ownership contract. */
public final class CharsetEncoderContract {
    private static int checks;
    private static void check(boolean value, String detail) {
        if (!value) throw new AssertionError(detail);
        checks++;
    }
    public static void run() throws Exception {
        Charset ascii = StandardCharsets.US_ASCII;
        Charset latin = StandardCharsets.ISO_8859_1;
        for (Charset charset : new Charset[] {ascii, latin}) {
            CharsetEncoder encoder = charset.newEncoder();
            for (int cp : new int[] {0x034f,0x061c,0x115f,0x1160,0x17b4,0x17b5,0x180b,
                    0x180c,0x180d,0x180e,0x200b,0x200c,0x200d,0x200e,0x200f,0x202a,
                    0x202b,0x202c,0x202d,0x202e,0x2060,0x2061,0x2062,0x2063,0x2064,
                    0x2066,0x2067,0x2068,0x2069,0xfe00,0xfe0f,0xfeff}) {
                String value = new String(Character.toChars(cp));
                check(encoder.canEncode(value), charset.name()+" ignorable U+"+Integer.toHexString(cp));
                ByteBuffer bytes = encoder.encode(CharBuffer.wrap(value));
                check(!bytes.hasRemaining(), "genuine zero-byte conversion");
                encoder.reset();
                check(encoder.canEncode("A"), "encoder reusable after zero-byte input");
            }
            check(!encoder.canEncode("\u4e2d"), "real unmappable input rejected");
            check(!encoder.canEncode("\ud800"), "malformed high surrogate rejected");
            check(!encoder.canEncode("\udc00"), "malformed low surrogate rejected");
            encoder.onMalformedInput(CodingErrorAction.IGNORE);
            encoder.onUnmappableCharacter(CodingErrorAction.REPLACE);
            encoder.canEncode("\u4e2d");
            check(encoder.malformedInputAction()==CodingErrorAction.IGNORE, "malformed action restored");
            check(encoder.unmappableCharacterAction()==CodingErrorAction.REPLACE, "unmappable action restored");
            encoder.reset();
            ByteBuffer output = encoder.encode(CharBuffer.wrap("ABC"));
            byte[] actual = new byte[output.remaining()]; output.get(actual);
            check(Arrays.equals(actual,new byte[]{65,66,67}), "real ordinary conversion");
        }
        CharsetEncoder encoder = ascii.newEncoder();
        byte[] replacement = new byte[]{63}; encoder.replaceWith(replacement); replacement[0]=33;
        check(encoder.replacement()[0]==63, "caller replacement array copied");
        byte[] returned = encoder.replacement(); returned[0]=64;
        check(encoder.replacement()[0]==63, "replacement getter copied");
        encoder.onUnmappableCharacter(CodingErrorAction.REPLACE);
        ByteBuffer result = encoder.encode(CharBuffer.wrap("\u4e2d"));
        check(result.remaining()==1 && result.get()==63, "actual ICU replacement matches retained copy");
        encoder.reset();
        CharBuffer input = CharBuffer.wrap("AZ"); input.position(1);
        check(encoder.canEncode(input) && input.position()==1, "canEncode preserves caller position");
        for (Charset charset : new Charset[]{ascii,latin,StandardCharsets.UTF_8,
                StandardCharsets.UTF_16,StandardCharsets.UTF_16BE,StandardCharsets.UTF_16LE}) {
            CharsetEncoder e = charset.newEncoder();
            check(e.canEncode(""), "empty fresh input");
            ByteBuffer bytes=ByteBuffer.allocate(32);
            check(e.encode(CharBuffer.wrap("A"),bytes,false).isUnderflow(), "actual streaming encoding");
            try { e.canEncode(""); throw new AssertionError("coding state accepted empty canEncode"); }
            catch (IllegalStateException expected) { checks++; }
            try { e.canEncode("A"); throw new AssertionError("coding state accepted canEncode"); }
            catch (IllegalStateException expected) { checks++; }
            e.reset();
            bytes.clear();
            check(e.encode(CharBuffer.wrap("A"),bytes,true).isUnderflow(), "actual end-of-input");
            check(e.flush(bytes).isUnderflow(), "actual flush");
            check(e.canEncode(""), "flushed encoder resets before empty input");
            check(e.canEncode("A"), "reusable after flush/reset");
            check(!e.canEncode("\ud800"), "all charsets reject malformed surrogate");
        }
        System.out.println("CHARSET_ENCODER_CONTRACT=PASS|checks="+checks
                +"|real_icu=true|zero_byte_conversion=true|malformed_rejected=true|defensive_copy=true|state_restored=true");
    }
}
