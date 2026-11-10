#!/usr/bin/env python3
"""Exercise production popup hit testing against both framework APIs."""
import argparse
from pathlib import Path
import subprocess
import tempfile

PROBE = r'''
import android.view.View;
import android.view.WindowManager.LayoutParams;
public final class WindowTouchProbe {
    static int cases;
    static void check(boolean expected,int visibility,int flags,float x,float y){
        boolean actual=SdWindowTouchTargets.accepts(visibility,flags,100,400,700,900,x,y);
        if(actual!=expected)throw new AssertionError("flags="+flags+" point="+x+","+y);
        cases++;
    }
    public static void main(String[] args){
        int popup=LayoutParams.FLAG_NOT_FOCUSABLE;
        check(true,View.VISIBLE,popup,150,500);
        check(true,View.VISIBLE,popup,100,400);
        check(false,View.VISIBLE,popup,700,500);
        check(false,View.VISIBLE,popup,150,900);
        check(false,View.VISIBLE,popup,99,500);
        check(false,View.VISIBLE,popup,150,399);
        check(false,View.GONE,popup,150,500);
        check(false,View.INVISIBLE,popup,150,500);
        check(false,View.VISIBLE,popup|LayoutParams.FLAG_NOT_TOUCHABLE,150,500);
        check(false,View.VISIBLE,LayoutParams.FLAG_NOT_TOUCHABLE,150,500);
        check(false,View.VISIBLE,LayoutParams.FLAG_NOT_TOUCH_MODAL,10,10);
        check(true,View.VISIBLE,LayoutParams.FLAG_NOT_TOUCH_MODAL,150,500);
        check(true,View.VISIBLE,0,10,10);
        check(true,View.VISIBLE,0,150,500);
        // A pass-through popup must allow the lower app window to win outside it.
        int selected=-1;
        for(int flags:new int[]{0,popup})if(SdWindowTouchTargets.accepts(View.VISIBLE,flags,100,400,700,900,10,10))selected=flags;
        if(selected!=0)throw new AssertionError("Outside popup consumed app touch");cases++;
        System.out.println("WINDOW_TOUCH_TARGETS=PASS|cases="+cases);
    }
}
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--framework',type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix='saildroid-window-touch-')as name:
        root=Path(name);source=root/'WindowTouchProbe.java';source.write_text(PROBE)
        subprocess.run(['javac','--release','8','-cp',str(args.framework),'-d',str(root),str(source),
                        str(repo/'scripts/device/SdWindowTouchTargets.java')],check=True)
        subprocess.run(['java','-cp',str(root)+':'+str(args.framework),'WindowTouchProbe'],check=True)

if __name__=='__main__':main()
