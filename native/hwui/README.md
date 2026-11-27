# HWUI native-window backend

Status: r85 is the default development component after fresh-boot device checks.
The earlier compositor/GPU wait did not recur in the final serial tests, but its
root cause remains unresolved; see the full report below.

The r85 component selects Android HWUI/Skia GLES rendering for applications that
request hardware acceleration. Its path is:

```
Android View -> RenderNode -> HWUI RenderThread -> GLES/EGL
             -> libhybris gralloc queue -> Wayland -> Lipstick
```

`SAILDROID_HWUI=0` selects the software diagnostic backend. An application whose
manifest explicitly disables application hardware acceleration selects that
backend automatically. No emulated success is returned for a missing native
producer.

## Build

Run builds inside the `MeeGo Build` VM. The helper needs Clang, AArch64 GNU ld,
and the exact selected component's Android libraries. The input download is
private to the workspace; it installs no phone packages:

```sh
python3 native/hwui/fetch-headers.py build/hwui
python3 native/hwui/build-helper-vm.py \
  build/hwui/headers build/hwui/libcxx-source \
  /var/tmp/saidroid-next-api29-native-20261025-r1/lib64 \
  build/hwui/native --compiler clang++
python3 scripts/runtime/build-product.py build/codex-api29/inputs \
  /var/tmp/saidroid-next-api29-product-hwui \
  --hwui-helper build/hwui/native/libsdhwui-native.so
```

The companion process-private pthread helper fixes a reproducible race in
lazy static mutex initialization. Its builder patches an output copy of the
nested translator source and records both source hashes:

```sh
python3 native/compat/build-pthread-helper-vm.py build/hwui/pthread-helper
```

Pass `--pthread-helper build/hwui/pthread-helper/libpthread_bio.so.0` to the
product build. It is preloaded only inside that component's ART processes.
The original host ART libraries and the nested source checkout stay intact.

Then build the manager APK and package the component through the ordinary
`scripts/runtime` entry points. The packager records the native helper hash,
ships the upstream boundary note, and selects the renderer in `runtime.json`.
The existing launcher gains no privileges beyond its previous narrow scheduling
capability. The Android process remains the ordinary phone user.

## Regression

These commands run in the VM, acquire the device lock, use unique logs, and
restore the previous component after each sample. They require an already
staged component. Device tests are serial. Do not run them against a busy phone.

```sh
python3 native/hwui/build-apk-vm.py hwui1
bash native/hwui/run-app-vm.sh my-hwui-lifecycle api29-my-staged-component

python3 scripts/perf/build-scroll-apk-vm.py hwui1
bash native/hwui/run-performance-vm.sh my-hwui-perf api29-my-staged-component

bash native/hwui/run-qq-vm.sh my-hwui-qq api29-my-staged-component
bash native/hwui/run-manager-vm.sh my-hwui-manager api29-my-staged-component
```

The Activity probe requires actual hardware View/Canvas flags, touch-handled
count changes, a second dialog GPU surface, dialog dismissal, two physical
background swipes followed by same-process foregrounding, bounded idle CPU,
and a zero exit status. The performance probe counts actual Wayland buffer
attachments and Android FrameMetrics. Driver invalidation counts are not used
as presented-frame counts.

QQ's check opens its unauthenticated Help -> QQ Safety Center path, without
submitting credentials or altering account settings. A pass also needs the
pixel gate and visual inspection of the final H5 screenshot:

```sh
python3 native/webview/qt-helper/check-qq-frame.py build/hwui/my-hwui-qq-h5.png
```

Every visible interval has an independent blank watchdog. The scripts restore
the previous component and require actual backlight brightness 0. Compositor
PID and phone boot identity must stay unchanged within each accepted run.
A no-surface Wayland sync tool must also receive a real compositor response
before and after each run; PID liveness alone is insufficient. It is built and
staged privately by `prepare-health-vm.sh`, without a desktop entry.

Full results and remaining limits: [HWUI report](../../docs/HWUI-NATIVE-2026-10-29.md).

See [UPSTREAM.md](UPSTREAM.md) for the ABI contract and current API boundaries.

The later r86 API29 compatibility gate additionally verifies first-frame mapping
and resumed static content before input can trigger a redraw. See
[the compatibility report](../../docs/ANDROID-COMPATIBILITY-2026-10-29.md) and
[`scripts/compat/README.md`](../../scripts/compat/README.md) for the upstream
JUnit subset, framework contracts, WebView checks and controlled performance.
