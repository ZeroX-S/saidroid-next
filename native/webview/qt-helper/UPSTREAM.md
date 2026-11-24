# Qt/WPE WebView host

This uses the installed Atlantic WPE Qt plugin in a separate glibc process. ART
loads neither Qt nor WebKit. `QQuickRenderControl` renders a hidden scene into an
FBO; its pixels travel over bounded, length-prefixed IPC and are drawn by the
Android `WebViewProvider.ViewDelegate`. No extra visible window is created.

Reference source: https://github.com/SpecSierra/atlantic-engine
Inspected revision: `b36d176b1374aab8c6b4bde582d10bf6ff50819e`.
Important files: `qt5-plugin/WPEQtView.cpp`, `WPEQtViewBackend.cpp`,
`WPEQmlExtensionPlugin.cpp`, and `deploy/runtime-common.sh`.
The upstream Qt plugin files retain their Igalia/Zodiac LGPL-2.0-or-later
notices; the overall Atlantic repository includes MPL-2.0 material. The BSD-licensed libwpe input ABI header is copied verbatim from the installed
libwpe 1.17.0 development headers under `include/wpe-input.h`; its full notice
is retained and packaged. No Qt plugin or WebKit implementation source is copied. The installed plugin/engine are external
dependencies, currently tested with `atlantic-browser-1.6.0-748.1.aio.aarch64`.

The r323e deployment uses the modular aarch64 engine packages from build 768.1,
with WPE WebKit 2.54.2 and the same inspected Atlantic source revision above.
The runtime RPM pins those package identities and carries the required
compatibility library closure, source records, and notices. The engine helper
executables use `/opt/wpe-sfos`; the compatibility library directory belongs
to the SailDroid release. See `scripts/packaging/README.md` for the package list
and installation checks.

The exported `WPEQtView::webView() const` accessor is used only to obtain an opaque
WebKit object for public WebKit settings APIs. No private C++ object layout is
recreated. If this accessor or the public settings symbols are unavailable the
host refuses a page load. The plugin is loaded through its ordinary QML API.

## Build and first independent probe

Inside the MeeGo Build VM:

```sh
bash native/webview/qt-helper/build-probe-vm.sh
bash native/webview/qt-helper/run-probe-vm.sh <unique-label>
bash native/webview/qt-helper/build-host-vm.sh
```

The independent probe performs no screen wake and uses only a private phone
user directory. It loads HTML, runs JavaScript, captures FBO pixels, scrolls,
and exits. Its `frameSwapped` notification is explicit: RenderControl does not
swap a visible window, but the WPE backend still needs the image release/frame
completion handshake. The host renders on demand, with one unacknowledged pixel
frame allowed. It does not use the proof probe's fixed render timer.

## Current boundaries

This is an initial Android provider integration, not complete Android WebView
compatibility. Downloads, Java interfaces, request interception, form IME,
Android cookie synchronization, authentication dialogs, and full settings
mapping still need explicit implementations and tests. A WebKit page-finished
callback is never fabricated by the provider. No account login is automated.

Android display density is passed to the real WebKit device scale API. Touch
input uses libwpe directly in physical pixels, avoiding a measured duplicate
DPR division in the Qt input adapter. Android performs View hit testing first.

The current validated Android scene also checks DPR=2.625 and DOM touch
coordinates, not just motion or a screenshot. See `run-android-probe-vm.sh`.
`run-qq-vm.sh` additionally rejects the historical white loading frame via an
independent image gate. The crash, idle and hidden-animation probes use their
own unique evidence directories and always leave the display off.

## Later integration update (r86)

The earlier boundary list above describes the first r84 integration. r86 adds
annotated primitive/string Java interfaces with synchronous returns on a bounded
worker, Android cookie mirroring and real WebKit synchronization, navigation
policy callbacks, prompt/alert/confirm callbacks, custom schemes, request headers,
redirects and URL-encoded POST. Popup navigation has an explicit same-view fallback.
The C boundary in `webkit-boundary.h` uses public opaque WebKit/GLib/libsoup APIs;
it does not recreate WebKit C++ layouts. Full IME, interception, download/auth/
permission handling, full cookie policies and multi-WebView popup management remain
outside the demonstrated scope. See `docs/ANDROID-COMPATIBILITY-2026-10-29.md` for
exact tests and limits. The r86-compat artifact retains its build-time license
snapshot; this source update governs subsequent builds.
