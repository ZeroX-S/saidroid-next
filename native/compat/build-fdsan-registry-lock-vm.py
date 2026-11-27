#!/usr/bin/env python3
"""Fix native fdsan reporting reentrancy over the byte-verified host shim closure."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess
p=argparse.ArgumentParser(description=__doc__)
for n in ['baseline-product','baseline-native','output']:p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();os.umask(0o022);repo=Path(__file__).resolve().parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();product=json.loads((a.baseline_product/'manifest.json').read_text());base=json.loads((a.baseline_native/'manifest.json').read_text());old=a.baseline_native/'libsdhost29.so';assert base['schema']=='saildroid-zip-read-native-v1'and base['passed']and sha(old)==base['library_sha256'];assert not a.output.exists();a.output.mkdir(parents=True)
names='api29-host api29-fdsan api29-signal api29-diagnostics api29-regex api29-egl-host api29-thread api29-cfi api29-renderscript api29-native-loader api29-hardware-loader'.split();sources=[repo/('native/compat/'+n+'.c')for n in names]
for f in sources:assert sha(f)==product['native_sources'][str(f.relative_to(repo))]
sources.append(repo/'native/compat/runtime-policy/runtime-gc.c');sources.append(repo/'native/compat/zip/zip-read.c');assert all(sha(repo/n)==h for n,h in base['sources'].items())and sha(sources[-1])==base['source_sha256'];source=repo/'native/compat/fdsan-ownership/api29-fdsan.c';changed=[source if f.name=='api29-fdsan.c'else f for f in sources];assert sum(x!=y for x,y in zip(sources,changed))==1
java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'));flags=['gcc','-shared','-fPIC','-O2','-Wall','-I'+str(java/'include'),'-I'+str(java/'include/linux')]
for label,files in [('baseline',sources),('new',changed)]:
 with(a.output/(label+'.log')).open('x')as log:subprocess.run(flags+['-o',str(a.output/(label+'.so')),*map(str,files),'-ldl','-pthread'],check=True,stdout=log,stderr=subprocess.STDOUT)
assert sha(a.output/'baseline.so')==sha(old)
def symbols(f):return set(' '.join(l.split()[-2:])for l in subprocess.check_output(['nm','-D',str(f)],text=True).splitlines()if len(l.split())>=2)
assert symbols(a.output/'new.so')==symbols(old)
needed=lambda f:sorted(l.strip()for l in subprocess.check_output(['readelf','-d',str(f)],text=True).splitlines()if'(NEEDED)'in l);assert needed(old)==needed(a.output/'new.so');shutil.copyfile(a.output/'new.so',a.output/'libsdhost29.so');(a.output/'libsdhost29.so').chmod(0o444)
record=dict(schema='saildroid-fdsan-registry-lock-v1',passed=True,scope='Real native fdsan registry checks and tagged kernel close remain under mutex. Move reporting/abort and allocation-failure reporting outside mutex, preventing ART abort/close reentry self-deadlock; exact public symbols/needed/default errorpolicy retained. Process-private only; no phone/fullCTS acceptance.',builder_sha256=sha(Path(__file__)),source_sha256=sha(source),baseline_source_sha256=sha(repo/'native/compat/runtime-fdsan.c'),baseline_library_sha256=sha(old),baseline_manifest_sha256=sha(a.baseline_native/'manifest.json'),library_sha256=sha(a.output/'libsdhost29.so'),baseline_rebuild_byte_identical=True,all_dynamic_symbols_identical=True,needed_identical=True,sources={str(f.relative_to(repo)):sha(f)for f in sources},actual_sources={str(f.relative_to(repo)):sha(f)for f in changed});(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('FDSAN_REGISTRY_LOCK=built|baseline_byte_identical=true|public_symbols_identical=true|abort_outside_mutex=true|phone_changed=false')
