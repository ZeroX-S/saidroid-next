#!/usr/bin/env python3
"""Assemble an isolated, reviewable SailDroid API29 component; no device writes."""
from pathlib import Path
import argparse,subprocess,shutil,json,hashlib,tarfile,os,zipfile,re
p=argparse.ArgumentParser()
for name in ['inputs','framework','core','product','manager','native','linker','output']:p.add_argument(name,type=Path)
p.add_argument('--command-runtime',type=Path)
p.add_argument('--hardware-profile',type=Path,help='Public hardware profile captured on the target phone; no persistent identifiers')
p.add_argument('--binder-device',choices=['/home/art/runtime/binder/binder'])
p.add_argument('--boot-image',type=Path,help='Verified ART boot image directory with recipe.json and manifest.json')
a=p.parse_args();assert not a.output.exists();a.output.mkdir(parents=True);root=a.output/'root';root.mkdir()
repo=Path(__file__).resolve().parents[2]
def copy(source,relative):
 target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target);target.chmod(0o644);return target
# Current-process glibc helpers are kept separate from Android ELF libraries.
for name in ['runtime.jar','libsdbridge.so','libsdwindow.so','libsdhost29.so','libsdmaliit.so','libsdhostapi.so']:copy(a.product/name,'lib/'+name)
for name in ['saildroid-app','saildroid-host']:copy(a.product/name,'libexec/'+name).chmod(0o755)
for name in ['sdwebviewd','sdwebview-host','webview-engine.qml','webview-host-env.json']:
 copy(a.product/'webview-host'/name,'libexec/'+name).chmod(0o644 if name.endswith(('.qml','.json')) else 0o755)
copy(a.linker/'libdl_bio.so.0','lib/libdl_bio.so.0')
if (a.product/'libpthread_bio.so.0').is_file():copy(a.product/'libpthread_bio.so.0','lib/libpthread_bio.so.0')
copy(a.manager/'manager.apk','share/manager.apk')
(root/'libexec/saildroid-open').symlink_to('saildroid-app')
subprocess.run(['gcc','-O2','-Wall','-o',str(root/'libexec/saildroid-launch'),str(repo/'native/launcher/saildroid-launch.c')],check=True);(root/'libexec/saildroid-launch').chmod(0o755)
(root/'empty-libs').mkdir()
(root/'linker-config').mkdir();(root/'linker-config/runtime.cfg').write_text('libc.so libc_bio.so.0\nlibstdc++.so libstdc++_bio.so.0\nlibm.so libm.so.6\nlibdl.so libdl.so.2\nlibEGL.so libEGL.so.1\nlibGLESv2.so libGLESv2.so.2\nlibGLESv3.so libGLESv2.so.2\nlibGLESv1_CM.so libGLESv2.so.2\n')
if (a.product/'libsdhwui-native.so').is_file():
 copy(a.product/'libsdhwui-native.so','android-libs/libsdhwui-native.so')
# All boot entries carry DEX; preserve real core resources and original extra jars.
base=['core-oj','apachehttp','apache-xml','bouncycastle','core-junit','core-libart','hamcrest','junit-runner','okhttp','wolfssljni'];boot=[]
for component in base:
 source=(a.core if component in ['core-oj','core-libart']else Path('/home/art/java/dex/art'))/(component+'-hostdex.jar')
 target='java/dex/art/'+source.name;copy(source,target);boot.append(target)
for source in sorted(a.framework.glob('framework29-*.jar')):target='java/dex/art/'+source.name;copy(source,target);boot.append(target)
# Resolve the dependency closure from matching API29 system/APEX libraries.
locations=[a.native/'lib64',a.native/'apex/com.android.runtime.debug/lib64',a.native/'apex/com.android.runtime.debug/lib64/bionic',a.native/'apex/com.android.conscrypt/lib64',a.native/'apex/com.android.resolv/lib64',a.native/'apex/com.android.media/lib64',a.native/'apex/com.android.media.swcodec/lib64']
libraries={}
for directory in locations:
 if directory.is_dir():
  for f in directory.iterdir():
   if f.is_file()and f.name.endswith('.so'):libraries.setdefault(f.name,f)
queue=['libandroid_runtime.so','libandroid.so','libjavacrypto.so','libOpenSLES.so','libOpenMAXAL.so'];visited=set();host={'libc.so','libm.so','libdl.so','libstdc++.so'}
while queue:
 name=queue.pop()
 if name in visited or name in host:continue
 if name not in libraries:raise RuntimeError('Missing matching Android dependency '+name)
 visited.add(name);file=libraries[name];copy(file,'android-libs/'+name)
 dynamic=subprocess.check_output(['readelf','-d',str(file)],text=True);queue.extend(re.findall(r'\(NEEDED\).*\[([^]]+)\]',dynamic))
# Custom application loaders inspect the real platform ELF dependency files.
# Core execution remains translated by the linker's immutable-path aliases.
for name in sorted(host):
 if name not in libraries:raise RuntimeError('Missing Android core ELF '+name)
 copy(libraries[name],'android-libs/'+name)
# The Java framework's exact resources, not a different system build's IDs.
resources=Path('/home/art/api29-root/system/framework/framework-res.apk');copy(resources,'system/framework/framework-res.apk')
for directory in ['fonts','etc','usr']:
 source=a.native/directory;target=root/'system'/directory
 shutil.copytree(source,target,symlinks=False,ignore_dangling_symlinks=True)
# Keep the actual private host CA snapshot validated by the earlier TLS gate.
certs=root/'system/etc/security/cacerts'
if certs.exists():shutil.rmtree(certs)
shutil.copytree('/home/art/etc/security/cacerts',certs)
for f in Path('/home/art/usr/icu').glob('*.dat'):copy(f,'usr/icu/'+f.name)
for f in (a.native/'apex/com.android.runtime.debug/etc/icu').glob('*.dat'):copy(f,'usr/icu/'+f.name)
with zipfile.ZipFile(a.inputs/'android-all-10-robolectric-5803371.jar')as z:
 target=root/'usr/share/zoneinfo/tzdata';target.parent.mkdir(parents=True);target.write_bytes(z.read('usr/share/zoneinfo/tzdata'))
(root/'framework').symlink_to('system/framework',target_is_directory=True);(root/'etc').symlink_to('system/etc',target_is_directory=True);(root/'fonts').symlink_to('system/fonts',target_is_directory=True)
(root/'apex/com.android.runtime.debug/etc/icu').mkdir(parents=True)
for f in (root/'usr/icu').glob('icudt63*.dat'):(root/'apex/com.android.runtime.debug/etc/icu'/f.name).symlink_to('../../../../usr/icu/'+f.name)
properties='''ro.build.version.sdk=29
ro.build.version.release=10
ro.build.version.preview_sdk=0
ro.build.version.codename=REL
ro.build.version.all_codenames=REL
ro.build.version.security_patch=2019-09-05
ro.build.version.incremental=saidroid-api29-0.2
ro.build.id=SAILDROID29
ro.build.type=user
ro.build.tags=dev-keys
ro.build.fingerprint=saidroid/saidroid/saidroid:10/SAILDROID29/0.2:user/dev-keys
ro.product.brand=SailDroid
ro.product.manufacturer=SailDroid
ro.product.name=saidroid
ro.product.model=SailDroid
ro.product.device=saidroid
ro.hardware=saidroid-wayland
ro.product.cpu.abi=arm64-v8a
ro.product.cpu.abilist=arm64-v8a
ro.product.cpu.abilist64=arm64-v8a
ro.product.cpu.abilist32=
ro.sf.lcd_density=420
ro.opengles.version=0
ro.debuggable=0
'''
boot_image=None
if a.boot_image:
 recipe=json.loads((a.boot_image/'recipe.json').read_text());images=json.loads((a.boot_image/'manifest.json').read_text())
 expected=[name for name in boot if '/framework29-' not in name]
 assert {Path(name).name for name in recipe['files']}=={Path(name).name for name in expected}
 for source,sha in recipe['files'].items():
  target=root/'java/dex/art'/Path(source).name;assert target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==sha
 for name,sha in images.items():
  relative=Path(name);assert len(relative.parts)==2 and relative.parts[0]=='arm64' and relative.suffix in ['.art','.oat','.vdex']
  source=a.boot_image/relative;assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
  copy(source,'framework/'+name)
 boot_image=dict(path='framework/boot.art',files=len(images),manifest_sha256=hashlib.sha256((a.boot_image/'manifest.json').read_bytes()).hexdigest())
 copy(a.boot_image/'manifest.json','share/build/boot-image-manifest.json')
hardware=(root/'android-libs/libsdhwui-native.so').is_file()
if hardware:properties=properties.replace('ro.opengles.version=0','ro.opengles.version=196608')+'debug.hwui.renderer=skiagl\n'
if a.hardware_profile:
 from hardware_identity import apply_identity
 properties,identity=apply_identity(properties,json.loads(a.hardware_profile.read_text()))
 copy(a.hardware_profile,'share/build/hardware-identity/profile.json')
 target=root/'share/build/hardware-identity/resolution.json';target.write_text(json.dumps(identity,indent=2)+'\n')
 for source in ['hardware_identity.py','capture-hardware-identity-phone.py','hardware-identity-aliases.json']:
  copy(repo/'scripts/api29'/source,'share/build/hardware-identity/'+source)
(root/'build.prop').write_text(properties)
product_manifest=json.loads((a.product/'manifest.json').read_text())
(root/'runtime.json').write_text(json.dumps(dict(schema='saildroid-api29-component-v1',api=29,version='0.3.0',boot_jars=boot,renderer='hwui-gles-wayland' if hardware else 'software-wayland',native_namespaces='application-process',native_host=True,native_nice_limit=product_manifest.get('native_nice_limit',28),native_bootstrap=product_manifest.get('native_bootstrap'),binder_device=a.binder_device,boot_image=boot_image),indent=2)+'\n')
icons=root/'share/icons';icons.mkdir(parents=True);(icons/'saildroid.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128"><rect width="128" height="128" rx="28" fill="#173f58"/><path d="M29 83L57 26l39 57H29z" fill="#dceaf0"/><path d="M29 91h67" stroke="#58c5d7" stroke-width="8" stroke-linecap="round"/></svg>''')
subprocess.run(['python3',str(repo/'scripts/api29/make-startup-icon.py'),str(icons/'saildroid.png')],check=True)
for source in [repo/'native/ime/LICENSE.LGPL',repo/'native/ime/UPSTREAM.md',repo/'native/window/surface-extension.xml']:copy(source,'share/licenses/'+source.name)
copy(repo/'native/host/third_party/LICENSE.json.MIT','share/licenses/host-json-LICENSE.MIT')
copy(repo/'native/host/third_party/manifest.json','share/licenses/host-json-manifest.json')
if a.command_runtime:
 from command_runtime import validate_commands
 command_metadata=validate_commands(a.command_runtime,repo)
 copy(a.command_runtime/'toybox','bin/touch').chmod(0o755)
 copy(a.command_runtime/'manifest.json','share/build/android-commands/manifest.json')
 copy(a.command_runtime/'NOTICE','share/licenses/android-commands-NOTICE')
 metadata=json.loads((root/'runtime.json').read_text());metadata['private_commands']=command_metadata
 (root/'runtime.json').write_text(json.dumps(metadata,indent=2)+'\n')

copy(repo/'native/webview/qt-helper/UPSTREAM.md','share/licenses/webview-UPSTREAM.md')
if hardware:copy(repo/'native/hwui/UPSTREAM.md','share/licenses/hwui-UPSTREAM.md')
copy(repo/'native/webview/qt-helper/include/wpe-input.h','share/licenses/wpe-input.h')
# Normalize only our new component, never an existing phone/runtime directory.
files={};symlinks={}
for path in sorted(root.rglob('*')):
 if path.is_symlink():symlinks[str(path.relative_to(root))]=os.readlink(path)
 elif path.is_dir():path.chmod(0o755)
 elif path.is_file():
  if not str(path.relative_to(root)).startswith(('libexec/','bin/')):path.chmod(0o644)
  files[str(path.relative_to(root))]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size=path.stat().st_size,mode=path.stat().st_mode&0o777)
record=dict(schema='saildroid-api29-component-v1',api=29,files=files,symlinks=symlinks,bytes=sum(f['size']for f in files.values()))
(a.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with tarfile.open(a.output/'component.tar.gz','w:gz')as tar:tar.add(root,arcname='root',recursive=True);tar.add(a.output/'manifest.json',arcname='manifest.json')
print('API29_COMPONENT=packaged|files='+str(len(files))+'|bytes='+str(record['bytes'])+'|sha256='+hashlib.sha256((a.output/'component.tar.gz').read_bytes()).hexdigest())
