import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.pm.PackageParser;
import android.content.pm.ProviderInfo;
import android.os.Binder;
import android.os.Bundle;
import android.os.Parcel;

public final class SdReceiverProcess {
    private SdReceiverProcess() {}

    public static void start(String packageName, String receiver, String process) {
        if (!SdApkPackage.NAME.equals(packageName))
            throw new SecurityException("Receiver package differs from the hosted APK");
        ActivityInfo info = SdApkPackage.receiverInfo(new ComponentName(packageName, receiver), 0);
        if (info == null || !info.applicationInfo.enabled || !process.equals(info.processName))
            throw new SecurityException("Receiver process differs from its enabled declaration");
        for (PackageParser.Provider declared : SdApkPackage.parsed().providers) {
            ProviderInfo provider = declared.info;
            if (!provider.enabled || !provider.applicationInfo.enabled || provider.name == null
                    || !packageName.equals(provider.packageName)
                    || !process.equals(SdApkPackage.providerProcess(provider))) continue;
            org.saildroid.host.HostApi.startProviderProcess(packageName, provider.name, process);
            System.err.println("SDBROADCAST=receiver_process_bootstrap|provider=" + provider.name
                    + "|process=" + process);
            return;
        }
        throw new UnsupportedOperationException("Receiver process has no enabled declared provider bootstrap");
    }

    public static boolean dispatch(Parcel data, Parcel reply) {
        if (Binder.getCallingUid() != android.os.Process.myUid())
            throw new SecurityException("Receiver caller UID differs");
        String caller = data.readString();
        if (!SdApkPackage.NAME.equals(caller))
            throw new SecurityException("Receiver caller package differs");
        Intent intent = Intent.CREATOR.createFromParcel(data);
        int result = data.readInt();
        String resultData = data.readString();
        Bundle extras = data.readBundle();
        String[] permissions = data.createStringArray();
        int user = data.readInt();
        try {
            SdManifestReceivers.deliverLocal(intent, result, resultData, extras, permissions, user);
        } catch (RuntimeException failure) {
            throw failure;
        } catch (Exception failure) {
            throw new IllegalStateException("Manifest receiver dispatch failed", failure);
        }
        reply.writeNoException();
        return true;
    }
}
