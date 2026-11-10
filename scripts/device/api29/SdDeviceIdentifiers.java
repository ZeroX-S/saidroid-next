import android.os.Binder;
import android.os.IBinder;
import android.os.IDeviceIdentifiersPolicyService;

/** API29 identifier access boundary for hosted ordinary applications.
 *
 * The current host has no Android privileged-phone-state grants, carrier
 * privileges, device/profile owners, identifier AppOp grants or dangerous
 * READ_PHONE_STATE grant backend. Android10 rejects these callers, including
 * pre-Q callers without an actual READ_PHONE_STATE grant. Declaring a permission
 * in an APK, choosing a package name or running under Sailfish's UID100000 does
 * not confer Android system identity. No host serial/IMEI/MEID is read here.
 *
 * This opt-in service is kept outside the frozen192/193 product sources until
 * its independent ordinary-UID and original-APK regressions complete.
 */
public final class SdDeviceIdentifiers extends IDeviceIdentifiersPolicyService.Stub {
    private static final SdDeviceIdentifiers INSTANCE = new SdDeviceIdentifiers();
    private SdDeviceIdentifiers() {}
    public static IBinder binder() { return INSTANCE; }
    private static String denied(String callingPackage) {
        // These are kernel Binder credentials, never an APK-supplied UID. Do not
        // apply Android's UID modulo to native Sailfish account identities.
        int caller = Binder.getCallingUid();
        throw new SecurityException("getSerial: UID " + caller
                + " has no supported Android device-identifier access grant");
    }
    @Override public String getSerial() { return denied(null); }
    @Override public String getSerialForPackage(String callingPackage) {
        return denied(callingPackage);
    }
}
