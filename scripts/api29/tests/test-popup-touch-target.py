from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
COMPAT = ROOT / 'scripts/api29/popup-touch-target-compat'
spec = importlib.util.spec_from_file_location('popup_patch', COMPAT / 'patch.py')
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


def method(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    ending = opening + 1
    while depth:
        depth += (source[ending] == '{') - (source[ending] == '}')
        ending += 1
    return source[start:ending]


HARNESS = '''
import java.util.ArrayList;
public class PopupTouchContract {
    static class View { static final int VISIBLE=0; }
    static class WindowManager {
        static class LayoutParams {
            static final int FLAG_NOT_FOCUSABLE=8,FLAG_NOT_TOUCHABLE=16,FLAG_NOT_TOUCH_MODAL=32;
            int flags;
        }
    }
    static class Rect { int left=100,top=100,right=200,bottom=200; }
    static class Window {
        final WindowManager.LayoutParams attributes=new WindowManager.LayoutParams();
        final Rect frame=new Rect();
        Object sender=new Object();int visibility=0,layer=1,order;
    }
    final ArrayList<Window> windows=new ArrayList<>();
    private ArrayList<Window> orderedWindows(){
        ArrayList<Window> ordered=new ArrayList<>(windows);
        ordered.sort((first,second)->first.layer!=second.layer?
            Integer.compare(first.layer,second.layer):Integer.compare(first.order,second.order));
        return ordered;
    }
    METHODS
    static void require(boolean condition,String reason){if(!condition)throw new AssertionError(reason);}
    public static void main(String[] arguments){
        String scenario=arguments[0];PopupTouchContract host=new PopupTouchContract();
        Window activity=new Window();activity.frame.left=0;activity.frame.top=0;
        activity.frame.right=1000;activity.frame.bottom=1000;host.windows.add(activity);
        Window popup=new Window();popup.order=1;popup.attributes.flags=8;host.windows.add(popup);
        Window expected=popup;float horizontal=150,vertical=150;
        if(scenario.equals("nonfocusable"))require(host.top()==activity,"Old focus target reproduction");
        if(scenario.equals("outside-left")){horizontal=99;expected=activity;}
        if(scenario.equals("outside-right")){horizontal=200;expected=activity;}
        if(scenario.equals("outside-bottom")){vertical=200;expected=activity;}
        if(scenario.equals("inside-border")){horizontal=100;vertical=100;}
        if(scenario.equals("negative-fraction")){horizontal=-0.5f;expected=activity;}
        if(scenario.equals("modal-outside")){popup.attributes.flags=0;horizontal=0;}
        if(scenario.equals("nonmodal-outside")){popup.attributes.flags=32;horizontal=0;expected=activity;}
        if(scenario.equals("not-touchable")){popup.attributes.flags|=16;expected=activity;}
        if(scenario.equals("invisible")){popup.visibility=4;expected=activity;}
        if(scenario.equals("gone")){popup.visibility=8;expected=activity;}
        if(scenario.equals("no-channel")){popup.sender=null;expected=activity;}
        if(scenario.equals("visual-layer")){activity.layer=3;expected=activity;}
        if(scenario.equals("nested-popup")){
            Window nested=new Window();nested.order=2;nested.attributes.flags=8;
            host.windows.add(nested);expected=nested;
        }
        if(scenario.equals("nested-outside")){
            Window nested=new Window();nested.order=2;nested.attributes.flags=8;
            nested.frame.left=300;nested.frame.right=400;host.windows.add(nested);
        }
        if(scenario.equals("none")){host.windows.clear();expected=null;}
        if(scenario.equals("all-not-touchable")){
            popup.attributes.flags|=16;activity.attributes.flags|=16;expected=null;
        }
        if(scenario.equals("focus-unchanged"))require(host.top()==activity,"Popup stole keyboard focus");
        require(host.touchTarget(horizontal,vertical)==expected,"Wrong touch target: "+scenario);
        System.out.println("POPUP_TOUCH=PASS|case="+scenario);
    }
}
'''


class PopupTouchTests(unittest.TestCase):
    def test_reference(self):
        source = (ROOT / 'scripts/device/SdWindowSession.java').read_text()
        methods = method(source, 'private Window touchTarget(') + '\n' + method(source, 'private Window top(')
        scenarios = ['nonfocusable', 'outside-left', 'outside-right', 'outside-bottom', 'inside-border',
                     'negative-fraction', 'modal-outside', 'nonmodal-outside', 'not-touchable', 'invisible',
                     'gone', 'no-channel', 'visual-layer', 'nested-popup', 'nested-outside', 'none',
                     'all-not-touchable', 'focus-unchanged']
        java_home = Path(os.environ.get('JAVA_HOME', '/usr'))
        with tempfile.TemporaryDirectory(prefix='saildroid-popup-touch-') as directory:
            path = Path(directory)
            (path / 'PopupTouchContract.java').write_text(HARNESS.replace('METHODS', methods))
            subprocess.run([str(java_home / 'bin/javac'), '--release', '8', '-d', str(path),
                            str(path / 'PopupTouchContract.java')], check=True, capture_output=True)
            for scenario in scenarios:
                with self.subTest(scenario=scenario):
                    completed = subprocess.run([str(java_home / 'bin/java'), '-cp', str(path),
                                                'PopupTouchContract', scenario], check=True,
                                               capture_output=True, text=True, timeout=10)
                    self.assertIn('POPUP_TOUCH=PASS|case=' + scenario, completed.stdout)

    def test_patch_boundaries(self):
        fixture = ('.class LSdWindowSession;\n.super Ljava/lang/Object;\n' + patch.SIGNATURE +
                   '\n    .registers 30\n    move-object/from16 v1, p0\n' +
                   '    move/from16 v3, p3\n    move/from16 v4, p4\n' + patch.OLD + '\n' +
                   patch.OLD + '\n    return-void\n.end method\n' +
                   '.method private top()LSdWindowSession$Window;\n    .registers 1\n' +
                   '    const/4 v0, 0x0\n    return-object v0\n.end method\n')
        patched = patch.patch(fixture)
        helper = (COMPAT / 'touchTarget.smali').read_text().rstrip()
        self.assertEqual(patched.count(patch.NEW), 2)
        self.assertEqual(patch.patch(patched), patched)
        self.assertEqual(patched[:-(len(helper) + 2)].replace(patch.NEW, patch.OLD), fixture)
        for invalid in [fixture.replace('.registers 30', '.registers 28'),
                        fixture.replace(patch.OLD, patch.NEW, 1),
                        fixture + helper + '\n', patched + helper + '\n']:
            with self.subTest(layout=invalid[:40]), self.assertRaises(ValueError):
                patch.patch(invalid)

    def test_gesture_capture_unchanged(self):
        source = (ROOT / 'scripts/device/SdWindowSession.java').read_text()
        delivery = method(source, 'private void deliver(')
        self.assertIn('if(touches.isEmpty()){gesture=touchTarget(x,y);', delivery)
        self.assertNotIn('gesture=top()', delivery)
        self.assertIn('coordinate.x=point.x-gesture.frame.left', delivery)
        self.assertIn('coordinate.y=point.y-gesture.frame.top', delivery)
        self.assertIn('MotionEvent.ACTION_POINTER_DOWN', delivery)


if __name__ == '__main__':
    unittest.main()
