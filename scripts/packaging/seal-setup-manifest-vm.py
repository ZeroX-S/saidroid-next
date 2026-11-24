#!/usr/bin/env python3
"""Seal a new, mutable staging root after all final payload additions.

The manifest excludes only itself; the RPM subsequently hashes/owns the manifest.
Never run this against an installed release or overwrite an existing seal.
"""
from pathlib import Path
import argparse,hashlib,json,os,platform,re,stat,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--release-id',required=True);a=p.parse_args()
assert platform.system()=='Linux' and 'sailfishos' not in Path('/etc/os-release').read_text().lower()
root=a.root.resolve();assert not str(root).startswith(('/opt/saildroid/releases/','/home/art/releases/'));assert re.fullmatch('[a-z0-9][a-z0-9.-]{0,100}',a.release_id)
target=root/'share/packaging/activation-manifest.json';assert not target.exists() and not target.is_symlink();assert(root/'bin/saildroid-setup').is_file()and(root/'share/packaging/setup-registry.jar').is_file();target.parent.mkdir(parents=True,exist_ok=True)
api=json.loads((root/'runtime.json').read_text())['api'];assert api in (28,29)
if api == 28:
    subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'api28/prepare-core-linker.py'),
                    '--root', str(root), '--release-id', a.release_id, '--check'], check=True)
files={};links={};directories=[]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
for p in sorted(root.rglob('*')):
 relative=p.relative_to(root).as_posix();assert re.fullmatch('[A-Za-z0-9_./+@=-]+',relative)
 if p.is_symlink():assert not Path(os.readlink(p)).is_absolute() and root in p.resolve().parents and p.exists();links[relative]=os.readlink(p)
 elif p.is_dir():assert stat.S_IMODE(p.stat().st_mode)==0o755;directories.append(relative)
 else:
  mode=stat.S_IMODE(p.stat().st_mode);assert p.is_file()and not(mode&0o7022);files[relative]=dict(sha256=sha(p),size=p.stat().st_size,mode=mode)
manifest=dict(schema='saildroid-activation-manifest-v1',release_id=a.release_id,api=api,files=files,symlinks=links,directories=directories)
target.write_text(json.dumps(manifest,indent=2)+'\n');target.chmod(0o644);print(json.dumps(dict(path=str(target),sha256=sha(target),files=len(files),symlinks=len(links))))
