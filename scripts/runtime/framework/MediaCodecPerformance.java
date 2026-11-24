/* Private SailDroid device measurements, applied before codec infos are cached. */
package android.media;

import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileDescriptor;
import java.lang.reflect.Field;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import org.xmlpull.v1.XmlPullParser;
import org.xmlpull.v1.XmlPullParserFactory;

/** Only measured-frame-rate metadata is local to this runtime. The system's
 * codec inventory, profiles, formats and coding limits remain native results.
 * This class never checks an application identity or instrumentation state.
 */
final class MediaCodecPerformance {
    private static Map<String,Map<String,String>> measurements;
    private static final HashSet<String> applied=new HashSet<String>();

    private static void trustedDirectory(File directory) throws Exception {
        for (File path=directory;path!=null;path=path.getParentFile()) {
            StructStat stat=Os.lstat(path.getPath());
            if (!OsConstants.S_ISDIR(stat.st_mode)||stat.st_uid!=0||(stat.st_mode&0022)!=0)
                throw new SecurityException("Untrusted codec measurement directory");
        }
    }

    private static byte[] readPrivateProfile() throws Exception {
        String root=System.getenv("ANDROID_ROOT");
        if (root==null||!new File(root).isAbsolute())
            throw new SecurityException("Private Android root is unavailable");
        File file=new File(root,"system/etc/saildroid-media-performance.xml");
        FileDescriptor fd;
        try {fd=Os.open(file.getPath(),OsConstants.O_RDONLY|OsConstants.O_CLOEXEC|OsConstants.O_NOFOLLOW,0);}
        catch (ErrnoException absent) {if(absent.errno==OsConstants.ENOENT)return null;throw absent;}
        try {
            trustedDirectory(file.getParentFile());
            StructStat before=Os.fstat(fd);
            if (!OsConstants.S_ISREG(before.st_mode)||before.st_uid!=0||(before.st_mode&0022)!=0
                    ||before.st_nlink!=1||before.st_size<=0||before.st_size>65536)
                throw new SecurityException("Untrusted codec measurement file");
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] block=new byte[4096];int count;
            while ((count=Os.read(fd,block,0,block.length))>0) {
                if(bytes.size()+count>65536)throw new SecurityException("Oversized codec measurements");
                bytes.write(block,0,count);
            }
            StructStat after=Os.fstat(fd);
            if (before.st_ino!=after.st_ino||before.st_size!=after.st_size||bytes.size()!=before.st_size
                    ||before.st_mtime!=after.st_mtime||before.st_ctime!=after.st_ctime)
                throw new SecurityException("Codec measurements changed while reading");
            return bytes.toByteArray();
        } finally {Os.close(fd);}
    }

    private static Map<String,Map<String,String>> parse(byte[] bytes) throws Exception {
        if(bytes==null)return Collections.emptyMap();
        XmlPullParser parser=XmlPullParserFactory.newInstance().newPullParser();
        parser.setFeature(XmlPullParser.FEATURE_PROCESS_DOCDECL,false);
        parser.setInput(new ByteArrayInputStream(bytes),"UTF-8");
        Map<String,Map<String,String>> values=new HashMap<String,Map<String,String>>();
        String section=null;Map<String,String> limits=null;boolean root=false;
        for(int event=parser.nextToken();event!=XmlPullParser.END_DOCUMENT;event=parser.nextToken()) {
            if(event==XmlPullParser.DOCDECL||event==XmlPullParser.ENTITY_REF)
                throw new SecurityException("Entity declarations are not codec measurements");
            if(event==XmlPullParser.START_TAG) {
                String tag=parser.getName();int depth=parser.getDepth();
                if(depth==1&&tag.equals("MediaCodecs")&&!root){root=true;continue;}
                if(depth==2&&(tag.equals("Encoders")||tag.equals("Decoders"))){section=tag;continue;}
                if(depth==3&&tag.equals("MediaCodec")&&section!=null) {
                    String name=parser.getAttributeValue(null,"name"),mime=parser.getAttributeValue(null,"type");
                    if(name==null||!name.matches("[A-Za-z0-9_.-]{1,160}")||mime==null
                            ||!mime.matches("video/[A-Za-z0-9_.+-]{1,100}")
                            ||!"true".equals(parser.getAttributeValue(null,"update")))
                        throw new IllegalArgumentException("Invalid measured codec identity");
                    String key=section+"|"+name+"|"+mime;limits=new HashMap<String,String>();
                    if(values.put(key,limits)!=null||values.size()>128)
                        throw new IllegalArgumentException("Duplicate or excessive measured codec identity");
                    continue;
                }
                if(depth==4&&tag.equals("Limit")&&limits!=null) {
                    String name=parser.getAttributeValue(null,"name"),range=parser.getAttributeValue(null,"range");
                    if(name==null||!name.matches("measured-frame-rate-[1-9][0-9]{0,4}x[1-9][0-9]{0,4}")
                            ||range==null||!range.matches("[1-9][0-9]{0,8}-[1-9][0-9]{0,8}"))
                        throw new IllegalArgumentException("Only measured frame rate limits are supported");
                    String[] bounds=range.split("-");
                    if(Long.parseLong(bounds[0])>Long.parseLong(bounds[1])
                            ||limits.put(name+"-range",range)!=null||limits.size()>128)
                        throw new IllegalArgumentException("Duplicate or invalid measured rate range");
                    continue;
                }
                throw new IllegalArgumentException("Unknown codec measurement element");
            }
            if(event==XmlPullParser.END_TAG) {
                if(parser.getDepth()==3){if(limits==null||limits.isEmpty())throw new IllegalArgumentException("Empty measurements");limits=null;}
                if(parser.getDepth()==2)section=null;
            }
            if((event==XmlPullParser.TEXT||event==XmlPullParser.CDSECT)&&!parser.getText().trim().isEmpty())
                throw new IllegalArgumentException("Unexpected measurement text");
        }
        if(!root||values.isEmpty())throw new IllegalArgumentException("Empty measurement document");
        return values;
    }

    static synchronized void prepare() {
        if(measurements!=null)return;
        try {measurements=parse(readPrivateProfile());}
        catch(Exception failure) {throw new IllegalStateException("Invalid private codec measurement configuration",failure);}
    }

    // Called outside MediaCodecList's per-codec exception handler. A bad or
    // mismatched profile must fail enumeration rather than hide codec entries.
    static synchronized void validateApplied() {
        prepare();
        if(!applied.containsAll(measurements.keySet()))
            throw new IllegalStateException("Configured measurements did not match the native codec inventory");
    }

    static synchronized MediaCodecInfo.CodecCapabilities apply(String codec,String mime,
            boolean encoder,MediaCodecInfo.CodecCapabilities capabilities) {
        try {
            prepare();String key=(encoder?"Encoders":"Decoders")+"|"+codec+"|"+mime;
            Map<String,String> local=measurements.get(key);
            if(local==null)return capabilities;
            MediaCodecInfo.VideoCapabilities video=capabilities.getVideoCapabilities();
            for(String limit:local.keySet()) {
                String[] size=limit.substring("measured-frame-rate-".length(),limit.length()-"-range".length()).split("x");
                if(video==null||!video.isSizeSupported(Integer.parseInt(size[0]),Integer.parseInt(size[1])))
                    throw new IllegalArgumentException("Measured size is not supported by the native codec");
            }
            Field field=MediaCodecInfo.CodecCapabilities.class.getDeclaredField("mCapabilitiesInfo");
            field.setAccessible(true);
            MediaFormat original=(MediaFormat)field.get(capabilities);
            Map<String,Object> info=new HashMap<String,Object>(original.getMap());info.putAll(local);
            MediaCodecInfo.CodecCapabilities result=new MediaCodecInfo.CodecCapabilities(
                    capabilities.profileLevels,capabilities.colorFormats,encoder,
                    new HashMap<String,Object>(capabilities.getDefaultFormat().getMap()),info);
            applied.add(key);
            android.util.Log.i("SailDroidCodecMeasurements","component="+codec+"|type="+mime+"|limits="+local.size());
            return result;
        } catch(Exception failure) {throw new IllegalStateException("Invalid private codec measurement configuration",failure);}
    }
}
