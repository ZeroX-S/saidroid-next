import android.content.ComponentName;
import android.content.pm.IPackageManager;
import android.content.pm.InstrumentationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;

/** Independent contract: reads declarations from the unmodified original APK. */
public final class InstrumentationMetadata260Contract {
    static int checks;
    static void check(boolean value, String name) {
        if (!value) throw new AssertionError(name);
        checks++;
    }
    public static void run(String apk, String data, String nativeDir) throws Exception {
        System.setProperty("saidroid.package", "android.libcore.cts");
        System.setProperty("saidroid.apk", apk);
        System.setProperty("saidroid.data", data);
        System.setProperty("saidroid.native", nativeDir);
        ComponentName name = new ComponentName("android.libcore.cts", "androidx.test.runner.AndroidJUnitRunner");
        IPackageManager pm = (IPackageManager) Class.forName("SdPackageManagerService").getMethod("service").invoke(null);
        InstrumentationInfo no = pm.getInstrumentationInfo(name, 0);
        check(no != null && no.metaData == null, "metadata must be absent without GET_META_DATA");
        InstrumentationInfo yes = pm.getInstrumentationInfo(name, PackageManager.GET_META_DATA);
        check(yes != null && yes.metaData != null, "declared instrumentation metadata must be returned");
        check("com.android.cts.runner.CtsTestRunListener".equals(yes.metaData.getString("listener")), "exact APK-declared listener");
        check(yes.name.equals(no.name) && yes.packageName.equals(no.packageName), "component identity preserved");
        check(yes.sourceDir.equals(apk) && yes.dataDir.equals(data) && yes.nativeLibraryDir.equals(nativeDir), "installation paths preserved");
        yes.metaData.putString("listener", "independent-contract-mutation");
        yes.metaData.putString("contract-added", "private");
        InstrumentationInfo again = pm.getInstrumentationInfo(name, PackageManager.GET_META_DATA);
        check(again != yes && again.metaData != yes.metaData, "fresh result and defensive bundle copy");
        check("com.android.cts.runner.CtsTestRunListener".equals(again.metaData.getString("listener")) && !again.metaData.containsKey("contract-added"), "returned bundle mutation cannot affect declarations");
        check(pm.getInstrumentationInfo(new ComponentName("absent.contract.package", name.getClassName()), PackageManager.GET_META_DATA) == null, "unknown package");
        check(pm.getInstrumentationInfo(new ComponentName(name.getPackageName(), "absent.contract.Runner"), PackageManager.GET_META_DATA) == null, "unknown component");
        PackageInfo plain = pm.getPackageInfo(name.getPackageName(), 0, 0);
        check(plain.instrumentation == null, "GET_INSTRUMENTATION required");
        PackageInfo list = pm.getPackageInfo(name.getPackageName(), PackageManager.GET_INSTRUMENTATION, 0);
        check(list.instrumentation != null && list.instrumentation.length == 1 && list.instrumentation[0].metaData == null, "package info metadata flag required");
        PackageInfo full = pm.getPackageInfo(name.getPackageName(), PackageManager.GET_INSTRUMENTATION | PackageManager.GET_META_DATA, 0);
        check(full.instrumentation.length == 1 && "com.android.cts.runner.CtsTestRunListener".equals(full.instrumentation[0].metaData.getString("listener")), "package info propagates metadata flag");
        full.instrumentation[0].metaData.clear();
        check("com.android.cts.runner.CtsTestRunListener".equals(pm.getPackageInfo(name.getPackageName(), PackageManager.GET_INSTRUMENTATION | PackageManager.GET_META_DATA, 0).instrumentation[0].metaData.getString("listener")), "package info defensive copy");
        InstrumentationInfo legacy = (InstrumentationInfo) Class.forName("SdInstrumentation").getMethod("info", ComponentName.class).invoke(null, name);
        check(legacy != null && legacy.metaData == null, "legacy method ABI and no-metadata default");
        System.out.println("INSTRUMENTATION_METADATA260_CONTRACT=PASS|checks=" + checks + "|uid=" + android.system.Os.getuid());
    }
}
