# API28 port integration

The integration keeps complete API28 and API29 releases separate. The product
builder selects the framework JAR, D8 minimum API and native display-event ABI
with `--api 28` or `--api 29`. It records the exact selected source hashes.
`scripts/device/api29/` retains the accepted API29 window, task, display,
application lifecycle, media and host-service implementations. Other device
sources provide the API28 port and shared adapters. A successful product build
is a Java/native helper build, not a complete bootable runtime certification.

The API29 source variants were recovered by reproducing all emitted classes
for each retained family against the accepted r321o class files. New changes
include separate pointer hit testing for non-focusable popups, reentrant input
finish retirement, root-owned permission policy, view diagnostics, WebView
geometry/history and safe-mode queries. Keep API-specific window/session
interfaces separate: Android 9 uses Surface and Android 10 uses SurfaceControl
and InsetsState. Display-event native layouts must match their framework.

## Inherited API29 native Host

The first phone candidate retained the accepted r321o native Host to preserve
its ART/JNI closure. That old binary still used package-name validation for
component class names. WeChat's `ProcessService$SupportProcessService` was
therefore rejected before the declared service could start, even though the
current product source already accepted Java nested-class names.

For this inherited payload, use the bounded VM builder before sealing a new
staging release:

```sh
python3 scripts/packaging/build-inherited-component-host-vm.py \
  --runtime-root /path/to/accepted/staging-root \
  --output /path/to/new/host-build
```

The builder verifies the recorded source/header closure and reproduces the
accepted Host byte for byte. It applies the same `valid_component()` rule to
the inherited manager and its four child-process entry points, then runs the
component-name contract against those exact legacy sources. Package-name and
caller/family validation remain unchanged. All existing dynamic exports and
C/JNI exports are retained; the compiler additionally emits one existing
internal weak C++ helper. Dynamic dependencies and RUNPATH are unchanged.
The supplied root is never modified. Install the resulting Host only into a
new sealed staging release, preserving the old installed release for rollback.

## Permissions

The old app-writable `saildroid-runtime-permissions.properties` is no longer an
authorization source. Policy lives in `/var/lib/saildroid/permissions` and every
ancestor and record must be root-owned and not group/world writable. Records
bind package identity and APK SHA-256. Symlinks, mismatched APKs, writable
records and stale grants are rejected. Platform permission declarations take
precedence over app declarations.

The hosted permission dialog reports denial or an existing host grant. It
cannot create a grant. The current UI and app run under the same Linux UID;
there is no independently trusted interactive grant broker yet. The root
operator can use the packaged helper for an explicitly selected installed APK:

```sh
/opt/saildroid/releases/<release>/bin/saildroid-permissions \
  --package org.example.app --apk /absolute/installed/base.apk \
  --grant android.permission.CAMERA
# Revoke with --deny; omit both flags to inspect the current policy.
```

This closes the properties-file self-grant path. It does not establish a full
Android security sandbox against arbitrary native code sharing the host UID.
No camera, microphone or storage grants should be migrated automatically from
app-owned records. Missing backend support still denies access even with policy.

## Web engine prerequisite

The helper requires the actual Atlantic WPE Qt plugin, WebKit subprocesses and
compatible native libraries. Missing `org.wpewebkit.qtwpe` is a renderer failure;
do not report a page load or synthesize success callbacks. The current engine
input is Atlantic build 768.1, publisher source commit
`b36d176b1374aab8c6b4bde582d10bf6ff50819e`. Verify repository metadata, package
hashes and signatures using the publisher's key before installation.

Keep compatibility libraries in the release's private `lib/webview` directory.
The upstream compatibility RPM also installs memory-management units; extracting
its library payload does not authorize installing those units. Do not preload
signal-skipping libraries as a substitute for fixing renderer faults.

## Acceptance boundaries

Run the transaction tests under umask 022 and 077, permission tests on both
frameworks, the pointer-selection cases, and input finish/package/text-service
probes against the actual selected product classes. Source/build checks do not
prove an API28 phone release. API28 activation additionally requires matching
core/framework resources, native runtime/JNI and boot images; the selector must
reject mismatched metadata rather than relabel an API29 root.

For device updates retain the previous release, install an isolated candidate,
perform an ordinary reboot, require a changed boot ID and fresh Lipstick/input
health, then test actual QQ quote draft state and rendered WebView load/JS/input.
Keep all chat screenshots and account-related logs outside public PR artifacts.

The Binder activation helper preserves an existing root-owned `0750` ART parent
with the phone user's group. It also migrates the earlier dedicated `/dev/binder1`
receipt only after matching its exact legacy fields, kernel registration,
source/target ownership and device numbers, absence of foreign consumers, and
Binder protocol 8. Without an existing receipt it selects only the supported
dedicated device names. Neither migration widens the ART parent's permissions.

## Pixel 3a verification, 2026-11-10

The isolated API29 candidate is
`saildroid-runtime-api29-r324a-dev-20261110-0.324.1-4.aarch64`, installed under
`/opt/saildroid/releases/api29-r324a-dev-20261110`. Its RPM SHA-256 is
`3c1dd229de8acff53b5d4c14735b0dbd1718aeb7dcdf8a2f5e95d6bd7ddd5bbf`.
The new `select-api 29 --release ... --apply` path activated it while preserving
the previous releases. Package and manifest verification passed. An ordinary
reboot produced a different boot ID and a fresh Lipstick process; the user
confirmed that desktop touch and swipes recovered.

The API28 and API29 product builds passed. The VM regression run passed 19
groups, including 85 activation cases under each of umask 022 and 077, both
API window/input/permission variants, native identity/audio, Binder and WebView
geometry. Eight additional API28 helper groups passed. The final Binder
migration fixtures passed 23 cases under each umask. Five registry checks ran
through the actual packaged API29 ART CLI, including expected rejection cases.

On the rebooted phone, a physical QQ message long press and Quote tap targeted
the non-focusable `PopupWindow`. The input then displayed the quoted message
preview and corresponding @ text, with an IME commit marker. The quote and
draft were cancelled, the editor was checked empty, and the owned QQ process
exited. Menu dismissal alone was not counted as a successful quote.

The controlled WebView verification page rendered actual before/after pixels
and passed ten checks: initial load, cookies, annotated-only Java interfaces,
physical input, Java callback, JavaScript prompt, custom navigation callback,
redirect, HTTP headers and HTTP cookies. Normal close returned exit status 0;
all four owned app/helper process identities disappeared. Earlier harness
attempts with incomplete process reaping were retained as failed attempts.

The actual WeChat verification page also loaded and accepted input; the user
confirmed that it could be used. A later login attempt, after the user entered
the SMS code, displayed `uuid_failed`. The native log contains completed page
loads and input events without a renderer failure. On the `r324b` retry, six
WebViews completed loading and three performed the `__wx` handshake and called
`mmsf0001` three times each. There were no native service-identity or runtime
startup failures. The user still reported `uuid_failed`, with one attempt
reaching QR verification. These observations establish that the bridge was
called; they do not establish that valid security information reached the page.
WeChat login is not accepted as passing. Verification tickets and account
details remain private; no successful security result is synthesized.

An additional regression was reproduced on both API frameworks: injecting a
native callback with `loadUrl("javascript:...")` replaced the provider's document
URL with the script and cleared its title. The shared provider now dispatches
the script before changing navigation state. The focused
`test-webview-javascript-state-vm.py` fixture fails against the old source and
passes against the fix on API28 and API29. It verifies the actual provider's
URL/title/load state and exact transport command while starting no renderer.
This fixes the state corruption; its connection to WeChat's login failure
remains unproven.

These checks prove the renderer prerequisite and controlled verification flow.
The phone tests used API29. A complete API28 phone runtime, cross-API phone
switching and a trusted interactive permission broker remain separate work.
Full CTS was not rerun for this integration. Every completed visible test
restored actual backlight brightness to 0.

The follow-up `r324b` candidate carries that native component-name fix in a
separate release, `saildroid-runtime-api29-r324b-dev-20261110-0.324.2-1.aarch64`.
Its RPM SHA-256 is
`d1e6f05d5c963f57935b80a24e9470dd48b8abd19bbcf84a6ec09f8398290d18`.
Installation, cold selection, manifest/package checks and another ordinary
reboot passed; the user confirmed recovered desktop touch and swipes. Fresh
WeChat startup presented its first app frame without an early-window failure.
Its account-verification retry remains under observation.

During the preceding retry, Lipstick stopped servicing display requests. MCE
reported a compositor timeout; sampling both the main and render threads found
them looping in the Adreno driver's command-submission descriptor traversal.
The temporary WebView diagnostic had not executed in that failed app run.
The trigger remains unproven. Closing owned apps did not recover the display;
an ordinary reboot restored it. No compositor or networking service was
replaced or manually stopped for this recovery.

## WeChat QR verification follow-up, 2026-11-10

The QR-verification crash was isolated to the process-local AppOps proxy, not
the WebView renderer or QR page. WeChat calls
`IAppOpsService.checkOperation` after login; the old `SdCameraAppOps` proxy
treated that method as unsupported and raised the runtime diagnostic exception.
The fix is commit `1f2a3a6` (`Handle AppOps checks used after WeChat login`). It
implements the required `checkOperation`, `noteOperation`, `checkPackage`,
`permissionToOpCode`, and `noteProxyOperation` paths while retaining the
owner/package and permission policy. The isolated contract test
`scripts/api29/tests/test-appops-contract-vm.py` covers allowed playback,
denied camera/foreign-owner operations, package checks, and the note-operation
path; its expected result is
`APPOPS_CONTRACT=passed|checkOperation|noteOperation|checkPackage|foreign-denial`.

The AppOps change is now staged for the r324d candidate. API28/API29 product
builds and the boot-image preparation completed, but the first r324d RPM
packaging attempt timed out during the long packaging step and is being
retried. No r324d package has been installed on the phone and no post-fix QR
login result is claimed yet. The r324c release remains the installed,
reboot-verified reference until packaging and a user-controlled WeChat retry
complete. `uuid_failed` and account verification remain unresolved acceptance
failures until that retry produces a real security result.
