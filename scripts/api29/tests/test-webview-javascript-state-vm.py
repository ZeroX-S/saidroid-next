#!/usr/bin/env python3
"""Run production WebView dispatch against a recording transport, without Android natives.

The fixed API28/API29 android-all inputs provide framework signatures. Only the
isolated engine transport and unrelated runtime helpers are replaced. The actual
provider is compiled and its per-view dispatcher is invoked without constructing
an Android View or starting Qt/WPE.
"""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile


ENGINE = r'''
import android.graphics.Bitmap;
import java.io.File;
import java.util.ArrayList;
import org.json.JSONObject;
public final class SdWebEngine {
    public interface Listener {
        void event(JSONObject event);
        void frame(Bitmap bitmap,long sequence);
        void failed(String reason);
    }
    final ArrayList<JSONObject> packets=new ArrayList<JSONObject>();
    SdWebEngine() {}
    public SdWebEngine(File directory,int width,int height,Listener listener) {
        throw new AssertionError("The fixture must not start a renderer");
    }
    public static boolean available() { return false; }
    public static int[] hostSize(int width,int height) { return new int[]{width,height}; }
    public static JSONObject touchCommand(int action,float x,float y,long time,int width,int height) {
        throw new AssertionError("Unexpected touch");
    }
    public boolean send(JSONObject packet) { packets.add(packet);return true; }
    public void close() { throw new AssertionError("Unexpected transport failure"); }
}
'''

HELPERS = r'''
final class SdDisplayShim { static final int WIDTH=1080,HEIGHT=2160; }
final class SdApkPackage { static final String NAME="org.example.webviewcontract"; }
final class SdViewRepair { static void enable() {} }
'''

CONTRACT = r'''
import android.webkit.WebView;
import android.webkit.ValueCallback;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Collections;
import org.json.JSONObject;

public final class WebViewJavascriptStateContract {
    static final Class<?> STATE;
    static final Method HANDLE;
    static {
        try {
            STATE=Class.forName("SdWebViewProvider$SdWebView");
            HANDLE=STATE.getDeclaredMethod("handle",String.class,Method.class,Object[].class);
            HANDLE.setAccessible(true);
        } catch(Exception error) { throw new AssertionError(error); }
    }
    static void check(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    static void set(Object state,String name,Object value)throws Exception {
        Field field=STATE.getDeclaredField(name);field.setAccessible(true);field.set(state,value);
    }
    static Object get(Object state,String name)throws Exception {
        Field field=STATE.getDeclaredField(name);field.setAccessible(true);return field.get(state);
    }
    static Object call(Object state,String name,Method signature,Object... arguments)throws Exception {
        return HANDLE.invoke(state,new Object[]{name,signature,arguments});
    }
    static Object read(Object state,String name)throws Exception {
        return call(state,name,WebView.class.getMethod(name));
    }
    static void unchanged(Object state,String url,String title)throws Exception {
        check(url.equals(read(state,"getUrl")),"JavaScript replaced the document URL");
        check(url.equals(read(state,"getOriginalUrl")),"JavaScript replaced the original URL");
        check(title.equals(read(state,"getTitle")),"JavaScript cleared the document title");
        check(Integer.valueOf(3).equals(get(state,"phase")),"JavaScript changed the load phase");
        check(Integer.valueOf(100).equals(get(state,"progress")),"JavaScript changed load progress");
    }
    public static void main(String[] args)throws Exception {
        // Skip View/Looper/native constructors while retaining the real dispatcher.
        Class<?> unsafeClass=Class.forName("sun.misc.Unsafe");
        Field singleton=unsafeClass.getDeclaredField("theUnsafe");singleton.setAccessible(true);
        Object state=unsafeClass.getMethod("allocateInstance",Class.class).invoke(singleton.get(null),STATE);
        String document="https://example.invalid/verification",title="Verification";
        set(state,"url",document);set(state,"title",title);set(state,"phase",3);set(state,"progress",100);
        SdWebEngine transport=new SdWebEngine();set(state,"engine",transport);
        Method load=WebView.class.getMethod("loadUrl",String.class);
        Method loadHeaders=WebView.class.getMethod("loadUrl",String.class,java.util.Map.class);
        String[] scripts={"window.nativeCallback({code:0});", "window.label='回调';\nvoid 0", ""};
        for(int i=0;i<scripts.length;i++) {
            if(i==1)call(state,"loadUrl",loadHeaders,"javascript:"+scripts[i],Collections.singletonMap("X-Test","fixture"));
            else call(state,"loadUrl",load,"javascript:"+scripts[i]);
            unchanged(state,document,title);
            check(transport.packets.size()==i+1,"JavaScript did not emit exactly one command");
            JSONObject packet=transport.packets.get(i);
            check("eval".equals(packet.getString("op")),"JavaScript attempted navigation");
            check(packet.getInt("id")==0,"loadUrl JavaScript acquired a callback ID");
            check(scripts[i].equals(packet.getString("script")),"Callback source changed in transit");
        }
        Method evaluate=WebView.class.getMethod("evaluateJavascript",String.class,ValueCallback.class);
        call(state,"evaluateJavaScript",evaluate,"void 0",null);
        unchanged(state,document,title);
        check(transport.packets.size()==4&&transport.packets.get(3).getInt("id")==1,
            "evaluateJavascript transport changed");
        // A real navigation must still replace URL/title. No engine/View is needed
        // for this fallback path, and it must not fabricate successful rendering.
        set(state,"engine",null);
        String next="https://example.invalid/next";
        call(state,"loadUrl",load,next);
        check(next.equals(read(state,"getUrl")),"Real navigation retained the old URL");
        check("".equals(read(state,"getTitle")),"Real navigation retained the old title");
        check(Integer.valueOf(2).equals(get(state,"phase")),"Unavailable renderer reported a successful load");
        System.out.println("WEBVIEW_JAVASCRIPT_STATE=passed|loadUrl_cases=3|evaluateJavascript|real_navigation|renderer_started=false");
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-jar', type=Path, action='append', required=True,
                        help='Repeat to exercise both fixed API28/API29 inputs')
    parser.add_argument('--jdk', type=Path,
                        default=Path(os.environ.get('JAVA_HOME', '/tmp/jdkfull/jdk-21.0.13+9')))
    parser.add_argument('--provider-source', type=Path,
                        help='Optional baseline source for a before/after regression check')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    provider = args.provider_source or repo/'scripts/device/SdWebViewProvider.java'
    for framework in args.android_jar:
        with tempfile.TemporaryDirectory(prefix='sd-webview-javascript-state-') as directory:
            root = Path(directory)
            files = {'SdWebEngine.java': ENGINE, 'RuntimeHelpers.java': HELPERS,
                     'WebViewJavascriptStateContract.java': CONTRACT}
            for name, content in files.items():
                (root/name).write_text(content)
            # javac requires the source filename to match the public class.
            (root/'SdWebViewProvider.java').write_text(provider.read_text())
            classes = root/'classes'
            classes.mkdir()
            sources = [root/name for name in files]+[root/'SdWebViewProvider.java']
            sources += [repo/'scripts/device'/name for name in ['SdWebCookies.java', 'SdWebInterfaces.java']]
            subprocess.run([str(args.jdk/'bin/javac'), '--release', '8', '-cp', str(framework),
                            '-d', str(classes), *map(str, sources)], check=True)
            subprocess.run([str(args.jdk/'bin/java'), '-cp', str(classes)+os.pathsep+str(framework),
                            'WebViewJavascriptStateContract'], check=True)
            print('WEBVIEW_JAVASCRIPT_STATE=framework|'+framework.name, flush=True)


if __name__ == '__main__':
    main()
