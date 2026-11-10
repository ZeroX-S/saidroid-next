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
