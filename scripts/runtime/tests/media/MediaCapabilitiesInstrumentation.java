package org.example.saildroid.mediacapabilities;

import android.app.Instrumentation;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.os.Bundle;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import org.json.JSONObject;

/** Public API snapshot, separate from all official CTS APKs and results. */
public final class MediaCapabilitiesInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    private static Bundle event(){Bundle b=new Bundle();b.putString("class",MediaCapabilitiesInstrumentation.class.getName());b.putString("test","publicCodecCapabilitySnapshot");b.putInt("numtests",1);return b;}
    @Override public void onStart(){
        sendStatus(1,event());
        try {
            MediaCodecInfo target=null;
            for(MediaCodecInfo info:new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos())
                if(info.isEncoder()&&info.getCanonicalName().equals("OMX.google.vp8.encoder")){
                    if(target!=null)throw new AssertionError("Duplicate canonical VP8 encoder");target=info;
                }
            if(target==null)throw new AssertionError("Actual native VP8 encoder is absent");
            MediaCodecInfo.CodecCapabilities caps=target.getCapabilitiesForType("video/x-vnd.on2.vp8");
            MediaCodecInfo.VideoCapabilities video=caps.getVideoCapabilities();
            if(video==null||!video.isSizeSupported(320,180))throw new AssertionError("Native video size unsupported");
            JSONObject support=new JSONObject();support.put("name",target.getName());support.put("canonical",target.getCanonicalName());
            support.put("encoder",target.isEncoder());support.put("software",target.isSoftwareOnly());support.put("hardware",target.isHardwareAccelerated());support.put("vendor",target.isVendor());
            String[] types=target.getSupportedTypes();Arrays.sort(types);support.put("types",Arrays.toString(types));
            int[] colors=caps.colorFormats.clone();Arrays.sort(colors);support.put("colors",Arrays.toString(colors));
            ArrayList<String> profiles=new ArrayList<String>();for(MediaCodecInfo.CodecProfileLevel level:caps.profileLevels)profiles.add(level.profile+":"+level.level);Collections.sort(profiles);support.put("profiles",profiles.toString());
            support.put("bitrate",video.getBitrateRange().toString());support.put("widths",video.getSupportedWidths().toString());support.put("heights",video.getSupportedHeights().toString());
            support.put("width_alignment",video.getWidthAlignment());support.put("height_alignment",video.getHeightAlignment());support.put("frame_rates",video.getSupportedFrameRates().toString());
            support.put("coding_frame_rates_320x180",video.getSupportedFrameRatesFor(320,180).toString());
            MediaCodecInfo.EncoderCapabilities encoder=caps.getEncoderCapabilities();support.put("complexity",encoder.getComplexityRange().toString());support.put("quality",encoder.getQualityRange().toString());
            support.put("cbr",encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR));support.put("vbr",encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR));support.put("cq",encoder.isBitrateModeSupported(MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CQ));
            android.util.Range<Double> measured=video.getAchievableFrameRatesFor(320,180);
            if(measured==null)throw new AssertionError("Measured device rate is missing");
            Bundle success=event();success.putString("support_snapshot",support.toString());success.putString("measured_320x180",measured.toString());sendStatus(0,success);
            Bundle result=new Bundle();result.putString("support_snapshot",support.toString());result.putString("measured_320x180",measured.toString());result.putString("stream","Internal public media snapshot; not CTS\nOK (1 test)\n");finish(-1,result);
        }catch(Throwable failure){Bundle error=event();error.putString("stack",android.util.Log.getStackTraceString(failure));sendStatus(-2,error);Bundle result=new Bundle();result.putString("stream","FAILURES!!!\nTests run: 1,  Failures: 1\n");finish(-1,result);}
    }
}
