package org.example.saildroid.api28microphone;

import android.app.Activity;
import android.app.AppOpsManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.net.Uri;
import android.os.Bundle;
import android.os.Process;
import android.provider.Settings;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicInteger;

/** Normal APK regression. Raw microphone samples are discarded after counting. */
public final class MicrophoneActivity extends Activity {
    private static final String MIC = "android.permission.RECORD_AUDIO";
    private int attempts;
    private TextView status;
    private AudioRecord retained;

    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        status = new TextView(this);
        content.addView(status);
        button(content, "microphone", "Request microphone").setOnClickListener(view -> requestMic());
        button(content, "settings", "Microphone permissions").setOnClickListener(view ->
                startActivityForResult(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.parse("package:" + getPackageName())), 80));
        setContentView(content);
        require(getPackageManager().hasSystemFeature(PackageManager.FEATURE_MICROPHONE), "Physical microphone feature missing");
        if (getPreferences(0).getBoolean("tested", false)) {
            verifyPermission(false);
            deniedRecording();
            System.err.println("API28_MIC=persistence_passed");
        } else {
            verifyPermission(false);
            deniedRecording();
            requestMic();
        }
    }

    private Button button(LinearLayout content, String name, String title) {
        Button button = new Button(this);
        button.setText(title);
        content.addView(button);
        button.post(() -> {
            int[] point = new int[2];
            button.getLocationOnScreen(point);
            System.err.println("API28_MIC=button|name=" + name + "|x="
                    + (point[0] + button.getWidth() / 2) + "|y=" + (point[1] + button.getHeight() / 2));
        });
        return button;
    }

    private void requestMic() {
        attempts++;
        requestPermissions(new String[]{MIC}, 70 + attempts);
    }

    private void verifyPermission(boolean granted) {
        int expected = granted ? PackageManager.PERMISSION_GRANTED : PackageManager.PERMISSION_DENIED;
        require(checkSelfPermission(MIC) == expected, "Activity grant differs");
        require(getPackageManager().checkPermission(MIC, getPackageName()) == expected, "Package grant differs");
        AppOpsManager operations = (AppOpsManager) getSystemService(APP_OPS_SERVICE);
        require(operations.checkOpNoThrow(AppOpsManager.OPSTR_RECORD_AUDIO, Process.myUid(), getPackageName())
                == (granted ? AppOpsManager.MODE_ALLOWED : AppOpsManager.MODE_IGNORED), "Microphone AppOps differs");
    }

    private AudioRecord create(int rate, int mask, int encoding) {
        int minimum = AudioRecord.getMinBufferSize(rate, mask, encoding);
        require(minimum > 0, "Minimum buffer unavailable");
        AudioRecord record = new AudioRecord(MediaRecorder.AudioSource.MIC, rate, mask, encoding, minimum * 2);
        require(record.getState() == AudioRecord.STATE_INITIALIZED, "Recorder not initialized");
        require(record.getBufferSizeInFrames() > 0, "Frame buffer missing");
        return record;
    }

    private void deniedRecording() {
        AudioRecord record = null;
        boolean denied = false;
        try {
            record = new AudioRecord(MediaRecorder.AudioSource.MIC, 16000, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, 4096);
            denied = record.getState() == AudioRecord.STATE_UNINITIALIZED;
        } catch (SecurityException expected) { denied = true; }
        finally { if (record != null) record.release(); }
        require(denied, "Unauthorized recorder initialized");
    }

    @Override public void onRequestPermissionsResult(int code, String[] names, int[] results) {
        super.onRequestPermissionsResult(code, names, results);
        require(code == 70 + attempts && names.length == 1 && MIC.equals(names[0]), "Microphone callback differs");
        if (attempts == 1) {
            require(results[0] == PackageManager.PERMISSION_DENIED && shouldShowRequestPermissionRationale(MIC), "Denial not recorded");
            verifyPermission(false);
            deniedRecording();
            System.err.println("API28_MIC=denial_passed");
        } else {
            require(attempts == 2 && results[0] == PackageManager.PERMISSION_GRANTED, "Reauthorization failed");
            verifyPermission(true);
            new Thread(() -> {
                try {
                    captureTests();
                    runOnUiThread(() -> status.setText("Capture passed. Revoke microphone in permissions."));
                    System.err.println("API28_MIC=capture_passed|raw_audio_retained=false");
                } catch (Throwable failure) {
                    failure.printStackTrace();
                    System.err.println("API28_MIC=failed|type=" + failure.getClass().getName());
                }
            }, "Microphone regression").start();
        }
    }

    private void captureTests() throws Exception {
        AudioManager manager = (AudioManager) getSystemService(AUDIO_SERVICE);
        require(!manager.isMicrophoneMute(), "Physical microphone incorrectly reported muted");
        try (RecorderScope scope = new RecorderScope(create(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT))) {
            AudioRecord record = scope.record;
            record.startRecording();
            require(record.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING, "Capture start failed");
            short[] samples = new short[8000];
            int count = record.read(samples, 0, samples.length, AudioRecord.READ_BLOCKING);
            require(count > 0, "Empty short capture");
            long squares = 0;
            int peak = 0;
            for (int index = 0; index < count; index++) {
                peak = Math.max(peak, Math.abs((int) samples[index]));
                squares += (long) samples[index] * samples[index];
            }
            require(peak > 0, "Physical capture produced only zeros");
            require(record.getRoutedDevice() != null && record.getRoutedDevice().isSource(), "Physical input route missing");
            System.err.println("API28_MIC=shorts|samples=" + count + "|peak=" + peak + "|rms=" + Math.sqrt((double) squares / count));
            require(record.read(samples, -1, 10) == AudioRecord.ERROR_BAD_VALUE, "Invalid offset accepted");
            record.stop();
            record.startRecording();
            require(record.read(samples, 0, 1000) > 0, "Restart lost capture or retained stale peek offset");
            record.stop();
            record.startRecording();
            AtomicInteger returned = new AtomicInteger(-999);
            Thread reader = new Thread(() -> returned.set(record.read(new short[32768], 0, 32768)));
            reader.start();
            Thread.sleep(20);
            record.stop();
            reader.join(1500);
            require(!reader.isAlive() && returned.get() >= 0, "Stop did not interrupt blocking read");
            record.startRecording();
            Thread releasing = new Thread(() -> returned.set(record.read(new short[32768], 0, 32768)));
            releasing.start();
            Thread.sleep(20);
            record.release();
            releasing.join(1500);
            require(!releasing.isAlive(), "Release did not interrupt blocking read");
            System.err.println("API28_MIC=lifecycle_passed|restart=true|stop_interrupt=true|release_interrupt=true");
        }
        for (int encoding : new int[]{AudioFormat.ENCODING_PCM_8BIT, AudioFormat.ENCODING_PCM_16BIT}) {
            try (RecorderScope scope = new RecorderScope(create(48000, AudioFormat.CHANNEL_IN_STEREO, encoding))) {
                scope.record.startRecording();
                byte[] samples = new byte[4096];
                int count = scope.record.read(samples, 0, samples.length);
                require(count > 0 && count % (encoding == AudioFormat.ENCODING_PCM_16BIT ? 4 : 2) == 0, "Byte capture lost frame alignment");
                ByteBuffer direct = ByteBuffer.allocateDirect(4096);
                require(scope.record.read(direct, direct.capacity()) > 0, "Direct buffer capture empty");
                require(scope.record.read(direct, direct.capacity(), AudioRecord.READ_NON_BLOCKING) >= 0, "Nonblocking read failed");
                System.err.println("API28_MIC=bytes_direct_passed|encoding=" + encoding + "|bytes=" + count);
            }
        }
        try (RecorderScope scope = new RecorderScope(create(44100, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT))) {
            scope.record.startRecording();
            float[] samples = new float[2048];
            int count = scope.record.read(samples, 0, samples.length, AudioRecord.READ_BLOCKING);
            require(count > 0, "Float capture empty");
            for (int index = 0; index < count; index++) require(!Float.isNaN(samples[index]) && !Float.isInfinite(samples[index]), "Invalid float sample");
            require(scope.record.read(new byte[128], 0, 128) == AudioRecord.ERROR_INVALID_OPERATION, "Float recorder accepted byte array");
            System.err.println("API28_MIC=float_passed|samples=" + count);
        }
        retained = create(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        retained.startRecording();
        require(retained.read(new short[1024], 0, 1024) > 0, "Retained capture failed");
    }

    @Override public void onActivityResult(int code, int resultCode, Intent value) {
        super.onActivityResult(code, resultCode, value);
        require(code == 80 && resultCode == RESULT_OK, "Permission settings callback differs");
        verifyPermission(false);
        boolean denied = false;
        try { denied = retained.read(new short[128], 0, 128) < 0; }
        catch (SecurityException expected) { denied = true; }
        finally { retained.release(); retained = null; }
        require(denied, "Revoked active recorder retained access");
        deniedRecording();
        getPreferences(0).edit().putBoolean("tested", true).commit();
        System.err.println("API28_MIC=revocation_passed");
    }

    @Override public void onDestroy() {
        if (retained != null) retained.release();
        super.onDestroy();
    }

    private static final class RecorderScope implements AutoCloseable {
        final AudioRecord record;
        RecorderScope(AudioRecord value) { record = value; }
        @Override public void close() { record.release(); }
    }
}
