# Port compatibility regression checks

Run these checks in an aarch64 Linux build VM with the fixed API29 inputs and
JDK described in [BUILD.md](BUILD.md). They do not contact a phone.

```sh
python3 scripts/api29/tests/check-hardware-identity.py
python3 scripts/api29/tests/test-webview-geometry-vm.py \
  --android-jar build/codex-api29/inputs/android-all-10-robolectric-5803371.jar
python3 scripts/api29/tests/test-native-loader-vm.py
python3 scripts/api29/build-product.py build/codex-api29/inputs /new/output/product
```

Initialize the pinned submodules and apply their verified patches before the
product build. The geometry check compiles the production Java sizing and
touch-packet code, then passes its packets to the production native coordinate
mapping function. It checks the default viewport, supported tall viewports,
1080x2340, QHD, a 1600x2560 tablet viewport, landscape and integer extremes,
as well as input consumed after a resize, old clients without View extents and
moves outside the View. Host
dimensions and the 33.75 MiB frame budget (`2160 * 4096 * 4`) must both hold.
Supported viewports retain their requested dimensions.

The loader check compiles the production loader against small guest-linker and
ART-library stand-ins. It covers all four ART library names on API28 and
non-API28 bases, ordinary guest libraries, the separate FD-loader entry, error
clearing and an unavailable guest linker. The API28 marker is simulated through
a linker wrapper; the VM's `/system` is never modified.

Also run the existing Binder and activation fixtures as root in the Linux VM
under both `umask 022` and `umask 077`:

```sh
python3 scripts/packaging/test-binder-setup.py
python3 scripts/packaging/test-setup-vm.py --output /new/output/setup
```

The 2026-11-08 PR2 validation passed the complete `build-product.py` compile
(Java, D8, native libraries/host and Qt/WPE helper), 40 mapped-touch cases, both
loader branches and the missing-linker case, the hardware identity checks, and
10 Binder plus 35 activation fixtures under each umask (90 total).

These are build and isolated contract checks. They do not prove page rendering
or JNI registration on a real Android 9 device, and do not constitute a fresh
full CTS run or a rebuilt/released RPM. Test actual bottom-of-page controls
before and after resizing on each target port as part of device acceptance.
