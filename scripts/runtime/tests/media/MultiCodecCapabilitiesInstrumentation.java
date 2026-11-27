package org.example.saildroid.mediacapabilities;

import android.app.Instrumentation;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.os.Bundle;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import org.json.JSONObject;

/** Ordinary public API observations, independent of original CTS results. */
public final class MultiCodecCapabilitiesInstrumentation extends Instrumentation {
    private static final int[][] SIZES = {{320,180},{640,360},{1280,720},{1920,1080},{3840,2160}};
    private static Bundle event() {
        Bundle b = new Bundle();
        b.putString("class", MultiCodecCapabilitiesInstrumentation.class.getName());
        b.putString("test", "publicMultiCodecSnapshot"); b.putInt("numtests", 1);
        return b;
    }
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        sendStatus(1, event());
        try {
            JSONObject all = new JSONObject(), measured = new JSONObject();
            MediaCodecInfo[] codecs = new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos();
            for (String type : new String[]{"vp8", "vp9"}) {
                String name = "OMX.google." + type + ".encoder", mime = "video/x-vnd.on2." + type;
                MediaCodecInfo target = null;
                for (MediaCodecInfo info : codecs) {
                    if (info.isEncoder() && info.getCanonicalName().equals(name)) {
                        if (target != null) throw new AssertionError("Duplicate canonical encoder " + name);
                        target = info;
                    }
                }
                if (target == null) throw new AssertionError("Missing actual native encoder " + name);
                MediaCodecInfo.CodecCapabilities caps = target.getCapabilitiesForType(mime);
                MediaCodecInfo.VideoCapabilities video = caps.getVideoCapabilities();
                if (video == null) throw new AssertionError("Missing native video capabilities");
                JSONObject support = new JSONObject(), sizes = new JSONObject(), rates = new JSONObject();
                support.put("name", target.getName()); support.put("canonical", target.getCanonicalName());
                support.put("mime", mime); support.put("encoder", target.isEncoder());
                support.put("software", target.isSoftwareOnly()); support.put("hardware", target.isHardwareAccelerated());
                support.put("vendor", target.isVendor());
                String[] types = target.getSupportedTypes(); Arrays.sort(types); support.put("types", Arrays.toString(types));
                int[] colors = caps.colorFormats.clone(); Arrays.sort(colors); support.put("colors", Arrays.toString(colors));
                ArrayList<String> profiles = new ArrayList<String>();
                for (MediaCodecInfo.CodecProfileLevel level : caps.profileLevels) profiles.add(level.profile + ":" + level.level);
                Collections.sort(profiles); support.put("profiles", profiles.toString());
                support.put("bitrate", video.getBitrateRange().toString());
                support.put("widths", video.getSupportedWidths().toString()); support.put("heights", video.getSupportedHeights().toString());
                support.put("width_alignment", video.getWidthAlignment()); support.put("height_alignment", video.getHeightAlignment());
                support.put("frame_rates", video.getSupportedFrameRates().toString());
                MediaCodecInfo.EncoderCapabilities encoder = caps.getEncoderCapabilities();
                support.put("complexity", encoder.getComplexityRange().toString()); support.put("quality", encoder.getQualityRange().toString());
                support.put("cbr", encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR));
                support.put("vbr", encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR));
                support.put("cq", encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CQ));
                for (int[] size : SIZES) {
                    int w = size[0], h = size[1]; String key = w + "x" + h;
                    JSONObject coding = new JSONObject(); boolean supported = video.isSizeSupported(w, h);
                    coding.put("supported", supported);
                    if (supported) {
                        coding.put("frame_rates", video.getSupportedFrameRatesFor(w, h).toString());
                        android.util.Range<Double> value = video.getAchievableFrameRatesFor(w, h);
                        rates.put(key, value == null ? JSONObject.NULL : value.toString());
                    }
                    sizes.put(key, coding);
                }
                support.put("sizes", sizes); all.put(name, support); measured.put(name, rates);
            }
            Bundle result = new Bundle(); result.putString("support_snapshot", all.toString());
            result.putString("measured_snapshot", measured.toString());
            Bundle done = event(); done.putString("support_snapshot", all.toString());
            done.putString("measured_snapshot", measured.toString()); sendStatus(0, done);
            result.putString("stream", "Internal public multi-codec snapshot; not CTS\nOK (1 test)\n"); finish(-1, result);
        } catch (Throwable failure) {
            Bundle error = event(); error.putString("stack", android.util.Log.getStackTraceString(failure)); sendStatus(-2, error);
            Bundle result = new Bundle(); result.putString("stream", "FAILURES!!!\nTests run: 1, Failures: 1\n"); finish(-1, result);
        }
    }
}
