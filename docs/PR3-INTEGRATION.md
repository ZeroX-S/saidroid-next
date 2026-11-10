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

This proves the renderer prerequisite and controlled verification flow. The
actual WeChat account verification page still needs its own observation;
starting WeChat at its welcome page does not satisfy that acceptance check.
The phone tests used API29. A complete API28 phone runtime, cross-API phone
switching and a trusted interactive permission broker remain separate work.
Full CTS was not rerun for this integration. Every completed visible test
restored actual backlight brightness to 0.
