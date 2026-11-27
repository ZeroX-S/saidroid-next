package android.media;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.Map;

/** Configuration parser/storage contract only; no encoder or CTS verdict. */
public final class MediaCodecPerformanceContract {
    private static final String VALID="<MediaCodecs><Encoders><MediaCodec name=\"OMX.google.vp8.encoder\" type=\"video/x-vnd.on2.vp8\" update=\"true\"><Limit name=\"measured-frame-rate-320x180\" range=\"100-120\" /></MediaCodec></Encoders></MediaCodecs>";
    private static Object parse(String xml)throws Exception {
        Method method=MediaCodecPerformance.class.getDeclaredMethod("parse",byte[].class);method.setAccessible(true);
        return method.invoke(null,(Object)xml.getBytes("UTF-8"));
    }
    private static void reject(String xml)throws Exception {
        try{parse(xml);throw new AssertionError("Invalid measurements accepted");}
        catch(InvocationTargetException failure){
            Throwable cause=failure.getCause();
            if(!(cause instanceof IllegalArgumentException)&&!(cause instanceof SecurityException)
                    &&!cause.getClass().getName().contains("XmlPullParserException"))throw failure;
        }
    }
    public static void main(String[] args)throws Exception {
        if(args[0].equals("parse")) {
            Map<?,?> result=(Map<?,?>)parse(VALID);
            if(result.size()!=1||!"100-120".equals(((Map<?,?>)result.values().iterator().next()).get("measured-frame-rate-320x180-range")))throw new AssertionError("Measured keys changed");
            reject(VALID.replace("measured-frame-rate-320x180","size-range"));
            reject(VALID.replace("100-120","120-100"));reject(VALID.replace("100-120","0-120"));
            reject(VALID.replace("100-120","-100-120"));reject(VALID.replace("100-120","1e2-120"));
            reject(VALID.replace("update=\"true\"","update=\"false\""));
            reject(VALID.replace("</MediaCodec>","<Limit name=\"measured-frame-rate-320x180\" range=\"100-120\" /></MediaCodec>"));
            reject(VALID.replace("</Encoders>","<MediaCodec name=\"OMX.google.vp8.encoder\" type=\"video/x-vnd.on2.vp8\" update=\"true\"><Limit name=\"measured-frame-rate-320x180\" range=\"100-120\" /></MediaCodec></Encoders>"));
            reject("<!DOCTYPE MediaCodecs [<!ENTITY x 'x'>]>"+VALID);
            reject("<MediaCodecs/>");reject(VALID.replace("<Limit","<Unknown"));
            java.lang.reflect.Field field=MediaCodecPerformance.class.getDeclaredField("measurements");field.setAccessible(true);field.set(null,result);
            try{MediaCodecPerformance.validateApplied();throw new AssertionError("Unmatched codec profile accepted");}
            catch(IllegalStateException expected){}
            field.set(null,java.util.Collections.emptyMap());MediaCodecPerformance.validateApplied();
            MediaCodecInfo.CodecCapabilities original=new MediaCodecInfo.CodecCapabilities();
            if(MediaCodecPerformance.apply("unchanged.codec","video/avc",true,original)!=original)
                throw new AssertionError("Unmeasured native capabilities changed");
            System.out.println("MEDIA_PROFILE_CONTRACT=PASS|parser=12|unmatched=reject|unmeasured=unchanged");return;
        }
        Method read=MediaCodecPerformance.class.getDeclaredMethod("readPrivateProfile");read.setAccessible(true);
        try {
            byte[] bytes=(byte[])read.invoke(null);
            if(args[0].equals("reject"))throw new AssertionError("Untrusted profile accepted");
            if(args[0].equals("absent")?(bytes!=null):(bytes==null||bytes.length==0))throw new AssertionError("Storage result mismatch");
        }catch(InvocationTargetException failure){
            Throwable cause=failure.getCause();
            boolean noFollow=cause instanceof android.system.ErrnoException
                    &&((android.system.ErrnoException)cause).errno==android.system.OsConstants.ELOOP;
            if(!args[0].equals("reject")||(!(cause instanceof SecurityException)&&!noFollow))throw failure;
        }
        System.out.println("MEDIA_PROFILE_CONTRACT=PASS|storage="+args[0]);
    }
}
