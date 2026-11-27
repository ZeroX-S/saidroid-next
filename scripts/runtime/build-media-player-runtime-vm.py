#!/usr/bin/env python3
"""Compose the media/IME source overlays without editing any frozen runtime tree."""
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--baseline-classes',required=True);parser.add_argument('--baseline-manifest',required=True);parser.add_argument('--output',required=True);parser.add_argument('--include-window-ime',action='store_true');parser.add_argument('--include-activity-finish',action='store_true');parser.add_argument('--jdk',default='/tmp/jdkfull/jdk-21.0.13+9');args=parser.parse_args()
repo=Path(__file__).resolve().parents[2];module=repo/'native/media/gstreamer-player';base=Path(args.baseline_classes).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);jdk=Path(args.jdk)/'bin';fw=repo/'build/codex-api29/inputs/android-all-10-robolectric-5803371.jar';r8=repo/'build/codex-api29/inputs/r8-8.3.37.jar';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before={str(p.relative_to(base)):sha(p)for p in base.rglob('*.class')};assert before==json.loads(Path(args.baseline_manifest).read_text())['classfiles_after']
sources=[module/(name+'.java')for name in ['SdAudio','SdTexture','SdMediaPlayer','SdMediaPlayerAudio','SdMediaDataSource']]
allowed={'SdAudio.class','SdTexture.class'}
if args.include_window_ime:sources.append(repo/'scripts/runtime/window-ime-compat/source/scripts/device/SdWindowSession.java');allowed.update(n for n in before if n=='SdWindowSession.class'or n.startswith('SdWindowSession$'))
if args.include_activity_finish:
 sources.extend(repo/'scripts/runtime/activity-finish-compat/source'/name for name in ['SdActivityHost.java','SdViewDump.java'])
 allowed.update(n for n in before if n=='SdActivityHost.class'or n.startswith('SdActivityHost$')or n=='SdViewDump.class')
commands=[]
def run(cmd,name):
 commands.append(cmd)
 with(out/name).open('wb')as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
# Reproduce the source owners used by the accepted base before applying changes.
baseline_sources=[];meta=json.loads((module/'sources.json').read_text())
for key in ['baseline_audio','baseline_texture']:
 row=meta[key];p=repo/row['path'];assert sha(p)==row['sha256'];baseline_sources.append(p)
if args.include_activity_finish:
 activity_meta=json.loads((repo/'scripts/runtime/activity-finish-compat/sources.json').read_text())['baseline'];p=repo/activity_meta['path'];assert sha(p)==activity_meta['sha256'];baseline_sources.append(p);baseline_sources.append(repo/'scripts/device/SdViewDump.java')
old=out/'baseline-check';old.mkdir();run([str(jdk/'javac'),'--release','8','-nowarn','-cp',str(fw)+':'+str(base),'-d',str(old),*map(str,baseline_sources)],'baseline-javac.log');assert all(before[str(p.relative_to(old))]==sha(p)for p in old.rglob('*.class'))
new=out/'overlay-classes';new.mkdir();run([str(jdk/'javac'),'--release','8','-nowarn','-cp',str(fw)+':'+str(base),'-d',str(new),*map(str,sources)],'javac.log');classes=out/'classes';shutil.copytree(base,classes)
for p in new.rglob('*.class'):shutil.copyfile(p,classes/p.relative_to(new))
after={str(p.relative_to(classes)):sha(p)for p in classes.rglob('*.class')};changed=[n for n in before if before[n]!=after[n]];added=sorted(set(after)-set(before));assert set(changed)<=allowed;assert all(n.startswith(('SdMediaPlayer','SdMediaDataSource','SdWindowSession$'))for n in added)
run([str(jdk/'java'),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(fw),'--output',str(out/'runtime.jar'),*map(str,sorted(classes.rglob('*.class')))],'d8.log')
(out/'manifest.json').write_text(json.dumps(dict(passed=True,sources={str(p.relative_to(repo)):sha(p)for p in sources},classfiles_before=before,classfiles_after=after,changed_classfiles=changed,added_classfiles=added,runtime_sha256=sha(out/'runtime.jar'),commands=commands),indent=2)+'\n');print(out/'runtime.jar')
