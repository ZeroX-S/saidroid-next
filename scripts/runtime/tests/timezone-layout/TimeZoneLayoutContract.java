import java.io.*;
import java.util.*;
import libcore.icu.ICU;
import libcore.timezone.TimeZoneDataFiles;
import libcore.timezone.TzDataSetVersion;

/** Actual dataset and offset agreement across the installed Java and native ICU sources. */
public final class TimeZoneLayoutContract {
    static int checks;
    static void require(boolean v,String why){if(!v)throw new AssertionError(why);checks++;}
    public static void run()throws Exception{
        String runtime=System.getenv("ANDROID_RUNTIME_ROOT"),module=System.getenv("ANDROID_TZDATA_ROOT");
        require(runtime!=null&&module!=null,"Actual runtime module environment");
        require(Arrays.equals(TimeZoneDataFiles.getTimeZoneFilePaths("tzdata"),libcore.util.TimeZoneDataFiles.getTimeZoneFilePaths("tzdata")),"Legacy and canonical actual lookup order agree");
        String javaPath=System.getProperty("android.icu.impl.ICUBinary.dataPath");
        require(javaPath.equals(TimeZoneDataFiles.generateIcuDataPath())&&javaPath.equals(libcore.util.TimeZoneDataFiles.generateIcuDataPath()),"Boot System initializes same canonical ICU paths");
        String[] paths=javaPath.split(":");require(paths.length==3&&paths[1].startsWith(module)&&paths[2].startsWith(runtime),"Data override, TZmodule, runtime ordering");
        String version=ICU.getTZDataVersion();
        require(version.equals(android.icu.util.TimeZone.getTZDataVersion()),"Native and Java ICU actual data version");
        require(version.equals(libcore.util.ZoneInfoDB.getInstance().getVersion()),"Real ZoneInfoDB version agrees");
        require(version.equals(libcore.timezone.ZoneInfoDB.getInstance().getVersion()),"Canonical ZoneInfoDb version agrees");
        for(String root:new String[]{runtime,module}){
            TzDataSetVersion data=TzDataSetVersion.readFromFile(new File(root,"etc/tz/tz_version"));
            require(data.rulesVersion.equals(version)&&data.formatMajorVersion==TzDataSetVersion.currentFormatMajorVersion()&&data.formatMinorVersion>=TzDataSetVersion.currentFormatMinorVersion(),"Actual compatible dataset metadata");
            try(DataInputStream input=new DataInputStream(new FileInputStream(root+"/etc/tz/tzdata"))){
                byte[] header=new byte[12];input.readFully(header);require(new String(header,0,11,"US-ASCII").equals("tzdata"+version)&&header[11]==0,"Actual binary TZ data header");
            }
        }
        String[] ids={"UTC","America/New_York","Europe/London","Asia/Tokyo","Pacific/Fiji","Africa/Casablanca","America/Sao_Paulo","Asia/Gaza","Europe/Dublin","Antarctica/Troll"};
        for(String id:ids){
            java.util.TimeZone zone=java.util.TimeZone.getTimeZone(id);android.icu.util.TimeZone icu=android.icu.util.TimeZone.getTimeZone(id);
            require(zone.getID().equals(id)&&icu.getID().equals(id),"Actual zone identity "+id);
            // Android10 ZoneInfo deliberately uses only signed32-bit transition seconds.
            for(int year=2000;year<=2037;year++)for(int month:new int[]{0,3,6,9}){
                GregorianCalendar calendar=new GregorianCalendar(java.util.TimeZone.getTimeZone("UTC"));calendar.clear();calendar.set(year,month,15,12,0,0);long when=calendar.getTimeInMillis();
                require(zone.getOffset(when)==icu.getOffset(when),"Actual transition offset "+id+" "+when);
            }
        }
        require(!new File(System.getenv("ANDROID_ROOT")+"/usr/share/zoneinfo/tzlookup.xml").exists(),"Country lookup lives in actual runtime module");
        System.out.println("TIMEZONE_LAYOUT_CONTRACT=PASS|checks="+checks+"|version="+version+"|zones=10|real_offset_samples=1520|native_java_icu=agree|canonical_paths=true");
    }
}
