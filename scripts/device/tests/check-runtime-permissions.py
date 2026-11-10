#!/usr/bin/env python3
"""Exercise per-app permission choices, manifest bounds and concurrent processes."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import sys,shutil,hashlib,stat


ASSETS = r'''
package android.content.res;
import java.io.File;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.xmlpull.v1.XmlPullParser;
public final class AssetManager {
    private String path;
    public int addAssetPath(String value) { path=value; return new File(value).isFile()?1:0; }
    public XmlResourceParser openXmlResourceParser(int cookie, String name) throws Exception {
        DocumentBuilderFactory factory=DocumentBuilderFactory.newInstance();factory.setNamespaceAware(true);
        Element root=factory.newDocumentBuilder().parse(new File(path)).getDocumentElement();
        ArrayList<Element> nodes=new ArrayList<Element>();nodes.add(root);
        for(Node child=root.getFirstChild();child!=null;child=child.getNextSibling())if(child instanceof Element)nodes.add((Element)child);
        final int[] position={-1};
        return (XmlResourceParser)Proxy.newProxyInstance(XmlResourceParser.class.getClassLoader(),new Class<?>[]{XmlResourceParser.class},(proxy,method,args)->{
            String operation=method.getName();
            if(operation.equals("next"))return ++position[0]<nodes.size()?XmlPullParser.START_TAG:XmlPullParser.END_DOCUMENT;
            if(operation.equals("close"))return null;
            Element element=nodes.get(position[0]);
            if(operation.equals("getDepth"))return position[0]==0?1:2;
            if(operation.equals("getName"))return element.getTagName();
            if(operation.equals("getAttributeValue")||operation.equals("getAttributeIntValue")){
                String namespace=(String)args[0],attribute=(String)args[1];
                boolean present=namespace==null?element.hasAttribute(attribute):element.hasAttributeNS(namespace,attribute);
                if(!present)return operation.equals("getAttributeIntValue")?args[2]:null;
                String value=namespace==null?element.getAttribute(attribute):element.getAttributeNS(namespace,attribute);
                return operation.equals("getAttributeIntValue")?Integer.decode(value):value;
            }
            throw new UnsupportedOperationException(operation);
        });
    }
    public void close() {}
}
'''

PROBE = r'''
import java.nio.file.*;
import java.util.*;
public final class RuntimePermissionsProbe {
    static final String CAMERA="android.permission.CAMERA",READ="android.permission.READ_EXTERNAL_STORAGE";
    static int cases;
    static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);cases++;}
    public static void main(String[] args)throws Exception{
        SdAppPermissions state=new SdAppPermissions(SdApkPackage.APK,SdApkPackage.NAME);
        check(state.holds("android.permission.INTERNET"),"Normal permission lost");
        check(state.holds("org.example.permissions.OWNED"),"Own signature permission lost");
        check(!state.holds("android.permission.INTERACT_ACROSS_USERS_FULL"),"Platform signature granted");
        check(!state.canRequest("android.permission.READ_CONTACTS"),"maxSdk ignored");
        check(!state.holds("android.permission.NOT_PLATFORM"),"Reserved Android namespace redefined");
        check(state.canRequest(CAMERA),"App redefinition overrode platform protection level");
        check(!state.interactiveAuthorizationAvailable(),"In-app UI advertised trusted authority");
        Map<String,Boolean> choices=new HashMap<>();choices.put(CAMERA,true);
        try{state.decide(choices);throw new AssertionError("In-process authorization accepted");}catch(SecurityException expected){cases++;}
        Path old=Paths.get(SdApkPackage.DATA,"saildroid-runtime-permissions.properties");
        Files.write(old,(CAMERA+"=granted\n"+READ+"=granted\n").getBytes("UTF-8"));
        check(state.holds(CAMERA)==Boolean.parseBoolean(args[0]),"Host policy decision differs after app-private forgery");
        check(!state.holds(READ),"Forged storage permission accepted");
        if(args.length>1)check(state.shouldShowRationale(CAMERA)==Boolean.parseBoolean(args[1]),"Root denial history differs");
        if(args.length>2){
            Path apk=Paths.get(SdApkPackage.APK);byte[] bytes=Files.readAllBytes(apk);
            Files.write(apk,"\n".getBytes("UTF-8"),StandardOpenOption.APPEND);
            check(!state.holds(CAMERA),"Cached digest survived APK mutation");
            Files.write(apk,bytes);
        }
        Path policy=Paths.get("/var/lib/saildroid/permissions/"+SdApkPackage.NAME+".properties");
        if(!Files.isWritable(policy)){
            try{Files.write(policy,(CAMERA+"=granted\n").getBytes("UTF-8"));throw new AssertionError("App could edit trusted policy");}
            catch(java.nio.file.AccessDeniedException expected){cases++;}
        }
        System.out.println("RUNTIME_PERMISSIONS=PASS|cases="+cases+"|camera="+state.holds(CAMERA));
    }
}
'''


def manifest(package, entries):
    return '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="' + package + '">' + entries + '</manifest>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    parser.add_argument('--namespace-worker',action='store_true',help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if os.geteuid()!=0 or 'sailfishos' in Path('/etc/os-release').read_text().lower():
        raise SystemExit('Run this isolated fixture as root in the Linux build VM')
    if not arguments.namespace_worker:
        subprocess.run(['unshare','--mount','--propagation','private',sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--namespace-worker'],check=True)
        return
    java_home=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))
    Path('/opt/saildroid-test-jdk').mkdir(exist_ok=True)
    subprocess.run(['mount','--bind',str(java_home),'/opt/saildroid-test-jdk'],check=True)
    os.environ['PATH']='/opt/saildroid-test-jdk/bin:'+os.environ['PATH']
    subprocess.run(['mount','-t','tmpfs','-o','mode=755','tmpfs','/var/lib'],check=True)
    policy=Path('/var/lib/saildroid/permissions');policy.mkdir(parents=True)
    for folder in [policy.parent,policy]:folder.chmod(0o755)
    repository = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix='saildroid-permissions-test-') as directory:
        work = Path(directory);work.chmod(0o755)
        root = work / 'root'
        (root / 'framework').mkdir(parents=True)
        shared = work / 'shared'
        shared.mkdir()
        data = work / 'data'
        data.mkdir();os.chown(data,65534,65534);data.chmod(0o700)
        names = ('INTERNET', 'READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE', 'CAMERA',
                 'RECORD_AUDIO', 'READ_CONTACTS', 'INTERACT_ACROSS_USERS_FULL')
        platform = ''.join('<permission android:name="android.permission.' + name
                           + '" android:protectionLevel="' + str(0 if name == 'INTERNET' else 2 if name == 'INTERACT_ACROSS_USERS_FULL' else 1) + '"/>' for name in names)
        (root / 'framework/framework-res.apk').write_text(manifest('android', platform), encoding='utf-8')
        requested = ''.join('<uses-permission android:name="android.permission.' + name + '"'
                            + (' android:maxSdkVersion="27"' if name == 'READ_CONTACTS' else '') + '/>' for name in names)
        apk = work / 'app.apk'
        apk.write_text(manifest('org.example.permissions', requested
                               + '<permission android:name="org.example.permissions.OWNED" android:protectionLevel="2"/>'
                               + '<uses-permission android:name="org.example.permissions.OWNED"/>'
                               + '<permission android:name="android.permission.CAMERA" android:protectionLevel="0"/>'
                               + '<permission android:name="android.permission.NOT_PLATFORM" android:protectionLevel="0"/>'
                               + '<uses-permission android:name="android.permission.NOT_PLATFORM"/>'), encoding='utf-8')
        fixtures = {
            'android/content/res/AssetManager.java': ASSETS,
            'android/os/Build.java': 'package android.os; public final class Build { public static final class VERSION { public static final int SDK_INT=28; } }',
            'SdApkPackage.java': 'public final class SdApkPackage { public static final String NAME="org.example.permissions", APK=System.getProperty("test.apk"), DATA=System.getProperty("test.data"); }',
            'SdCamera.java': 'public final class SdCamera { public static boolean available() { return Boolean.getBoolean("test.camera"); } }',
            'SdAudio.java': 'public final class SdAudio { public static boolean recordingAvailable() { return Boolean.getBoolean("test.microphone"); } }',
            'RuntimePermissionsProbe.java': PROBE,
        }
        sources = []
        for name, text in fixtures.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8', newline='\n')
            sources.append(str(path))
        classes = work / 'classes'
        subprocess.run(['javac', '--release', '8', '-encoding', 'UTF-8', '-nowarn', '-sourcepath', '',
                        '-cp', str(arguments.framework), '-d', str(classes), *sources,
                        str(repository / 'scripts/device/SdAppPermissions.java')], check=True)
        framework=work/'framework.jar';shutil.copyfile(arguments.framework,framework)
        # A strict caller umask must not turn fixture paths into private roots.
        for path in work.rglob('*'):
            if path==data:continue
            path.chmod(0o755 if path.is_dir() else 0o644)
        environment = dict(os.environ, ANDROID_ROOT=str(root), EXTERNAL_STORAGE=str(shared))
        helper=repository/'scripts/packaging/saildroid-permissions.py'
        command=['java','-Dtest.apk='+str(apk),'-Dtest.data='+str(data),'-Dtest.camera=true',
                 '-cp',str(classes)+os.pathsep+str(framework),'RuntimePermissionsProbe']
        rows=[]
        def run(label,expected,rationale=None,mutate=False):
            args=[str(expected).lower()]+([]if rationale is None else[str(rationale).lower()])+(['mutate']if mutate else[])
            q=subprocess.run(command+args,env=environment,user=65534,group=65534,extra_groups=[],capture_output=True,text=True,timeout=20)
            print(label,q.stdout.strip(),q.stderr.strip(),flush=True);assert q.returncode==0,(label,q.stdout,q.stderr)
            rows.append(label)
        run('fresh-and-app-private-forgery',False,False)
        target=policy/'org.example.permissions.properties'
        cli=['python3',str(helper),'--package','org.example.permissions','--apk',str(apk)]
        subprocess.run(cli+['--grant','android.permission.CAMERA'],check=True,capture_output=True,text=True)
        run('host-grant-visible-to-new-process',True,False)
        apk.chmod(0o666)
        run('apk-mutation-invalidates-cached-digest',True,False,True)
        apk.chmod(0o644)
        subprocess.run(cli+['--deny','android.permission.CAMERA'],check=True,capture_output=True,text=True)
        run('host-revoke-visible-to-new-process',False,True)
        subprocess.run(cli+['--grant','android.permission.CAMERA'],check=True,capture_output=True,text=True)
        saved=target.read_text()
        target.write_text(saved.replace(hashlib.sha256(apk.read_bytes()).hexdigest(),'0'*64));run('wrong-apk-binding',False)
        target.write_text(saved.replace('package=org.example.permissions','package=org.example.other'));run('wrong-package-binding',False)
        target.write_text(saved);target.chmod(0o666);run('writable-policy-rejected',False);target.chmod(0o644)
        os.chown(target,65534,65534);run('application-owned-policy-rejected',False);os.chown(target,0,0)
        replacement=work/'forged-policy';replacement.write_text(saved);target.unlink();target.symlink_to(replacement);run('symbolic-policy-rejected',False)
        target.unlink();target.write_text(saved);target.chmod(0o644)
        policy.chmod(0o777);run('writable-parent-rejected',False);policy.chmod(0o755)
        q=subprocess.run(['python3',str(helper),'--package','org.example.permissions','--apk',str(apk),'--grant','android.permission.CAMERA'],user=65534,group=65534,extra_groups=[],capture_output=True,text=True)
        assert q.returncode!=0 and 'require root'in q.stderr;rows.append('unprivileged-host-editor-rejected')
        print('RUNTIME_PERMISSION_HOST_POLICY=PASS|scenarios='+str(len(rows))+'|app_private_self_grant=false')


if __name__ == '__main__':
    main()
