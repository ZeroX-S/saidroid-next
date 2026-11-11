# SailDroid native application host

`libexec/saildroid-app` is the small CAP_DAC_OVERRIDE/CAP_SYS_RESOURCE bootstrap.
It restores its own `/proc/self/oom_score_adj` to zero, sets RLIMIT_NICE=40
(Android's nice -20..19 range), drops every capability, enables no_new_privs and execs
`libexec/saildroid-host` with the same PID. The unprivileged host pins its
component root, sets the ART environment, execs itself once, registers its
identity and maps the native Wayland window **before** waiting for Binder or
initializing ART. No exec occurs after window creation.

The OOM reset prevents application children from inheriting the desktop
service's memory protection. CAP_DAC_OVERRIDE permits this fixed self-only
write on vendor kernels exposing the control with mode 0400. Both capabilities
are cleared before any host or application library loads. New product manifests
declare `native_bootstrap` with schema `saildroid-native-bootstrap-v1` and
capabilities `cap_dac_override,cap_sys_resource=ep`. Packaging and activation
validate this exact set. Releases without this metadata retain the earlier
`cap_sys_resource=ep` policy.

Hosts spawning further processes retain `no_new_privs`. Their children verify
and keep an already-zero OOM adjustment, allowing startup after capability
removal. A restricted child inheriting a protected value fails before entering
the host when it cannot restore zero.

ART is created with the existing `JniInvocation`/`JNI_CreateJavaVM` API in this
same process. The early window thread has no JNIEnv until Java has installed
its handlers. It caches focus/visibility and publishes callbacks through an
explicit C hook table. `SdWindowHost.nativeStart()` binds to the existing
surface. Android HWUI continues through GLES/libhybris; no CPU readback or
software replacement was added to the GPU path.

The parent retains the installed application icon beneath real Android
subsurfaces. This is a native startup backdrop, including a fallback during
Activity surface replacement, not a simulated Android UI. The real app's
opaque buffers cover it. Sailfish Home currently snapshots that parent, so
these generic Cover cards show the app icon, **not live Android thumbnails**.

The ordinary-user session manager owns `org.saildroid.HostManager`. It checks
D-Bus UID/PID, executable identity, boot ID and start ticks. Registration
atomically selects one host per package/process role; duplicates activate the
existing host. Each app retains its launch ID, component path and APK record
hash. A per-package POSIX lock interlocks with installer update/uninstall.
The manager admits one heavy ART initialization at a time in FIFO order; early
window creation is outside that queue. The compositor remains authoritative
for focus, while the most recent activation request is tracked separately.

Declared service processes must belong to a live app launch generation. Host
exit terminates only that generation's services and its verified process-group
helpers. A non-parent manager cannot recover an exact exit code; unexpected
process termination is recorded with a null exit code. Manager restart can
re-adopt matching live host identities. These checks are lifecycle boundaries,
not a claim of per-app Linux sandboxing: Android apps still use the phone user.

Ordinary app hosts and their declared Activity/service/provider processes also
install a kernel seccomp filter that denies `link`/`linkat` with `EACCES`, matching
Android's app-domain hardlink restriction (b/19953790). TSYNC covers existing
D-Bus threads, and new threads/children inherit the filter. Installation failure
stops app startup. The trusted manager, Binder broker and session dispatcher
remain outside this restriction. Other file operations retain their existing
kernel behavior; this narrow rule does not provide a complete Android sandbox.

When a component includes the validated fdlibm companion, the host preloads it
before ART and verifies the actual owner of its `ieee_exp` entry point. This
corrects the old ARM64 fdlibm byte-order configuration while retaining the
phone's existing libopenjdk/JNI and ordinary host libc math. See
[`fdlibm-README.md`](../compat/fdlibm-README.md) for source/build boundaries.

`org.saildroid.host.HostApi` exposes typed JNI/D-Bus methods for opening apps,
starting services, reading host state and querying the three read-only MCE
methods. The SailDroid WebView environment wrapper is also a native executable;
its verified external WPE defaults are component data. Build, deploy and test
tools may remain Python/shell.

Declared Activity processes now use the same generation-owned native process
boundary as services. Private Binder carries the real Intent and Activity result;
the caller receives results before resuming. Reopening the application activates
its live foreground Activity process. Provider installation normalizes a missing
process name to the application's manifest default, and remote clients use the
owning process's real IContentProvider Binder. A provider in a new declared
process can start headlessly without creating a Cover. The ordinary APK contract
in `tests/device-remote-activity.py` checks separate processes, provider state,
physical page input, pixels, repeated entry and result ordering.

`SdBattery` supplies read-only battery properties from the Linux power-supply
device. Missing properties report unsupported; this bridge does not write power
settings. Component enabled-state queries use the selected APK's real declared
components and return DEFAULT while this package store has no user overrides.

Build in the phone-owning MeeGo Build VM:

```sh
bash native/host/build-host-vm.sh /var/tmp/saildroid-native-host-build
bash native/host/tests/run-vm.sh
```

The product builder calls the host builder, includes HostApi Java classes and
records all native source and payload hashes. The normal component packager
ships the binaries and native entry symlink. For the existing r86 release,
`package-native-overlay.py` creates an exact-manifest overlay and
`deploy-native-overlay.py` stages it into a new release; `--activate` changes
entries only after all old hosts are quiescent. Hold `scripts/devlock.sh` for
all mutating device work. Keep a verified previous release.

Tests use real disposable processes on a temporary VM session bus for dedup,
concurrent app identity, FIFO admission, lease authorization, generation-pinned
close, installation locks, service cleanup, helper cleanup and re-adoption.
The device scripts exercise physical drawer taps, early window and ART PID
identity, output pixels, overlapping app starts, repeat activation, actual Home
card taps and physical gesture close. Every visible run has an independent
blank watchdog and verifies actual backlight brightness 0 on cleanup.

Recovery after the exact r89→r95 transition, while holding the device lock and
with the OLED off:

```sh
python3 scripts/perf/close-owned-vm.py
python3 scripts/api29/restore-native-baseline.py
```

This restores the saved r86 launch indirection and desktop entries. It is an
explicit recovery action, not an automatic fallback after a failed test.

For this transition's exact source boundary, including exclusion of the
independent IME/crypto working changes, use the frozen-base build driver:

```sh
python3 scripts/api29/build-native-transition-vm.py \
  build/evidence/startup-mapping-20261030/r86-predecessor \
  /var/tmp/saildroid-native-transition-new
```

It records the base commit and overlay hashes. It never rewrites the working
tree or the accepted phone release. The packaged product manifest records its
actual source and artifact bytes; tarball timestamps/signatures need not be
bit-identical between builds.

## Character Unicode data

When the component includes `libsdcharacter-icu63.so`, the host preloads its
trusted original Character implementation and verifies the actual native symbol
owner plus the private ICU63/Unicode11 data before ART starts. The optional
helper preserves libopenjdk's JNI registration and other native implementations.
See `../compat/character-README.md` for its source and ABI boundaries. Components
without this optional library retain their existing launch behavior.

