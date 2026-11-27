#!/usr/bin/env python3
"""Build only the process-private glibc JNI/GStreamer adapter, on the Linux VM."""
import argparse, hashlib, json, os, platform, shlex, shutil, subprocess
from pathlib import Path
default_jdk = os.environ.get('JAVA_HOME') or ('/tmp/jdkfull/jdk-21.0.13+9' if Path('/tmp/jdkfull/jdk-21.0.13+9').is_dir() else str(Path(shutil.which('javac')).resolve().parents[1]))
parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--jdk',default=default_jdk);args=parser.parse_args()
assert platform.system()=='Linux'and platform.machine()=='aarch64'
source=Path(__file__).resolve().parent;out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);jdk=Path(args.jdk);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gstreamer-1.0','gstreamer-app-1.0','gstreamer-video-1.0'],text=True))
cmd=['g++','-shared','-fPIC','-O2','-std=c++17','-Wall','-Wextra','-Werror=return-type','-I'+str(jdk/'include'),'-I'+str(jdk/'include/linux'),str(source/'player-host.cpp'),'-o',str(out/'libsdmediaplayer-host.so'),*flags,'-ldl','-pthread','-Wl,-z,defs']
with(out/'build.log').open('wb')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
p=out/'libsdmediaplayer-host.so';header=subprocess.check_output(['readelf','-h',str(p)],text=True);assert 'AArch64'in header
(out/'manifest.json').write_text(json.dumps(dict(passed=True,command=cmd,output=str(p),sha256=sha(p),sources={p.name:sha(p)for p in source.glob('*')if p.is_file()}),indent=2)+'\n')
print(p)
