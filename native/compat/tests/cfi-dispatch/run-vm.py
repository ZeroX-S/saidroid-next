from pathlib import Path
import subprocess,resource,tempfile,json
repo=Path(__file__).resolve().parents[4];source=Path(__file__).resolve().parent
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
with tempfile.TemporaryDirectory(prefix='saidroid-cfi-')as directory:
 out=Path(directory)
 for name in ['checked','unchecked']:
  subprocess.run(['gcc','-shared','-fPIC','-O2',str(source/(name+'.c')),'-o',str(out/(name+'.so'))],check=True)
 subprocess.run(['gcc','-O2','-Wall',str(source/'main.c'),str(repo/'native/compat/runtime-cfi.c'),'-ldl','-o',str(out/'test')],check=True)
 rows=[]
 for library,mode,expected in [('checked','valid',0),('checked','wrong-type',-6),('checked','unmapped',-6),('unchecked','valid',0)]:
  p=subprocess.run([str(out/'test'),str(out/(library+'.so')),mode],capture_output=True,text=True,timeout=5)
  rows.append(dict(library=library,mode=mode,expected=expected,exit=p.returncode,stderr=p.stderr.strip()));assert p.returncode==expected,rows[-1]
 print(json.dumps(dict(status='PASS',cases=rows,scope='cross-DSO CFI dispatch and rejection protocol; not a full Android CFI acceptance'),indent=2))
