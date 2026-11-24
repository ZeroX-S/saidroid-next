#!/usr/bin/env python3
"""Exercise production Java viewport/packets and native input mapping, without a phone.

Requires a JDK, g++, and the fixed API29 android-all input. This is a geometry
and protocol contract test; it does not claim to render a real WPE page.
"""
from pathlib import Path
import argparse
import json
import subprocess
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--android-jar', type=Path, required=True)
p.add_argument('--jdk', type=Path, default=Path('/tmp/jdkfull/jdk-21.0.13+9'))
a = p.parse_args()
repo = Path(__file__).resolve().parents[3]

JAVA = r'''
import org.json.JSONObject;
public class WebViewGeometryContract {
    static void check(boolean value,String reason) { if(!value)throw new AssertionError(reason); }
    public static void main(String[] args)throws Exception {
        // Default, supported tall viewport, new port, QHD, tablet, landscape, extremes.
        int[][] cases={{1080,2160},{720,2560},{1080,2340},{1440,3200},{2340,1080},
                       {1600,2560},{2160,4096},{4096,2160},{1,Integer.MAX_VALUE},
                       {Integer.MAX_VALUE,1},{Integer.MAX_VALUE,Integer.MAX_VALUE},
                       {0,0},{-10,-20}};
        check(SdWebEngine.MAX_FRAME_BYTES==2160*4096*4,"Java/native frame budget");
        for(int[] view:cases) {
            int[] size=SdWebEngine.hostSize(view[0],view[1]);
            int w=size[0],h=size[1];
            check(w>0&&h>0&&w<=2160&&h<=4096,"host dimensions");
            check((long)w*h*4<=SdWebEngine.MAX_FRAME_BYTES,"frame budget");
            if(view[0]>0&&view[1]>0&&view[0]<=2160&&view[1]<=4096)
                check(w==view[0]&&h==view[1],"supported geometry must stay 1:1");
            if(view[0]<1||view[1]<1)continue;
            // A rendered point at these fractions must hit the same host point.
            for(float fraction:new float[]{0.0f,0.25f,0.75f,0.99f}) {
                JSONObject touch=SdWebEngine.touchCommand(0,view[0]*fraction,view[1]*fraction,123,view[0],view[1]);
                check(touch.getInt("viewWidth")==view[0]&&touch.getInt("viewHeight")==view[1],"View extents missing");
                JSONObject row=new JSONObject().put("width",w).put("height",h).put("touch",touch)
                    .put("expectedX",w*(double)fraction).put("expectedY",h*(double)fraction);
                System.out.println(row);
            }
        }
    }
}
'''

CPP = r'''
#include "native/host/third_party/json.hpp"
#include "native/webview/qt-helper/include/webview-geometry.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <string>
using Json=nlohmann::json;
int main() {
    std::string line;int count=0;
    while(std::getline(std::cin,line)) {
        auto row=Json::parse(line),touch=row.at("touch");
        const int width=row.at("width"),height=row.at("height");
        double x=sd_webview_coordinate(touch.at("x"),touch.at("viewWidth"),width);
        double y=sd_webview_coordinate(touch.at("y"),touch.at("viewHeight"),height);
        assert(std::abs(x-row.at("expectedX").get<double>())<0.001);
        assert(std::abs(y-row.at("expectedY").get<double>())<0.001);
        // The same touch consumed after a queued resize uses the NEW viewport.
        assert(std::abs(sd_webview_coordinate(touch.at("y"),touch.at("viewHeight"),height/2)-y*(height/2)/height)<0.001);
        ++count;
    }
    assert(count==44);
    // Existing clients send host pixels; missing extents must remain compatible.
    assert(sd_webview_coordinate(123.5,0,900)==123.5);
    // Moves outside the View must not get pinned to an edge.
    assert(sd_webview_coordinate(-25,100,200)==-50);
    assert(sd_webview_coordinate(125,100,200)==250);
    std::cout<<"WEBVIEW_GEOMETRY=passed|mapped_touches="<<count
             <<"|initial_resize_budget|live_resize|legacy_packets|outside_moves\n";
}
'''

with tempfile.TemporaryDirectory(prefix='sd-webview-geometry-') as d:
    root = Path(d)
    (root/'WebViewGeometryContract.java').write_text(JAVA)
    (root/'input.cpp').write_text(CPP)
    classes = root/'classes'
    classes.mkdir()
    subprocess.run([str(a.jdk/'bin/javac'), '--release', '8', '-cp', str(a.android_jar),
                    '-d', str(classes), str(repo/'scripts/device/SdWebEngine.java'),
                    str(root/'WebViewGeometryContract.java')], check=True)
    packets = subprocess.check_output([str(a.jdk/'bin/java'), '-cp',
                                       str(classes)+':'+str(a.android_jar),
                                       'WebViewGeometryContract'], text=True)
    # Preserve the production JSON packets as diagnostic output.
    rows = [json.loads(line) for line in packets.splitlines()]
    assert len(rows) == 44
    subprocess.run(['g++', '-std=c++11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I'+str(repo), str(root/'input.cpp'), '-o', str(root/'input')], check=True)
    subprocess.run([str(root/'input')], input=packets, text=True, check=True)
