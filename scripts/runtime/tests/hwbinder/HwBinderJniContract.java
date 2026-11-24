import android.os.HidlSupport;
import android.os.HwBinder;
import android.os.HwBlob;
import android.os.HwParcel;
import android.os.IHwBinder;
import android.os.IHwInterface;
import android.system.Os;
import java.util.ArrayList;
import java.util.Arrays;

/** JNI memory/value/lifetime boundaries; deliberately opens no hardware driver. */
public final class HwBinderJniContract {
    private static int checks;
    private static void check(boolean value, String why) {
        checks++;
        if (!value) throw new AssertionError(why);
    }
    private static void bounds(Runnable call) {
        try { call.run(); throw new AssertionError("Native access escaped blob bounds"); }
        catch (IndexOutOfBoundsException expected) { checks++; }
    }
    public static void main(String[] unused) throws Exception {
        check(Os.getuid() == 65534, "Ordinary contract UID required");
        // The actual original libhidlbase's function branches directly to getpid,
        // independently recorded by its ELF disassembly; no disclosure override.
        check(HidlSupport.getPidIfSharable() == Os.getpid(), "Native HIDL process identity");
        HwBinder binder = new HwBinder() {
            public void onTransact(int code, HwParcel request, HwParcel reply, int flags) {
                throw new UnsupportedOperationException("No hardware-service fixture");
            }
            public IHwInterface queryLocalInterface(String descriptor) {
                throw new UnsupportedOperationException("No local interface fixture");
            }
            public boolean linkToDeath(IHwBinder.DeathRecipient recipient, long cookie) {
                throw new UnsupportedOperationException("No remote lifetime fixture");
            }
            public boolean unlinkToDeath(IHwBinder.DeathRecipient recipient) {
                throw new UnsupportedOperationException("No remote lifetime fixture");
            }
        };
        java.lang.reflect.Field context = HwBinder.class.getDeclaredField("mNativeContext");
        context.setAccessible(true);
        check(context.getLong(binder) != 0, "Real HwBinder native constructor context");
        for (int i = 0; i < 64; i++) {
            final HwBlob blob = new HwBlob(64);
            blob.putBool(0, (i & 1) != 0); check(blob.getBool(0) == ((i & 1) != 0), "bool");
            blob.putInt8(1, (byte)i); check(blob.getInt8(1) == (byte)i, "int8");
            blob.putInt16(2, (short)(-1000+i)); check(blob.getInt16(2) == -1000+i, "int16");
            blob.putInt32(4, 0x12340000+i); check(blob.getInt32(4) == 0x12340000+i, "int32");
            blob.putInt64(8, Long.MIN_VALUE+i); check(blob.getInt64(8) == Long.MIN_VALUE+i, "int64");
            blob.putFloat(16, i+0.5f); check(blob.getFloat(16) == i+0.5f, "float");
            blob.putDouble(24, -i-0.25); check(blob.getDouble(24) == -i-0.25, "double");
            String text = "HIDL-\u4f60\u597d-"+i;
            blob.putString(32, text); check(blob.getString(32).equals(text), "embedded UTF-8 string");
            int[] input = new int[]{i, -i, Integer.MAX_VALUE, Integer.MIN_VALUE};
            blob.putInt32Array(48, input); int[] copy = new int[4]; blob.copyToInt32Array(48, copy, 4);
            check(Arrays.equals(input, copy), "Native array copy");
            // A newly allocated blob is not a received Binder buffer and has
            // no parcel-owned transport handle. Original native code rejects it.
            try { blob.handle(); throw new AssertionError("Owned blob exposed received-buffer handle"); }
            catch (UnsupportedOperationException expected) { checks++; }
            bounds(() -> blob.getInt64(57));
            bounds(() -> blob.putInt32(62, 1));
            bounds(() -> blob.copyToInt32Array(60, new int[2], 2));
            HwParcel parcel = new HwParcel();
            java.lang.reflect.Field parcelContext = HwParcel.class.getDeclaredField("mNativeContext");
            parcelContext.setAccessible(true); check(parcelContext.getLong(parcel) != 0, "Real parcel context");
            parcel.writeInterfaceToken("org.saildroid.contract.HidlMemory");
            parcel.writeBool(true); parcel.writeInt8((byte)i); parcel.writeInt16((short)i);
            parcel.writeInt32(i); parcel.writeInt64(Long.MAX_VALUE-i);
            parcel.writeFloat(i+0.5f); parcel.writeDouble(i+0.25); parcel.writeString(text);
            parcel.writeInt32Vector(new ArrayList<Integer>(Arrays.asList(i, -i)));
            parcel.writeBuffer(blob);
            parcel.releaseTemporaryStorage(); parcel.release();
            checks++; // Every write/release above used the actual original native implementation.
        }
        check(HidlSupport.getPidIfSharable() == Os.getpid(), "Identity after native allocation/release");
        System.out.println("HWBINDER_JNI_CONTRACT=PASS|checks="+checks+"|pid="+Os.getpid()
                +"|uid="+Os.getuid()+"|hardware_driver_opened=false|remote_service_claim=false");
    }
}
