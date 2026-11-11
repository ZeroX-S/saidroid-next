#!/usr/bin/env python3
"""Build the API 29 product from source; never imports the old /tmp/ap stubs."""
from pathlib import Path
import argparse,subprocess,os,json,hashlib
p=argparse.ArgumentParser();p.add_argument('inputs',type=Path);p.add_argument('output',type=Path);p.add_argument('--hwui-helper',type=Path);p.add_argument('--pthread-helper',type=Path);args=p.parse_args();assert not args.output.exists();args.output.mkdir(parents=True)
repo=Path(__file__).resolve().parents[2];java=Path(os.environ.get('JAVA_HOME','/tmp/jdkfull/jdk-21.0.13+9'))/'bin';fw=args.inputs/'android-all-10-robolectric-5803371.jar';r8=args.inputs/'r8-8.3.37.jar'
subprocess.run(['python3',str(repo/'native/webview/tools/check-clinit-safety.py'),str(repo/'scripts/device/SdWebViewProvider.java')],check=True)
classes=args.output/'classes';classes.mkdir()
names='SdBridge SdStartup SdClassLoaderNamespaces SdGraphicsEnvironment SdRuntime SdRuntimeDiagnostics SdViewDump SdViewRepair SdRuntimeControl SdKernelServices SdBinderRegistry SdSensorService SdServiceEndpoint SdRemoteServices SdApkPackage SdAppPermissions SdActivityManagerService SdActivityTaskManager SdActivityHost SdServiceHost SdServiceManagerStub SdServices SdPackageManagerService SdStorageManager SdUsers SdDisplayShim SdWindowHost SdWindowManager SdWindowSession SdDisplayFrames SdSurfaceStore SdSurfaceControls SdMaliit SdInputManager SdInputMethods SdConnectivity SdHostState SdPower SdKeyguard SdNotificationPolicy SdContentService SdContentProviders SdSettingsProvider SdWebEngine SdWebInterfaces SdWebCookies SdWebViewProvider SdCryptoProvider'.split()
names.extend(['SdRemoteActivities','SdBattery','SdAudio','SdInstrumentation','SdNetworkStats','SdThermal','SdDeviceIdle'])
names.extend(['SdDocumentPicker','SdDocumentsProvider'])
sources=[repo/'scripts/device'/(name+'.java')for name in names]+sorted((repo/'scripts/device/org/saildroid/manager').glob('*.java'))+sorted((repo/'scripts/device/org/saildroid/host').glob('*.java'))
sources.append(repo/'scripts/device/SdSharedLibraries.java')
sources.append(repo/'scripts/device/SdInstrumentationFiles.java')
sources.append(repo/'scripts/device/SdWifi.java')
sources.append(repo/'scripts/device/SdTls.java')
sources.append(repo/'scripts/device/SdDownloadsProvider.java')
with(args.output/'javac.log').open('xb')as log:subprocess.run([str(java/'javac'),'--release','8','-nowarn','-cp',str(fw),'-d',str(classes),*[str(f)for f in sources]],check=True,stdout=log,stderr=subprocess.STDOUT)
with(args.output/'d8.log').open('xb')as log:subprocess.run([str(java/'java'),'-Xmx2g','-cp',str(r8),'com.android.tools.r8.D8','--release','--min-api','29','--lib',str(fw),'--output',str(args.output/'runtime.jar'),*[str(f)for f in sorted(classes.rglob('*.class'))]],check=True,stdout=log,stderr=subprocess.STDOUT)
with(args.output/'native-build.log').open('xb')as log:
 subprocess.run(['g++','-c','-fPIC','-O2','-Wall','-fno-exceptions','-fno-rtti','-o',str(args.output/'binder.o'),str(repo/'native/compat/api29-binder.cpp'),'-I'+str(java.parent/'include'),'-I'+str(java.parent/'include/linux')],check=True,stdout=log,stderr=subprocess.STDOUT)
 subprocess.run(['bash',str(repo/'native/host/build-host-vm.sh'),str(args.output)],check=True,stdout=log,stderr=subprocess.STDOUT)
 subprocess.run(['gcc','-c','-fPIC','-O2','-Wall','-Dsd_activation_start=sd_runtime_control_start','-Dsd_activation_stop=sd_runtime_control_stop','-o',str(args.output/'runtime-control.o'),str(repo/'native/window/sdactivate.c')],check=True,stdout=log,stderr=subprocess.STDOUT)
 subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-o',str(args.output/'libsdbridge.so'),str(repo/'scripts/device/sdbridge.c'),str(repo/'native/compat/api29-memory.c'),str(repo/'native/compat/api29-eventlog.c'),str(repo/'native/compat/api29-hardware-properties.c'),str(args.output/'binder.o'),str(args.output/'runtime-control.o'),str(repo/'native/launcher/sdruntime-control.c'),'-I'+str(java.parent/'include'),'-I'+str(java.parent/'include/linux'),'-ldl','-pthread'],check=True,stdout=log,stderr=subprocess.STDOUT)
 xml='/usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml'
 subprocess.run(['wayland-scanner','client-header',xml,str(args.output/'xdg-shell-client-protocol.h')],check=True,stdout=log,stderr=subprocess.STDOUT)
 subprocess.run(['wayland-scanner','private-code',xml,str(args.output/'xdg-shell-protocol.c')],check=True,stdout=log,stderr=subprocess.STDOUT)
 subprocess.run(['wayland-scanner','client-header',str(repo/'native/window/surface-extension.xml'),str(args.output/'surface-extension-client-protocol.h')],check=True,stdout=log,stderr=subprocess.STDOUT)
 subprocess.run(['wayland-scanner','private-code',str(repo/'native/window/surface-extension.xml'),str(args.output/'surface-extension-protocol.c')],check=True,stdout=log,stderr=subprocess.STDOUT)
 flags=subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','libpng'],text=True).split()
 subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-o',str(args.output/'libsdwindow.so'),str(repo/'native/window/sdwindow.c'),str(repo/'native/window/native-display-events.c'),str(repo/'native/hwui/sd-hwui-host.c'),str(repo/'native/hwui/sd-hwui-background.c'),str(repo/'native/window/sdcontrol.c'),str(repo/'native/window/sdactivate.c'),str(args.output/'xdg-shell-protocol.c'),str(args.output/'surface-extension-protocol.c'),'-I'+str(args.output),'-I'+str(java.parent/'include'),'-I'+str(java.parent/'include/linux'),*flags,'-pthread','-ldl'],check=True,stdout=log,stderr=subprocess.STDOUT)
 subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-o',str(args.output/'libsdhost29.so'),str(repo/'native/compat/api29-host.c'),str(repo/'native/compat/api29-fdsan.c'),str(repo/'native/compat/api29-signal.c'),str(repo/'native/compat/api29-diagnostics.c'),str(repo/'native/compat/api29-regex.c'),str(repo/'native/compat/api29-egl-host.c'),str(repo/'native/compat/api29-thread.c'),str(repo/'native/compat/api29-cfi.c'),str(repo/'native/compat/api29-renderscript.c'),str(repo/'native/compat/api29-native-loader.c'),str(repo/'native/compat/api29-hardware-loader.c'),'-I'+str(java.parent/'include'),'-I'+str(java.parent/'include/linux'),'-ldl','-pthread'],check=True,stdout=log,stderr=subprocess.STDOUT)
import json as _json
xml=(repo/'native/ime/minputmethodcontext1interface.xml').read_text()
(args.output/'maliit-client-xml.h').write_text('static const char maliit_client_xml[]='+_json.dumps(xml)+';\n')
ime_flags=subprocess.check_output(['pkg-config','--cflags','--libs','gio-2.0'],text=True).split()
with(args.output/'ime-build.log').open('xb')as log:
 subprocess.run(['gcc','-shared','-fPIC','-O2','-Wall','-o',str(args.output/'libsdmaliit.so'),str(repo/'native/ime/sdmaliit.c'),'-I'+str(args.output),'-I'+str(java.parent/'include'),'-I'+str(java.parent/'include/linux'),*ime_flags,'-pthread'],check=True,stdout=log,stderr=subprocess.STDOUT)
subprocess.run(['bash',str(repo/'native/webview/qt-helper/build-host-vm.sh'),str(args.output/'webview-host')],check=True)
record=dict(api=29,native_nice_limit=40,native_bootstrap=dict(schema='saildroid-native-bootstrap-v1',capabilities='cap_dac_override,cap_sys_resource=ep'),sources={str(f.relative_to(repo)):hashlib.sha256(f.read_bytes()).hexdigest()for f in sources},files={n:hashlib.sha256((args.output/n).read_bytes()).hexdigest()for n in ['runtime.jar','libsdbridge.so','libsdwindow.so','libsdhost29.so','libsdmaliit.so','saildroid-app','saildroid-host','libsdhostapi.so']})
record['webview_host']=dict(files={name:hashlib.sha256((args.output/'webview-host'/name).read_bytes()).hexdigest() for name in ['sdwebviewd','sdwebview-host','webview-engine.qml','webview-host-env.json']},sources={str(f.relative_to(repo)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((repo/'native/webview/qt-helper').rglob('*')) if f.is_file() and f.suffix in ['.cpp','.h','.qml','.sh','.md','.json']})
native_sources=[repo/'native/api29-jni-entries.inc',repo/'scripts/device/sdbridge.c']
native_sources+=sorted((repo/'native/compat').glob('*.[ch]'))+sorted((repo/'native/window').glob('*.c'))+sorted((repo/'native/hwui').glob('*.c'))+sorted((repo/'native/hwui').glob('*.cpp'))
native_sources+=sorted((repo/'native/host').glob('*.cpp'))+sorted((repo/'native/host').glob('*.hpp'))+sorted((repo/'native/host').glob('*.c'))+sorted((repo/'native/host').glob('*.sh'))+sorted((repo/'native/host/third_party').glob('*'))
record['native_sources']={str(f.relative_to(repo)):hashlib.sha256(f.read_bytes()).hexdigest() for f in native_sources}
record['application_filesystem_policy']=dict(schema='saildroid-app-filesystem-v1',backend='kernel-seccomp-tsync',hardlinks_errno='EACCES',scope='application-and-declared-processes',excluded_roles=['manager','broker','session'],source_sha256=record['native_sources']['native/host/app-filesystem-policy.hpp'])
if args.hwui_helper:
 import shutil
 helper=args.hwui_helper;assert helper.is_file()
 assert 'AArch64' in subprocess.check_output(['readelf','-h',str(helper)],text=True)
 shutil.copyfile(helper,args.output/'libsdhwui-native.so')
 record['hwui_helper']=dict(sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),source_sha256=hashlib.sha256((repo/'native/hwui/sd-hwui-native.cpp').read_bytes()).hexdigest())
if args.pthread_helper:
 import shutil
 helper=args.pthread_helper;assert helper.is_file()
 assert 'AArch64' in subprocess.check_output(['readelf','-h',str(helper)],text=True)
 shutil.copyfile(helper,args.output/'libpthread_bio.so.0')
 record['pthread_helper']=dict(sha256=hashlib.sha256(helper.read_bytes()).hexdigest())
(args.output/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');print('API29_PRODUCT=compiled|'+str(args.output))
