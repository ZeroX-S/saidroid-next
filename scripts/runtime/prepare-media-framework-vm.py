#!/usr/bin/env python3
"""Compile the lazy device-measurement hook without rebuilding or installing ART.

Preserve all other accepted framework class/resource bytes. The separate normal
framework, hidden-API and boot-image tools must process this source archive.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,zipfile

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
 p=argparse.ArgumentParser();p.add_argument('inputs',type=Path);p.add_argument('baseline_framework',type=Path)
 p.add_argument('original_source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
 repo=Path(__file__).resolve().parents[2];assert not a.output.exists();a.output.mkdir(parents=True)
 assert sha(a.original_source)=='a253025c872b7a22e12d60e9057dfca2e0ab33df815311c9941a016dc78488c9'
 fw=a.inputs/'android-all-10-robolectric-5803371.jar'
 assert sha(fw)=='a0ad701eedd47bdaefbac1c2cc80dd400c0adea3cccd8a3ad286f79da1ca294c'
 source=a.original_source.read_text();old='caps[typeIx++] = getCodecCapabilities(index, type);'
 assert source.count(old)==1
 source=source.replace(old,'caps[typeIx++] = MediaCodecPerformance.apply(getCanonicalName(index), type,\n'
  '                    (getAttributes(index) & 1) != 0, getCodecCapabilities(index, type));')
 assert source.count('int count = native_getCodecCount();')==1
 source=source.replace('int count = native_getCodecCount();','MediaCodecPerformance.prepare();\n                int count = native_getCodecCount();')
 assert source.count('sRegularCodecInfos =\n')==1
 source=source.replace('sRegularCodecInfos =\n','MediaCodecPerformance.validateApplied();\n                sRegularCodecInfos =\n')
 java=a.output/'MediaCodecList.java';java.write_text(source)
 helper=repo/'scripts/runtime/framework/MediaCodecPerformance.java';classes=a.output/'classes';classes.mkdir()
 javac=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin/javac'
 command=[str(javac),'--release','8','-nowarn','-cp',str(fw),'-d',str(classes),str(java),str(helper)]
 with(a.output/'javac.log').open('w')as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
 replacements={str(f.relative_to(classes)):f.read_bytes()for f in classes.rglob('*.class')}
 assert set(replacements)=={'android/media/MediaCodecList.class','android/media/MediaCodecPerformance.class'}
 baseline=a.baseline_framework/'classes.jar';baseline_manifest=json.loads((a.baseline_framework/'manifest.json').read_text())
 first=a.baseline_framework/'framework29-classes.jar';assert sha(first)==baseline_manifest['files'][first.name]['sha256']
 with zipfile.ZipFile(fw)as canonical,zipfile.ZipFile(baseline)as accepted:
  assert accepted.read('android/media/MediaCodecList.class')==canonical.read('android/media/MediaCodecList.class'), 'Baseline codec list has unreviewed changes'
 # Compare the complete Java method/field descriptor surface after compiling
 # the source from the matching platform release.
 javap=str(javac.with_name('javap'))
 before=subprocess.check_output([javap,'-p','-s','-cp',str(baseline),'android.media.MediaCodecList'],text=True)
 after=subprocess.check_output([javap,'-p','-s','-cp',str(classes),'android.media.MediaCodecList'],text=True)
 assert before==after,'MediaCodecList declarations changed'
 (a.output/'MediaCodecList.declarations.txt').write_text(after)
 files={}
 with zipfile.ZipFile(baseline)as accepted,zipfile.ZipFile(first)as resources,zipfile.ZipFile(a.output/'source.jar','x',zipfile.ZIP_DEFLATED)as output:
  for name in accepted.namelist():
   data=replacements.get(name,accepted.read(name));output.writestr(name,data);files[name]=hashlib.sha256(data).hexdigest()
  for name,data in replacements.items():
   if name not in files:output.writestr(name,data);files[name]=hashlib.sha256(data).hexdigest()
  for name in resources.namelist():
   if name.endswith('.dex')or name.endswith('/'):continue
   assert name not in files;data=resources.read(name);output.writestr(name,data);files[name]=hashlib.sha256(data).hexdigest()
 record=dict(scope='Framework source preparation only; no device installation',baseline_manifest_sha256=sha(a.baseline_framework/'manifest.json'),
  baseline_classes_sha256=sha(baseline),aosp_source_sha256=sha(a.original_source),helper_source_sha256=sha(helper),
  source_sha256=sha(a.output/'source.jar'),replaced_classes=sorted(replacements),other_accepted_class_bytes_unchanged=True,
  declaration_surface_unchanged=True,configuration_path='${ANDROID_ROOT}/system/etc/saildroid-media-performance.xml',files=files)
 (a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('MEDIA_FRAMEWORK=source-prepared|replaced=1|added=1|other_class_bytes=unchanged')

if __name__=='__main__':main()
