import android.content.pm.ApplicationInfo;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.*;
import java.nio.file.*;
import java.util.Arrays;

/** Ordinary-UID filesystem boundaries for the actual runtime cache binding. */
public final class ApplicationCodeCacheContract {
    private static int checks;
    interface Action { void run() throws Exception; }
    private static void check(boolean value,String why) { checks++;if(!value)throw new AssertionError(why); }
    private static void denied(Action action,String why) throws Exception {
        System.clearProperty("dexmaker.dexcache");
        try { action.run();throw new AssertionError("Accepted invalid cache: "+why); }
        catch(SecurityException|IOException expected) { checks++; }
        check(System.getProperty("dexmaker.dexcache")==null,"Rejected case changed property: "+why);
    }
    private static ApplicationInfo app(Path root) {
        ApplicationInfo info=new ApplicationInfo();info.uid=Os.getuid();info.packageName="android.libcore.cts";info.dataDir=root.toString();return info;
    }
    private static Path home(Path root,String name)throws Exception {
        Path p=Files.createDirectory(root.resolve(name));Os.chmod(p.toString(),0700);Path code=Files.createDirectory(p.resolve("code_cache"));Os.chmod(code.toString(),0700);return p;
    }
    public static void run() throws Exception {
        check(Os.getuid()>0,"actual unprivileged caller");
        Path root=Paths.get(System.getenv("SAILDROID_DATA_DIR"),"cache-boundary-contract");Files.createDirectory(root);Os.chmod(root.toString(),0700);
        Path good=home(root,"good");ApplicationInfo valid=app(good);
        denied(()->SdApplicationCodeCache.bind(null),"null identity");
        ApplicationInfo wrong=app(good);wrong.uid=valid.uid+1;denied(()->SdApplicationCodeCache.bind(wrong),"different UID");
        ApplicationInfo blank=app(good);blank.packageName="";denied(()->SdApplicationCodeCache.bind(blank),"missing package");
        ApplicationInfo relative=app(good);relative.dataDir="relative";denied(()->SdApplicationCodeCache.bind(relative),"relative data path");
        Path publicData=home(root,"public-data");Os.chmod(publicData.toString(),0777);denied(()->SdApplicationCodeCache.bind(app(publicData)),"public data directory");
        Path publicCode=home(root,"public-code");Os.chmod(publicCode.resolve("code_cache").toString(),0777);denied(()->SdApplicationCodeCache.bind(app(publicCode)),"writable shared code cache");
        Path external=home(root,"external"),dataLink=root.resolve("data-link");Files.createSymbolicLink(dataLink,external);denied(()->SdApplicationCodeCache.bind(app(dataLink)),"data symlink");
        Path codeLink=home(root,"code-link");Files.delete(codeLink.resolve("code_cache"));Files.createSymbolicLink(codeLink.resolve("code_cache"),external.resolve("code_cache"));denied(()->SdApplicationCodeCache.bind(app(codeLink)),"code cache symlink");
        Path targetLink=home(root,"target-link");Files.createSymbolicLink(targetLink.resolve("code_cache/dexmaker"),external);denied(()->SdApplicationCodeCache.bind(app(targetLink)),"dynamic cache symlink");
        Path targetFile=home(root,"target-file");Files.write(targetFile.resolve("code_cache/dexmaker"),new byte[]{1,2,3});denied(()->SdApplicationCodeCache.bind(app(targetFile)),"regular file cache");
        Path publicTarget=home(root,"public-target");Path open=Files.createDirectory(publicTarget.resolve("code_cache/dexmaker"));Os.chmod(open.toString(),0777);denied(()->SdApplicationCodeCache.bind(app(publicTarget)),"public dynamic cache");
        Path configured=home(root,"configured");System.setProperty("dexmaker.dexcache",external.toString());
        try{SdApplicationCodeCache.bind(app(configured));throw new AssertionError("external property accepted");}
        catch(SecurityException expected){checks++;}
        check(System.getProperty("dexmaker.dexcache").equals(external.toString()),"rejection rewrote supplied property");
        check(!Files.exists(configured.resolve("code_cache/dexmaker")),"external property created cache before rejection");
        System.clearProperty("dexmaker.dexcache");SdApplicationCodeCache.bind(valid);
        Path cache=good.resolve("code_cache/dexmaker");check(cache.toString().equals(System.getProperty("dexmaker.dexcache")),"documented property actual path");
        StructStat state=Os.lstat(cache.toString());check(state.st_uid==Os.getuid()&&(state.st_mode&0777)==0700&&OsConstants.S_ISDIR(state.st_mode),"actual private owner/mode/directory");
        Path payload=cache.resolve("ordinary-owned-cache.bin");byte[] bytes={5,12,33,100};Files.write(payload,bytes);check(Arrays.equals(Files.readAllBytes(payload),bytes),"actual ordinary UID file IO");
        SdApplicationCodeCache.bind(valid);check(Files.exists(payload)&&cache.toString().equals(System.getProperty("dexmaker.dexcache")),"idempotent binding retains file");
        check(!Files.exists(external.resolve("dexmaker")),"symlink targets untouched");
        System.out.println("APPLICATION_CODE_CACHE_CONTRACT=PASS|checks="+checks+"|uid="+Os.getuid()+"|cache="+cache+"|mode=0700|real_file_io=true|negative_paths_rejected=true");
    }
}
