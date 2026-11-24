import android.os.IDeviceIdentifiersPolicyService;
import android.os.Parcel;

/** Actual framework Binder interface and local Parcel dispatch boundary. */
public final class DeviceIdentifiersContract {
    private static int checks;
    private static void denied(IDeviceIdentifiersPolicyService service, String name,
                               boolean anonymous) throws Exception {
        try {
            String value = anonymous ? service.getSerial() : service.getSerialForPackage(name);
            throw new AssertionError("Identifier unexpectedly returned: " + value);
        } catch (SecurityException expected) {
            if (!expected.getMessage().contains("UID " + android.os.Process.myUid()))
                throw new AssertionError("Denial lacks actual caller identity", expected);
            checks++;
        }
    }
    public static void run() throws Exception {
        if (android.os.Process.myUid() == 0) throw new AssertionError("Ordinary UID required");
        IDeviceIdentifiersPolicyService service = IDeviceIdentifiersPolicyService.Stub.asInterface(
                SdDeviceIdentifiers.binder());
        denied(service, null, true);
        for (String name : new String[]{null, "", SdApkPackage.NAME, "android",
                "com.android.phone", "not.installed.owner"}) denied(service, name, false);
        // Exercise the generated original Stub's Parcel dispatch too. Local
        // Binder.transact propagates exceptions directly; only remote Binder
        // execTransact serializes them. Transaction IDs come from that Stub.
        Class<?> stub = IDeviceIdentifiersPolicyService.Stub.class;
        for (String method : new String[]{"getSerial", "getSerialForPackage"}) {
            java.lang.reflect.Field field = stub.getDeclaredField("TRANSACTION_" + method);
            field.setAccessible(true);
            Parcel request = Parcel.obtain(), reply = Parcel.obtain();
            try {
                request.writeInterfaceToken("android.os.IDeviceIdentifiersPolicyService");
                if (method.equals("getSerialForPackage")) request.writeString("android");
                try {
                    if (!SdDeviceIdentifiers.binder().transact(field.getInt(null), request, reply, 0))
                        throw new AssertionError("Actual AIDL transaction not handled");
                    reply.readException();
                    throw new AssertionError("Actual caller denial absent");
                } catch (SecurityException expected) {
                    if (!expected.getMessage().contains("UID " + android.os.Process.myUid()))
                        throw new AssertionError("Parcel denial lacks actual identity", expected);
                    checks++;
                }
            } finally { request.recycle(); reply.recycle(); }
        }
        System.err.println("DEVICE_IDENTIFIER_BOUNDARY=PASS|checks=" + checks
                + "|uid=" + android.os.Process.myUid()
                + "|parcel_dispatch=local|host_identifiers_read=false");
    }
}
