#!/usr/bin/env python3
"""Reproduce the native transition without including unrelated working changes.

Freeze the accepted Git base, then overlay only native-host sources and the
explicit Java/package changes in this transition. The verified crypto and WebView IME implementation
are included; other working changes stay excluded. Outputs must be new directories.
"""
from pathlib import Path
import argparse,hashlib,io,json,shutil,subprocess,tarfile
p=argparse.ArgumentParser();p.add_argument('predecessor',type=Path);p.add_argument('work',type=Path);p.add_argument('--base',default='230a3f734fd3708c805cd9270cb0ea66a1d53902');p.add_argument('--platform-runtime',type=Path);p.add_argument('--media-runtime',action='store_true');p.add_argument('--core-runtime',type=Path);p.add_argument('--framework-runtime',type=Path);p.add_argument('--codec-performance-profile',type=Path);p.add_argument('--boot-image',type=Path);p.add_argument('--rs-tools',type=Path);p.add_argument('--linker-runtime',type=Path);p.add_argument('--art-runtime',type=Path);p.add_argument('--native-icu-runtime',type=Path);p.add_argument('--hiddenapi-runtime',type=Path);p.add_argument('--strictmath-runtime',type=Path);p.add_argument('--character-runtime',type=Path);p.add_argument('--command-runtime',type=Path);p.add_argument('--canonical-core-jar-names',action='store_true');p.add_argument('--prepare-only',action='store_true',help='Freeze and compile exact product/manager inputs before encoding metadata for the new runtime JAR');a=p.parse_args();repo=Path(__file__).resolve().parents[2];assert not a.work.exists();a.work.mkdir(parents=True);source=a.work/'source';source.mkdir()
commit=subprocess.check_output(['git','rev-parse',a.base+'^{commit}'],cwd=repo,text=True).strip();data=subprocess.check_output(['git','archive',commit],cwd=repo)
with tarfile.open(fileobj=io.BytesIO(data))as archive:archive.extractall(source,filter='data')
# Repository-owned implementation paths only; no nested repository changes.
paths=['scripts/device/SdWindowManager.java','scripts/device/SdWindowSession.java','scripts/device/SdInstrumentation.java','scripts/device/SdActivityManagerService.java','scripts/device/SdAudio.java','scripts/device/SdBattery.java','scripts/device/SdPackageManagerService.java','scripts/device/SdContentProviders.java','scripts/device/SdRuntime.java','scripts/device/SdRuntimeControl.java','scripts/device/SdRemoteActivities.java','scripts/device/SdApkPackage.java','scripts/device/SdServiceEndpoint.java','native/launcher/sdruntime-control.c','scripts/device/SdWebViewProvider.java','native/webview/qt-helper/sdwebviewd.cpp','native/webview/qt-helper/webkit-ime.h','native/webview/qt-helper/build-host-vm.sh','scripts/device/SdCryptoProvider.java','scripts/device/SdActivityHost.java','scripts/device/SdActivityTaskManager.java','scripts/device/SdInputManager.java','scripts/device/SdServices.java','native/window/sdwindow.c','native/hwui/sd-hwui-background.c','native/hwui/sd-hwui-host.c','scripts/device/SdWindowHost.java','scripts/device/SdSurfaceStore.java','native/webview/qt-helper/native-host.cpp','native/webview/qt-helper/runtime-env.sailfish52.json','scripts/api29/build-product.py','scripts/api29/package-component.py','scripts/api29/make-startup-icon.py','scripts/device/SdHostState.java','scripts/device/SdRemoteServices.java','scripts/device/SdBinderRegistry.java','scripts/device/org/saildroid/host/HostApi.java','scripts/device/org/saildroid/manager/SdAppRegistry.java','scripts/device/org/saildroid/manager/NativeHost.java']
paths.extend(['native/window/native-display-events.c', 'native/window/native-display-events.h'])
for name in paths:
 target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/name,target)
for name in ['scripts/device/SdClassLoaderNamespaces.java','native/saidroid-system-paths.h','native/compat/api29-renderscript.c','native/compat/api29-hardware-properties.c','native/compat/api29-eventlog.c','native/compat/api29-diagnostics.c','native/compat/api29-native-loader.c','native/compat/api29-hardware-loader.c','native/api29-jni-entries.inc','native/compat/api29-cfi.c','scripts/device/sdbridge.c','scripts/device/SdSharedLibraries.java','scripts/device/SdInstrumentationFiles.java','scripts/device/SdWifi.java','scripts/device/SdTls.java','scripts/device/SdDownloadsProvider.java']:
 paths.append(name);target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/name,target)
shutil.copytree(repo/'native/host',source/'native/host',dirs_exist_ok=True)
shutil.copytree(repo/'third_party/art-standalone/libnativehelper/include',source/'third_party/art-standalone/libnativehelper/include',dirs_exist_ok=True)
# Runtime/process sources above are explicit overlays. No transformation of
# the old runtime is needed, so the recipe hashes exactly what it compiles.

inputs=repo/'build/codex-api29/inputs';product=a.work/'product';manager=a.work/'manager';bundle=a.work/'bundle'
subprocess.run(['python3',str(source/'scripts/api29/build-product.py'),str(inputs),str(product)],check=True)
subprocess.run(['python3',str(source/'scripts/api29/build-manager.py'),str(inputs),str(product),'/home/art/api29-root/system/framework/framework-res.apk',str(manager)],check=True)
if a.prepare_only:
 record=dict(base=commit,overlays={name:hashlib.sha256((source/name).read_bytes()).hexdigest()for name in paths},output=str(bundle),predecessor=str(a.predecessor),predecessor_manifest_sha256=hashlib.sha256((a.predecessor/'install-manifest.json').read_bytes()).hexdigest(),state='compiled-inputs-only',product_manifest_sha256=hashlib.sha256((product/'manifest.json').read_bytes()).hexdigest(),manager_manifest_sha256=hashlib.sha256((manager/'manifest.json').read_bytes()).hexdigest())
 (a.work/'transition-preparation.json').write_text(json.dumps(record,indent=2)+'\n');print('NATIVE_TRANSITION=PREPARED|work='+str(a.work));raise SystemExit(0)
package=['python3',str(repo/'scripts/api29/package-native-overlay.py'),str(a.predecessor),str(product),str(manager),str(bundle)]
if a.platform_runtime:package+=['--platform-runtime',str(a.platform_runtime)]
if a.media_runtime:package+=['--media-runtime']
if a.core_runtime:package+=['--core-runtime',str(a.core_runtime)]
if a.framework_runtime:package+=['--framework-runtime',str(a.framework_runtime)]
if a.codec_performance_profile:package+=['--codec-performance-profile',str(a.codec_performance_profile)]
if a.boot_image:package+=['--boot-image',str(a.boot_image)]
if a.rs_tools:package+=['--rs-tools',str(a.rs_tools)]
if a.linker_runtime:package+=['--linker-runtime',str(a.linker_runtime)]
if a.art_runtime:package+=['--art-runtime',str(a.art_runtime)]
if a.native_icu_runtime:package+=['--native-icu-runtime',str(a.native_icu_runtime)]
if a.strictmath_runtime:package+=['--strictmath-runtime',str(a.strictmath_runtime)]
if a.character_runtime:package+=['--character-runtime',str(a.character_runtime)]
if a.command_runtime:package+=['--command-runtime',str(a.command_runtime)]
if a.hiddenapi_runtime:package+=['--hiddenapi-runtime',str(a.hiddenapi_runtime)]
if a.canonical_core_jar_names:package+=['--canonical-core-jar-names']
subprocess.run(package,check=True)
record=dict(base=commit,overlays={name:hashlib.sha256((source/name).read_bytes()).hexdigest()for name in paths},output=str(bundle),predecessor_manifest_sha256=hashlib.sha256((a.predecessor/'install-manifest.json').read_bytes()).hexdigest());(a.work/'transition-recipe.json').write_text(json.dumps(record,indent=2)+'\n');print('NATIVE_TRANSITION=BUILT|bundle='+str(bundle))
