# Port and runtime compatibility regression checks

Run the complete host regression, preflight, and native compilation suite in one command after running `bash tools/setup-dev-env.sh`:

```sh
python3 tools/run-tests.py
```

Or run individual isolated checks in a Linux build environment with JDK 21, `aidl`, `gcc`/`g++`, `pkg-config`, and the pinned API 28 inputs described in [BUILD.md](BUILD.md). They do not contact a phone.

```sh
python3 scripts/runtime/tests/check-hardware-identity.py
python3 scripts/runtime/tests/test-webview-geometry-vm.py \
  --android-jar build/inputs/android-all-9-robolectric-4913185-2.jar
python3 scripts/runtime/tests/test-native-loader-vm.py
python3 scripts/api28/tests/check-audio-output-registration.py --jni-include "$JAVA_HOME/include"
python3 scripts/api28/tests/check-audio-sink-metadata.py --jni-include "$JAVA_HOME/include"
python3 scripts/api28/tests/check-component-identity.py --jni-include "$JAVA_HOME/include"
python3 -m unittest discover -s scripts/compat/tests
for test in \
  test-process-startup.py \
  test-activity-clear-top.py \
  test-document-picker-render.py \
  test-explicit-broadcast-dispatch.py \
  test-popup-touch-target.py; do
  python3 "scripts/runtime/tests/$test"
done
python3 scripts/runtime/build-product.py build/inputs /tmp/saidroid-product-check --compat-only
```

Initialize the pinned submodules and apply their verified patches (`python3 tools/apply-third-party-patches.py`) before running the product build or native host checks.

The geometry check compiles the production Java sizing and touch-packet code, then passes its packets to the production native coordinate mapping function. Host dimensions and the 33.75 MiB frame budget (`2160 * 4096 * 4`) must both hold, while supported viewports retain their requested dimensions.

The loader check compiles the production loader against small guest-linker and ART-library stand-ins. When root privileges are available in an isolated Linux VM (never on Sailfish OS), also run the Binder and activation fixtures under both `umask 022` and `umask 077`:

```sh
python3 scripts/packaging/test-binder-setup.py
python3 scripts/packaging/test-setup-vm.py --output /tmp/saidroid-setup-check
```

These are build and isolated contract checks; test actual UI rendering, touch, audio, and WebView pages on each target Sailfish device before release acceptance.
