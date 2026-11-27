package org.example.saildroid.devicemodel;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.widget.TextView;

/** Compare public Build fields with the actual native command in an APK host. */
public final class DeviceModelActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        final TextView view = new TextView(this);
        view.setTextSize(24);
        view.setPadding(40, 90, 40, 40);
        view.setText("Checking public hardware identity");
        setContentView(view);
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    String[] names = {"manufacturer", "brand", "model", "name", "device"};
                    String[] values = {Build.MANUFACTURER, Build.BRAND, Build.MODEL,
                                       Build.PRODUCT, Build.DEVICE};
                    StringBuilder report = new StringBuilder();
                    for (int i = 0; i < names.length; i++) {
                        Process command = new ProcessBuilder(System.getenv("ANDROID_ROOT")
                                + "/bin/getprop", "ro.product." + names[i]).start();
                        java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
                        byte[] block = new byte[256];
                        int count;
                        while ((count = command.getInputStream().read(block)) != -1)
                            bytes.write(block, 0, count);
                        String nativeValue = new String(bytes.toByteArray(), "UTF-8").trim();
                        if (command.waitFor() != 0 || !values[i].equals(nativeValue))
                            throw new AssertionError("Build/native mismatch: " + names[i]);
                        System.out.println("DEVICE_MODEL_APK=field|name=" + names[i]
                                + "|value=" + values[i] + "|native=" + nativeValue);
                        report.append(names[i]).append(": ").append(values[i]).append('\n');
                    }
                    final String text = report.toString();
                    runOnUiThread(new Runnable() {
                        @Override public void run() {
                            view.setText(text);
                            System.out.println("DEVICE_MODEL_APK=passed|sdk="
                                    + getApplicationInfo().targetSdkVersion);
                        }
                    });
                } catch (Throwable failure) {
                    System.out.println("DEVICE_MODEL_APK=failed|" + failure);
                    failure.printStackTrace();
                }
            }
        }, "device-model-contract").start();
    }
}
