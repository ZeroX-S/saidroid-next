# Isolated runtime distribution

These VM-only tools assemble an exact accepted component snapshot, add captured
phone support libraries, and build an inert development RPM. They do not contact
the phone, install packages, activate a release, provision users/data directories,
change services, or enable app AOT caches.

Run them through the existing MeeGo Build wrapper. The repository's shared VM
path is `/media/psf/Home/WorkSpace/saidroid-next`. Use script files for Parallels
commands rather than multiline `python -c` arguments.

## Pipeline

1. `audit-runtime-inputs-vm.py --overlay ... --expected-manifest SHA --output DIR`
   pins the full install manifest and locates every input by size and SHA-256.
2. `assemble-runtime-vm.py --audit DIR/input-audit.json --output ASSEMBLY
   --release-id ID [--compiler COMPILER]` materializes the accepted bytes and
   modes. It checks that the compiler's ART identity matches the component.
3. `relink-host-origin-vm.py --reference HOST-BUILD.json --root ASSEMBLY/root
   --output BUILD` first reproduces the exact accepted host binary, then changes
   only `RUNPATH=/home/art/lib` to `$ORIGIN/../lib`. This is needed because the
   capability bootstrap clears loader environment variables before host startup.
4. `add-phone-support-vm.py --root ASSEMBLY/root --capture CAPTURE --output JSON`
   verifies a captured phone manifest and adds missing library bytes, preserving
   every existing component file. Captured libraries use mode 0644; the RPM owns
   them as root. Symlink source/resolved paths remain in the provenance, while
   the payload materializes the captured bytes under each needed basename.
5. `audit-runtime-elf-vm.py --root ASSEMBLY/root --no-legacy-fallback --output JSON`
   records the host dependency closure and Android ELF inventory. This static
   gate does not prove runtime `dlopen`, WebView, or GUI behavior.
6. Freeze the root's exact files, modes, links, and directories as the JSON
   returned by `inventory()` in `build-runtime-rpm-vm.py`. Invoke the builder
   with `--root`, `--manifest`, `--manifest-sha256`, `--release-id`, `--version`,
   `--rpm-release`, and a new `--output` directory. A snapshot mismatch fails
   before building. The builder checks RPM identity, capabilities, scriptlets,
   and every extracted payload byte/mode/link.

The RPM name includes the release ID and owns only
`/opt/saildroid/releases/<release-id>` plus the two parent directories. It uses
explicit host ABI requirements, no automatic Android/Bionic providers, no
stripping, and a gzip payload compatible with the observed RPM 4.16 target.
The sealed `native_bootstrap` policy selects either `cap_sys_resource=ep` or
`cap_dac_override,cap_sys_resource=ep` for `libexec/saildroid-app`. Older releases
default to the former. The bootstrap drops all capabilities before entering
the host. The sealed `rpm_activation` policy controls installation scriptlets.
The only permitted APKs are the component's
`share/manager.apk` and `system/framework/framework-res.apk`; user/test APKs,
application data, desktop registration, and service units are rejected.

## 2026-11-10 video inventory and OOM policy

`SdMediaProvider` reads video width, height, duration and rotation through the
existing `MediaMetadataRetriever`, caching the results with each file's size
and modification time. Existing files are indexed when the updated application
process starts. Unsupported media retains zero metadata. The provider continues
to reconcile additions, changes and removals through the same transactional
inventory.

The r323i build overlays the two changed provider classes into the retained
297-class runtime, preserves all 2664 existing hidden-API member flags and
rebuilds all 42 matching boot-image outputs. Its small bootstrap is built after
byte-identical reproduction of the r323h bootstrap. The complete extracted RPM
inventory and its declared capabilities must pass verification before activation.
The package records these inputs and recipes under
`share/build/qq-video-metadata-20261110`.

The device bootstrap regression covers an inherited -1000 adjustment, an
already-zero child with `no_new_privs`, and a protected restricted child that
must fail. Successful entries report UID 100000, adjustment zero, cleared
effective/permitted/inheritable/ambient capabilities and `no_new_privs=1`.

Run `scripts/packaging/test-setup-vm.py --output NEW_DIRECTORY` as root in a
Linux build VM for activation and capability regressions. The video APK fixture
source is `native/media/gstreamer-player/tests/VideoThumbnailActivity.java`.
Build it with the pinned API28 SDK, a synthetic `clip.mp4` asset and explicit
READ_EXTERNAL_STORAGE permission. Launch through the ordinary app entry point
with valid device video fixtures. It checks OOM adjustment, seven thumbnail
operations and MediaStore metadata against the retriever's actual values.

The Xiaomi Pad 5/NABU device validation installed
`saildroid-runtime-api28-r323i-dev-20261110-0.321.60-67.aarch64` and obtained
`rpm -V` success plus setup status `ready`. The RPM SHA256 is
`9c42d73435e0aff707b7819ef994fa0a53ed304ff44bfc906acc05f2c283d4ef`.
The SDK build used `SailfishOS-latest-aarch64` through
`tools/sailfish-wsl-build.sh` and retained its command, input manifests and
payload recipes in the build records.

All 68 activation/capability cases and the three device bootstrap cases passed.
The ordinary APK fixture verified seven synthetic thumbnail operations and
metadata for three valid 720x1280 videos. A second ordinary-entry run verified
mini and 180x135 grid thumbnails for each real video with varied pixels. The
application had OOM adjustment zero, cleared active capability sets and
`no_new_privs=1`. The installation and device probes retained a single boot ID.
QQ's video picker still requires a physical visual retest.

## 2026-11-10 local document selection

QQ's resource `0x7f121541` reports a missing `GET_CONTENT` or `OPEN_DOCUMENT`
handler. `SdDocumentPicker` supplies the fallback intent handler in the
requesting application's task. It browses the real SailDroid shared directory
and the user's Downloads, Documents, Pictures, Videos and Music directories.
Directory listing runs on a worker, with a 10000-entry limit per directory.
MIME filters, cancellation, initial external-storage document URIs, repeated
requests and selections of up to 256 files use the Activity result path.

`SdDocumentsProvider` stores selected read handles in an app-owned SQLite
database. Each handle resolves to a readable regular file in those shared
folders. Queries return the actual name, size, MIME type and path. File opens
validate the canonical path and use `O_NOFOLLOW`. `OPEN_DOCUMENT` handles
support persisted read grants and access from the application's other
declared processes. The first MIME lookup is handled through ActivityManager's
provider MIME entry point.

The native host and manager share component-name validation for Activity,
Service and Provider startup, including nested classes with `$`. The native
build records a byte-identical baseline and verifies the candidate's dynamic
dependencies, runpath and exported interfaces.

The workspace recipe is `artifacts/qq-file-path-20261110/prepare_package_k.py`.
It builds the r323k payload from the verified r323i release, installs the
308-class runtime and all 42 matching boot-image outputs, binds the final
linker paths and seals the activation manifest. The runtime merger retains
2666 existing member flags and encodes 89 new internal members. The RPM build
uses `SailfishOS-latest-aarch64` through `tools/sailfish-wsl-build.sh`. Build
commands, source hashes and image inputs are packaged under
`share/build/document-picker-20261110`.

The ordinary APK fixture is `scripts/device/tests/DocumentPickerActivity.java`.
Its file operations and automated selections target its own temporary shared
files. It exercises single and multiple results, openable metadata, document
bytes, linked replacements, persisted reads in a declared secondary process,
cancellation, removed files and a repeated request to the live picker.

Device validation on Xiaomi Pad 5/NABU installed
`saildroid-runtime-api28-r323k-dev-20261110-0.321.62-69.aarch64` and passed
`rpm -V` plus setup status `ready`. The RPM SHA256 is
`b7c0f65a25fd5b048b46d17c844cef3e383eb6c3d43da100624193d1ab1533fc`.
Its extracted inventory contains 3623 files and 15 symlinks.

The ordinary APK fixture passed single and multiple results, first MIME lookup,
actual file bytes, linked replacement rejection, persisted reads from its
nested secondary Activity, cancellation, removed files and repeated requests.
The process ran with OOM adjustment zero, all four Linux capability sets zero
and `no_new_privs=1`. Fixture files, app data, process state and diagnostic
backups were cleaned after verifying their identities. Installation and tests
used boot ID `4617bb3e-7fb9-4a85-8459-9c5a640a78bf`.

The QQ acceptance step is to choose a file from its send-file page and confirm
the selection returns to QQ.

## 2026-11-10 document picker GPU rendering

The r323k regression APK disabled application hardware acceleration. With
acceleration enabled, the picker attempted software drawing into a GPU Surface
and ViewRootImpl reported `Could not lock surface`. `SdDocumentPicker` now sets
`ActivityInfo.FLAG_HARDWARE_ACCELERATED` when the selected window backend uses
HWUI. The fixture checks its actual DecorView acceleration before selecting files.

The same accelerated APK failed on r323k and passed on r323l. Both accelerated
and software variants passed selection, cancellation, repeated requests and
persisted cross-process reads. The accelerated run created picker EGL windows
and completed GPU swaps with zero surface-lock errors.

The installed RPM is
`saildroid-runtime-api28-r323l-dev-20261110-0.321.63-70.aarch64`, with SHA256
`1ed3cb17c3636e98ec50891a5466cc0cc31cd3d3d32c8dfd80b0c6510e247f09`.
Its extracted inventory contains 3633 files and 15 symlinks. Runtime rebuild
commands, source hashes and native boot-image inputs are packaged under
`share/build/document-picker-rendering-20261110`. The runtime update preserves
307 other classes and all 2755 existing member access flags.

## 2026-11-09 API28 Java compatibility updates

Partial runtime updates compile the changed Java sources with `javac --release 8`
against the pinned API28 framework, then run D8 with `--min-api 28`.
`scripts/api28/MergeRuntimeDex.java` accepts
`BASELINE.dex OVERLAY.dex OUTPUT.dex --preserve-synthetic` to retain earlier
synthetic accessors and constructor bridges referenced by retained classes.
The merged JAR passes through `scripts/api28/encode-platform-dex.py`, followed
by a comparison of every existing member and its hidden-API flags.

Rebuild the matching boot images whenever the runtime JAR changes. Record the
compiler identity, all boot JAR hashes, final logical locations, and emitted
ART/OAT/VDEX hashes. Reseal the activation manifest after staging the new JAR,
images, source records, and runtime metadata. Verify the complete extracted RPM
inventory, scriptlets, capabilities, dependencies, and installed release.

The network and toast repair records live in
`share/build/network-miniapp-20261109` within the r322y RPM. The source includes
`scripts/device/tests/check-connectivity-callbacks.py` and
`scripts/device/tests/check-toast-queue.py` for callback and toast lifecycle
regressions. Host network observations project the existing snapshot helper's
DNS and routes and derive validation from the matching ConnMan service's
`online` state. The default Android network continues to use the host resolver
through network ID zero.

The r322z API28 address parser correction is recorded in
`share/build/network-miniapp-api28-20261109`. Compile the canonical
`scripts/device/SdConnectivitySnapshot.java` together with `SdConnectivity`
and `SdHostNetworkObservation`. It uses API28's
`NetworkUtils.numericToInetAddress` for strict numeric address parsing. Verify
the installed build through an ordinary APK using `ConnectivityManager`,
`Network.getAllByName`, and the public `Toast` API, including attachment,
timeout, and cancellation.

## 2026-11-09 WPE runtime dependencies

The r323e runtime records its engine inputs in
`share/build/webview-runtime-20261109/runtime-manifest.json`. Install the
runtime and these aarch64 engine packages in one RPM transaction.

| Package | Minimum version and release (`>=`) |
| --- | --- |
| libepoxy | 1.5.11-768.1 |
| libwpe | 1.17.0-768.1 |
| wpebackend-fdo | 1.17.0-768.1 |
| wpewebkit2 | 2.54.2-768.1 |
| wpewebkit2-qt5 | 2.54.2-768.1 |

Verify the repository signature, each RPM signature, and the payload SHA-256
from the signed primary metadata before staging. Download the aarch64 RPMs
from the rolling engine repository. Build 768.1 corresponds to Atlantic source
revision `b36d176b1374aab8c6b4bde582d10bf6ff50819e`. Later builds satisfy these
minimum version requirements. [Engine download directory](https://specsierra.github.io/atlantic-engine/aarch64/) · [Repository configuration](https://specsierra.github.io/atlantic-engine/atlantic-ci.repo)

To install the dependencies as root on Sailfish OS, import the repository key
and add its configuration.

```sh
rpm --import https://specsierra.github.io/atlantic-engine/RPM-GPG-KEY-atlantic-ci
zypper ar -f https://specsierra.github.io/atlantic-engine/atlantic-ci.repo
zypper ref atlantic-ci
zypper in libepoxy libwpe wpebackend-fdo wpewebkit2 wpewebkit2-qt5
```

The key fingerprint is `A6CCF45E59F159B687BF268C5AE893A84F8F9C4B`.
`build-runtime-rpm-vm.py` verifies the manifest hash recorded in
`host_webview_runtime` and derives each configured dependency's minimum RPM
epoch, version and release from `engine_rpms`.

WebKit uses its compiled `/opt/wpe-sfos` helper paths. SailDroid packages the
required compatibility library closure under its own `lib/webview` directory,
with source records and license notices. `sdwebview-host` expands
`${SD_COMPONENT}` to its canonical release root when configuring the isolated
process. The libsoup boundary resolves its SONAME through that configured
library path. The runtime RPM requires at least the recorded versions of all
five engine dependencies. The
release-owned `libegl-stubs.so` supplies EGL 1.5 entry points through the
platform KHR functions. Configure both `LD_PRELOAD` and
`ATLANTIC_LD_PRELOAD`, and propagate the release library path through
`ATLANTIC_LD_LIBRARY_PATH` for the WebKit helper wrappers.

After installation, verify both the engine RPM inventories and SailDroid's
activation seal. Run an ordinary APK through the public Android WebView API
to check HTML loading, JavaScript evaluation, an annotated Java interface,
HTTPS loading, and emitted renderer frames. The provider forwards layout
parameters through `WebView.PrivateAccess.super_setLayoutParams`, so Android
parents can measure a WebView attached with `Activity.setContentView`. Package
that provider change with boot images compiled from the same runtime JAR. The
API28 JNI registration table initializes Android NIO helpers before graphics,
which provides the buffer access methods used by Bitmap pixel transfers.
Exercise heap, direct, and typed buffer copies in the ordinary APK probe. The
API28 CLI bootstrap validates 97 framework registrations and carries its
matching source hash in the CLI module manifest. The probe covers
zero-offset Bitmap buffers. A heap ByteBuffer positioned at 4 currently
triggers an ART array-pointer abort in `Bitmap.copyPixelsToBuffer` on this
API28 runtime.

### r323f Activity queue and page recovery

The r323f runtime uses version `0.321.57-64`. Its repair inputs and device boot
image recipe are recorded under
`share/build/webview-runtime-20261109/recovery`. The build starts from the sealed
r323e payload, overlays `SdActivityHost` and `SdWebViewProvider`, compiles the
42 matching boot image files on the aarch64 device, and uses the established
Sailfish SDK target `SailfishOS-latest-aarch64` for the RPM. The provenance
includes `prepare_package_recovery.py` and the exact input hashes.

Activity start requests retain the caller's package when they enter the queue.
If the caller finishes before dispatch, the accepted launch continues with its
saved referrer and detached result ownership. Pending starts also retain a
process whose last Activity has just finished. Unknown caller tokens are
validated when a new request is accepted.

A WPE page load error reports the failing URL through `WebViewClient` and keeps
the engine available for JavaScript and subsequent navigation. Engine process
failures continue through the existing renderer cleanup path.
`native/webview/qt-helper/RecoveryProbeActivity.java` exercises these paths
through a normal API28 APK, including local file errors, HTTPS, Java interfaces,
proxy Activity finish/start ordering, result delivery, and one-Activity tasks.

The final r323g package uses version `0.321.58-65` and the same runtime JAR and
boot images. It includes the corrected recovery probe, which loads a valid
document after a page error before checking JavaScript and Java interfaces.
Its packaging recipe is `prepare_package_recovery_final.py` in the recovery
provenance directory.

## 2026-11-04 development example

Evidence root:
`build/evidence/apps-performance321-20261104/performance/distribution-v2`.
The input is the r321d process overlay, manifest
`e62135212681e80585ac247294e2d2e407d22794301d691b50d591493fc8ae65`,
containing 2457 baseline files and 5 links. The support capture contains 29 real
phone files from Sailfish OS 5.2.0.16, manifest
`902d29f0b826b8b70b5a84fb81e62beef703bc5facf2fd7bf1a13a173dddc30b`.
VM support libraries were explicitly rejected as substitutes because several
of their bytes differ from the accepted phone versions.

The host's accepted hash is
`c5578dbe3d9b75eea9c8ae8553f4cd7cf113dea2e521aaffe193860dd3c25912`;
the RUNPATH-only version is
`53a38daf18f0c0a8e9840e93717f8adb10fc03dbdff101e423b1d89e876a1cb5`.
The isolated compiler also needs its own captured `libatomic.so.1`, hash
`2896f2608b49113496e6872c77cb591f51f4e646fec01e59f517a971199979fe`.
Its library path intentionally does not borrow the runtime's parent directory.
The final development example uses RPM release **2**; release 1 is retained
only as diagnostic evidence and lacks that private compiler dependency.

Accepted VM checks:

- `runtime-elf-audit.json`: 235 ELF paths, 56 glibc host paths, no unresolved
  library and no external non-OS library when the old ART fallback is omitted.
- `relocation-smoke-v5.json`: ordinary UID 65534 executes SHA-256, StrictMath,
  and Unicode code from `/opt`; `/home`, `/tmp`, `/var/tmp`, and
  `/usr/local/lib` are hidden, with a bounded scratch bind. Runtime library
  mappings show no old ART/build library paths.
- `host-origin-smoke-v2.json`: the relocated host starts in the same namespace
  with inherited scheduling limit 40, zero effective capabilities, and
  `no_new_privs=1`.
- `bootstrap-smoke.json`: the real file-capability bootstrap starts the host
  from a cleared environment, producing the same limits. Its temporary VM
  capability was removed after the check.
- `compiler-atomic-smoke-v2.json`: the isolated compiler produces a real
  quickened ODEX/VDEX from a tiny Java DEX with the old library paths hidden.
  Its loader uses the private captured atomic library.
- `rpm-v3/result.json`: the corrected RPM identity/hash and exact extraction
  verification. The source manifest is `distribution-manifest-v2.json`.
  NEVRA: `saildroid-runtime-api29-r321d-dev-20261104-0.321.4-2.aarch64`;
  size: 358,535,953 bytes; RPM SHA-256:
  `d5c74114b27f01cdad0888162d4141c0ee141ce27e0a77f1ae8d2f791b156626`.
  The 2507 files and 5 links match distribution manifest
  `e5096d84f8250f0b32db63f5b45e74d834d310709ff19f29270634a810bdee5b`.
  Complete RPM requirements are also saved as `rpm-v3/requirements.txt`.

The temporary VM `/opt` test clone was removed after these checks. Early
namespace/permission fixture failures and a compiler ENOSPC run remain in the
notebook; the accepted compiler repeat used shared-disk scratch because the VM
root disk had no space for an ordinary user.

## Boundaries

This is a reviewable development package, not a frozen or phone-accepted release.
Phone installation, dependency resolution, app behavior, and current branch
acceptance must be verified separately by the serial device owner. No AOT cache
is bundled or enabled; the earlier WeChat quicken pilot reduced one loader
measurement but later aborted, so it is not a performance acceptance result.
The serial device owner also reproduced the same JNI abort without that cache;
the abort must not be attributed to AOT without the native caller investigation.

The component retains platform integration dependencies: WebView references
`/opt/wpe-sfos`, `/usr/lib64/wpe-compat`, Qt/WPE subprocesses, and the user's
Wayland/D-Bus/audio environment. The static ELF gate does not certify these
runtime-loaded dependencies, and RPM requirements are not a substitute for that
platform audit. The old `libexec/saildroid-launch` is a legacy fixed-path entry;
the relocated supported startup path is the capability bootstrap/native host.
The native host preserves existing `/home/art` app data and binder conventions.
Existing fallback strings remain in the accepted sources, although the bounded
CLI relocation proof executes successfully with those old private paths absent.

## Explicit setup and rollback

`saildroid-setup.py` is the manual root command for a package containing
this setup payload. It does not install the RPM or open an installer window.
After the normal RPM transaction, use its absolute versioned path:

```sh
python3 /opt/saildroid/releases/<release-id>/bin/saildroid-setup status
python3 /opt/saildroid/releases/<release-id>/bin/saildroid-setup activate <release-id>
python3 /opt/saildroid/releases/<release-id>/bin/saildroid-setup rollback
python3 /opt/saildroid/releases/<release-id>/bin/saildroid-setup recover
```

`recover` handles an interrupted setup transaction; it restores the pointer,
launcher snapshot, and activation history from the root-owned journal. A changed
active pointer outside that transaction is rejected. A normal failure restores
those items immediately. Existing APKs, records, app data, and AOT directories
are not modified or deleted. Rollback to an initially unconfigured system removes
setup-created launcher entries while retaining the app store.

Production prerequisites are Sailfish OS 5.2 or 5.3, aarch64, Python 3.9 or newer, `rpm`,
`getcap`, an existing ordinary `defaultuser`, and its active user-bus and Wayland
session. Account UID/GID/home/groups are read from the actual account database.
The expected versioned RPM must own `runtime.json`, verify cleanly, have no
scriptlets, and have providers for every external RPM dependency. The root and
all payload parents must be root-owned and not group/world writable. The full
activation manifest checks every file/hash/mode/link and the directory inventory;
only the native bootstrap may carry `cap_sys_resource=ep`. Extra payload files,
escaping links, legacy non-native entrypoints, and unrelated launcher collisions
fail closed. `status` is read-only; activation prepares only the compatible
`/home/art` storage and root-owned journal directories that are missing.

An already-provisioned `/home/art/runtime/binder` is preserved when the directory
is root:root 0755 beneath trusted parents, `binder` is a real character device
owned by the selected user with mode 0600, and `provision.json` is a root-owned
regular file with mode 0644. External provisioning is preserved, and its device
is checked for Binder protocol 8. Linked or writable substitutes fail closed,
and this exception does not permit root-owned
application storage. A VM fixture uses a real character node and checks that
activation, upgrade, and rollback preserve inode, rdev, mode, owner, ctime, and
provision bytes. Invalid variants are separately rejected before switching roots.

New setup payloads include `bin/saildroid-binder-setup.py`. Activation uses it to
prepare a private binderfs instance and bind its device at the configured path.
Kernels that create `binder` on mount use that node. Other kernels create it with
`BINDER_CTL_ADD`. The node belongs to `defaultuser` with mode 0600. Only the common
runtime and Binder directories become root-owned 0755. The helper installs and
enables `saildroid-binder.service` before the user session, with an independent
root-owned copy at `/usr/local/sbin/saildroid-binder-setup`. Repeated execution
preserves the device identity. Boot recreates the mount and refreshes device
metadata. This common prerequisite remains available across runtime rollback.

When binderfs is unavailable, the helper accepts a dedicated static
`/dev/anbox-binder` or `/dev/puddlejumper` node. It preserves a previously
registered source and otherwise selects anbox-binder first. Static provisioning
checks the kernel misc-device identity, protocol version, root ownership,
0600 permissions and existing consumers before creating the user-owned runtime
node. Kernels with `binder,vndbinder,hwbinder,puddlejumper,vndpuddlejumper,hwpuddlejumper`
can use puddlejumper for the private runtime Binder context. Binderfs remains
the preferred backend when available.

Close all SailDroid hosts, including its native session manager, before activation.
The helper never kills them. It holds both a root setup lock and the existing
native manager startup lock, scans owned processes, and atomically replaces
`/home/art/api29-root`. A native launch whose old executable was resolved just
before the final switch can still race the last process scan; the existing host
has no shared activation-generation protocol. Do not launch apps during setup.
This limitation is explicit rather than being hidden by stopping system services.

The helper creates one normal manager desktop entry targeting the current native
bootstrap, plus the compatibility `saildroid-open` symlink. Desktop operations run
after dropping to the actual user's UID/GID/groups, not as root. Application
entries are generated by the installed **real `SdAppRegistry.refreshLaunchers`**
through the headless ART CLI with its actual selected-root environment. No custom
replacement app catalog, APK, binder process, or GUI is started.

The CLI enforces application-owned main classes and hidden-API restrictions.
The setup payload therefore adds an application-owned `RefreshLaunchers` entry
and a boot-owned `RegistryBridge.refresh(expectedRoot)` with precisely one public
entry. It can only validate the current app records and refresh that user's
launchers for the current `ANDROID_ROOT`; it provides no arbitrary reflection or
root operation. The original CLI bootstrap DEX and all its hidden-API flags remain
byte-identical. The bridge is appended as `classes2.dex` to the CLI-only
`lib/java-cli-bootstrap.jar`; the application host's bootclasspath, runtime.jar,
ART libraries and application AOT identities do not change.

Rollback between setup-capable RPM releases refreshes through the selected
release's real registry. A pre-helper legacy root lacks that boot bridge, so its
rollback restores the exact pre-activation desktop snapshot without changing the
old immutable root. Applications installed after activation retain their data;
open the restored legacy manager to generate their icons. The old
`libexec/saildroid-launch` remains unsupported: setup requires the native
`libexec/saildroid-app` capability bootstrap and ordinary-user host.

## Adding setup to the final staging root

Run `build-setup-payload-vm.py --bootstrap-jar ACCEPTED/lib/java-cli-bootstrap.jar
--output NEW-DIR`. It produces a small `root/` overlay, source/provenance records,
and verifies preservation of every original bootstrap ZIP entry. The input must
be the accepted original CLI bootstrap, not an already extended setup version.
Apply that overlay to a new final staging root, then run
`seal-setup-manifest-vm.py --root STAGING --release-id ID`. The seal covers the
whole final root except itself; the subsequent RPM inventory includes the seal,
so the installed RPM database verifies its bytes as well. Seal only after all
native fixes and closure additions. These builders refuse Sailfish and do not
accept installed release directories as seal destinations. No final RPM is built
automatically, and no RPM scriptlets are needed.

Tests are `test-setup-vm.py` (isolated temporary filesystem, real unprivileged
user-file subprocesses, explicit platform test doubles) and
`test-setup-registry-vm.py` (actual packaged ART/registry in a no-network mount
namespace). Both refuse Sailfish. Production CLI has no fixture-prefix override.
The registry test materializes the runtime only inside a private tmpfs mount;
Parallels shared files have synthetic per-caller ownership and cannot substitute
for an immutable root-owned release in the ordinary-user trust check.

Setup dependency checks use RPM's installed-package verification, including
version comparisons (`rpm -V --nofiles --noscripts`). A separate isolated RPMDB
fixture proves rejection with a missing provider and a too-old provider, and
acceptance with the required version. A literal `rpm -q --whatprovides 'name >=
version'` lookup is not used: it can falsely reject installed dependencies.
Packages with the setup helper require the actual `/usr/bin/python3` file
provider; the helper also checks Python >= 3.9 and the `rpm`/`getcap` tools.

## 2026-11-05 H snapshot with setup

`performance/distribution-v4/rpm/result.json` records the H snapshot package:

- NEVRA: `saildroid-runtime-api29-r321h-dev-20261105-0.321.8-1.aarch64`.
- Installed root: `/opt/saildroid/releases/api29-r321h-dev-20261105`.
- RPM SHA-256: `17a302b5d490f709497bfe0d45dea0ec3dd771c58952c62c1c9732c1c99aa181`;
  size 358,762,555 bytes.
- Distribution manifest: `80c1c2869325758e21816042439181359b0f00a92512604e6281dcc29808db83`;
  2541 files and 5 links, all extraction-verified.
- Activation seal: `071ba298e2dc8a6cf46874fa4f8fe0632c1e67d1733be3b3fc51a221d75a0457`.

This snapshot includes all 2486 accepted H files before packaging additions,
the verified captured support closure, private compiler, setup helper, and
restricted registry bridge. The host change remains RUNPATH-only and its
accepted baseline hash matches the earlier byte-reproduced host. The runtime
DEX remains `df951374615669f06bcd5a457e067dd6b5185c68bf966131da8b4894a670e00b`.
The experimental stored framework ZIP repacking is **not** included.

Setup transaction tests passed 21 cases; the final H real-ART registry test
passed refresh, corrupt-record rejection, wrong-root rejection, boot-main
rejection, and app reflection rejection. These are VM results. Target install,
activation, app regression, performance, and CTS results belong to the device
owner's subsequent run and are not implied by RPM extraction verification.

## 2026-11-05 I snapshot with binder preservation

`performance/distribution-v5/distribution-summary.json` records the complete I
snapshot and links its independent evidence:

- NEVRA: `saildroid-runtime-api29-r321i-dev-20261105-0.321.9-1.aarch64`.
- Installed root: `/opt/saildroid/releases/api29-r321i-dev-20261105`.
- RPM SHA-256: `6e085ff5d49045bbe2fbd0b5a79c3c969d853fe7249ed80850885cce399cdfea`;
  size 358,791,225 bytes; extracted payload 773,235,063 bytes.
- Distribution manifest: `7a28db244b72a7c3ca90b9e76b7b994b3f046bc20a22800d8cbaa93cefc4b441`;
  2547 files and 5 links, all extraction-verified.
- Runtime JAR: `ec5048600e09cbb8cb8bc96831d6a84291fb8f7872dbdad36302f32f87d047cd`.
- Activation seal: `7d964698d054d09f0f570c13c7c2f4128e5237767703baf821b09236ace9b5f6`.

Relative to H, only the asynchronous IME runtime, six associated provenance files,
binder-preserving setup helper, and activation seal change. All 32 setup
transaction cases and five real I ART registry cases pass. RPM requirements,
capabilities, and no-scriptlet policy match H. This is a VM-verified package;
target acceptance is separate. The five final app caches are held pending the
ongoing native linker fix and final installation-root selection. No experimental
framework ZIP repacking was applied.

## 2026-11-05 J snapshot and final app caches

`performance/distribution-v6/distribution-summary.json` records the J package:

- NEVRA: `saildroid-runtime-api29-r321j-dev-20261105-0.321.10-1.aarch64`.
- Root: `/opt/saildroid/releases/api29-r321j-dev-20261105`.
- RPM SHA-256: `ec8b02cfb9da68595264cbd546fb745e921d84b26939ef521204d2bf070aa716`;
  size 358,791,071 bytes; 2551 files and 5 links verified after extraction.
- Manifest: `4893df570d5f9b094471bc1831f521877458880c680f27231e6fe47f14ad5deb`.
- Seal: `e63f7414a9ae69ebc2a251ef985332ed68d14589aeea552f0cd616fca2ce3ecc`.

J preserves the I Java runtime and setup helper. Its only payload differences
are the generic defined-object linker fix, four associated provenance files, and
the seal. All five real-ART setup cases pass on J. The first RPM extraction hit
the former 180s limit under concurrent compilation/shared-disk I/O; the exact
same RPM passed full verification with a 600s bound. That failure and its partial
extraction are retained. The builder now uses a configurable bounded timeout and
reaps only its own extraction subprocess on failure.

`performance/final-j-opt-cache-verified-v1.json` independently verifies WeChat
and QQ speed caches plus Xiaohongshu, Douyin and Zhihu quicken caches. Compilation
began from the sealed final assembly while RPM packing ran; the final check
compares every boot/shared-library input against the extracted RPM, recomputes
cache keys and file hashes, and parses the emitted OAT context paths/checksums.
Every context uses the final J root. The caches are separate from the RPM, and
both actual ART acceptance and steady-state/startup performance require target
measurements. No historical performance result or old cache is relabelled as J.

## 2026-11-05 L preloaded boot image snapshot

`performance/distribution-v9/distribution-summary.json` records the L package
and the five independently verified caches:

- NEVRA: `saildroid-runtime-api29-r321l-dev-20261105-0.321.12-1.aarch64`.
- Root: `/opt/saildroid/releases/api29-r321l-dev-20261105`.
- RPM SHA-256: `0e372a547afb60008b79cc797dd887f12ca0584edc281dd6cb52679d146ef67d`;
  size 420,456,289 bytes; all 2586 files and 5 links verified after extraction.
- Manifest: `4f29b0972b63727227565c9ee5411e01f39f2d9b0e75ede84a313f2f23b670f8`.
- Seal: `7df56c981fc65400bb381ca9c992d3d6f9b0a1253978603f206e894bab353130`.

L preserves the J2 setup helper, captured support closure, private compiler,
original 15 boot DEX JARs, native libraries, and hidden-API rules. Its full boot
image covers those 15 JARs and uses the existing packaged AOSP preloaded-class
list. Compiler initialization retains ART transaction rollback and the
`NoPreloadHolder` exclusion. All 45 active generated image files are sealed;
six older inactive image files remain preserved. The image-class experiment
and its exact inputs are recorded under `performance/full-boot-preloaded-v1`.
The additional class metadata is not a claim of measured physical-memory savings.

The helper's exact bytes retain 39 passing transaction tests. Five fresh
registry tests use the extracted L ART runtime as an ordinary user in a private
namespace. They cover valid refresh, malformed-record preservation, wrong-root
rejection, boot-owned-main rejection, and hidden-registry reflection rejection.
Package installation does not activate the runtime or change services.

`performance/final-l-opt-cache-verified-v1.json` verifies WeChat and QQ speed
caches and Xiaohongshu, Douyin, and Zhihu quicken caches. A genuine new compiler
reference uses L's full image closure; the verifier checks every active image,
boot/shared-library input, cache key, output hash, and emitted final-path OAT
context against the extracted RPM. Caches remain separate from the package.
The device deployment script's optional `--adopt-source` is not bundled in the
RPM and does not change the sealed runtime.

Target install, activation, real-app interactions, cache acceptance, memory,
performance, and official CTS gates are recorded separately by the device test
owner. Neither these VM checks nor earlier J performance results certify those
L device gates. Earlier K artifacts and partial cache outputs are preserved;
its paused cache driver was terminated without starting the remaining jobs.

## 2026-11-09 API28 native display repair

The r323h release is `saildroid-runtime-api28-r323h-dev-20261109-0.321.59-66.aarch64`.
Its native display library is built with
`native/window/build-native-display-vm.py`, using the extracted r323g payload
and its recorded cross-build inputs. The builder verifies a byte-identical
baseline and records the candidate's source hashes, commands, dependencies,
and exports. The native display README contains the build and regression
commands.

The workspace packaging record is
`artifacts/wechat-qr-login-20261109/prepare_package.py`. It clones the verified
r323g payload, installs the window library and its provenance, updates the
integration metadata, and runs `prepare-core-linker.py` with the final release
ID. `seal-setup-manifest-vm.py` generates the activation inventory before the
Sailfish WSL SDK wrapper builds the aarch64 RPM. `verify_package.py` extracts
the RPM and compares all payload bytes, modes, directories, and symlinks.

The installed payload includes the recipe, native source, and build record
under `share/build/native-display-events-20261109`. The RPM owns the release
directory and carries the setup helper's checked installation scriptlets.
