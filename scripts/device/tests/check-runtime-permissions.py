#!/usr/bin/env python3
"""Exercise per-app permission choices, manifest bounds and concurrent processes."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile


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
    static final String READ="android.permission.READ_EXTERNAL_STORAGE";
    static final String WRITE="android.permission.WRITE_EXTERNAL_STORAGE";
    static final String CAMERA="android.permission.CAMERA";
    static final String MIC="android.permission.RECORD_AUDIO";
    static int cases;
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);cases++;}
    static SdAppPermissions state()throws Exception{return new SdAppPermissions(SdApkPackage.APK,SdApkPackage.NAME);}
    static Map<String,Boolean> choice(String name,boolean grant){Map<String,Boolean> result=new LinkedHashMap<String,Boolean>();result.put(name,grant);return result;}
    static void rejects(SdAppPermissions state,Map<String,Boolean> choices){try{state.decide(choices);throw new AssertionError("Unauthorized choice accepted");}catch(SecurityException expected){cases++;}}
    public static void main(String[] args)throws Exception{
        SdAppPermissions first=state();
        if(args.length>0){for(int index=0;index<40;index++)first.decide(choice(args[0],true));return;}
        check(first.holds(null),"Null receiver restriction changed");
        check(first.holds("android.permission.INTERNET"),"Requested normal platform permission lost");
        check(first.holds("org.example.permissions.OWNED"),"Own signature grant lost");
        check(!first.holds("android.permission.INTERACT_ACROSS_USERS_FULL"),"Platform signature granted");
        check(!first.holds(READ)&&!first.shouldShowRationale(READ),"Fresh dangerous permission granted or denied history inferred");
        check(first.supported(READ)&&first.supported(WRITE)&&first.supported(CAMERA),"Implemented backends not requestable");
        check(!first.supported(MIC),"Missing microphone backend advertised");
        check(!first.canRequest("android.permission.READ_CONTACTS"),"maxSdkVersion ignored");
        check(!first.canRequest("org.example.permissions.UNDECLARED"),"Undeclared permission request accepted");
        rejects(first,choice("org.example.permissions.UNDECLARED",true));
        rejects(first,choice("android.permission.INTERACT_ACROSS_USERS_FULL",true));
        rejects(first,choice(MIC,true));
        Map<String,Boolean> mixed=choice(READ,true);mixed.put(MIC,true);rejects(first,mixed);
        check(!first.holds(READ),"Rejected transaction saved a partial grant");
        first.decide(choice(READ,false));
        check(!first.holds(READ)&&first.shouldShowRationale(READ),"User denial history not saved");
        SdAppPermissions other=state();other.decide(choice(READ,true));
        check(first.holds(READ)&&!first.shouldShowRationale(READ),"Existing process did not see new grant");
        check(state().holds(READ),"Restart did not retain grant");
        other.decide(choice(WRITE,true));check(first.holds(READ)&&first.holds(WRITE),"Second choice lost first grant");
        System.setProperty("test.camera","false");rejects(first,choice(CAMERA,true));
        System.setProperty("test.camera","true");first.decide(choice(CAMERA,true));
        System.setProperty("test.camera","false");check(!first.holds(CAMERA),"Unavailable camera retained usable permission");
        System.setProperty("test.camera","true");
        System.setProperty("test.microphone","true");
        check(first.supported(MIC)&&!first.holds(MIC),"Available microphone inferred a grant");
        first.decide(choice(MIC,false));
        check(!first.holds(MIC)&&first.shouldShowRationale(MIC),"Microphone denial lost");
        first.decide(choice(MIC,true));
        check(state().holds(MIC),"Microphone choice not retained");
        System.setProperty("test.microphone","false");
        check(!first.holds(MIC),"Unavailable microphone retained usable permission");
        System.setProperty("test.microphone","true");
        other.decide(choice(MIC,false));
        check(!first.holds(MIC),"Microphone revocation did not propagate");
        String java=System.getProperty("java.home")+"/bin/java",classpath=System.getProperty("java.class.path");
        ArrayList<String> base=new ArrayList<String>(Arrays.asList(java,"-Dtest.apk="+SdApkPackage.APK,"-Dtest.data="+SdApkPackage.DATA,"-Dtest.camera=true","-cp",classpath,"RuntimePermissionsProbe"));
        ArrayList<String> read=new ArrayList<String>(base),camera=new ArrayList<String>(base);read.add(READ);camera.add(CAMERA);
        Process one=new ProcessBuilder(read).inheritIO().start(),two=new ProcessBuilder(camera).inheritIO().start();
        check(one.waitFor()==0&&two.waitFor()==0,"Concurrent writer failed");
        check(first.holds(READ)&&first.holds(CAMERA)&&first.holds(WRITE),"Concurrent processes lost a grant");
        other.decide(choice(READ,false));check(!first.holds(READ)&&first.shouldShowRationale(READ),"Revocation did not propagate");
        Path record=Paths.get(SdApkPackage.DATA,"saildroid-runtime-permissions.properties");
        Properties previous=new Properties();try(java.io.InputStream input=Files.newInputStream(record)){previous.load(input);}
        check(previous.getProperty(WRITE).equals("granted"),"API29 record compatibility lost");
        try(java.util.stream.Stream<Path> paths=Files.list(record.getParent())){check(paths.noneMatch(path->path.getFileName().toString().startsWith(".saildroid-permissions-")),"Temporary decision leaked");}
        Files.delete(record);Files.createSymbolicLink(record,Paths.get(SdApkPackage.APK));
        try{first.holds(READ);throw new AssertionError("Symbolic decision record followed");}catch(IllegalStateException expected){cases++;}
        Files.delete(record);
        Path lock=record.getParent().resolve("saildroid-runtime-permissions.lock");Files.delete(lock);Files.createSymbolicLink(lock,Paths.get(SdApkPackage.APK));
        rejects(first,choice(READ,true));Files.delete(lock);
        System.out.println("RUNTIME_PERMISSIONS=PASS|cases="+cases+"|concurrent_writes=80");
    }
}
'''


def manifest(package, entries):
    return '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="' + package + '">' + entries + '</manifest>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework', type=Path, required=True)
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix='saildroid-permissions-test-') as directory:
        work = Path(directory)
        root = work / 'root'
        (root / 'framework').mkdir(parents=True)
        shared = work / 'shared'
        shared.mkdir()
        data = work / 'data'
        data.mkdir()
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
                               + '<uses-permission android:name="org.example.permissions.OWNED"/>'), encoding='utf-8')
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
        environment = dict(os.environ, ANDROID_ROOT=str(root), EXTERNAL_STORAGE=str(shared))
        subprocess.run(['java', '-Dtest.apk=' + str(apk), '-Dtest.data=' + str(data), '-Dtest.camera=true',
                        '-cp', str(classes) + os.pathsep + str(arguments.framework), 'RuntimePermissionsProbe'],
                       env=environment, check=True, timeout=60)


if __name__ == '__main__':
    main()
