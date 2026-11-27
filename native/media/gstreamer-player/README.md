# Process-private MediaPlayer

This module replaces the 49 Android 10 `MediaPlayer` JNI entry points as one
unit. It does not start or impersonate Android's `media.player` service. Player
contexts are registry IDs owned by this library, never pointers consumed by the
old Android JNI implementation.

`playbin` decodes real media. An RGBA appsink writes into the actual Android
`ANativeWindow` supplied by `Surface`/`TextureView`; audio uses a real PulseAudio
sink. Preparation, first-frame, position, pause, seek completion and EOS events
come from GStreamer. `SdMediaPlayerAudio` records PlayerBase lifecycle within the
application process; it does not implement global audio focus or policy.

HTTP/HTTPS data is read through the application's Android URLConnection/TLS
stack, retaining request headers, cleartext policy and certificate trust.
Byte-range reads require a matching Content-Range. IP endpoints with an explicit
Host header use that host for certificate identity. Network preparation runs on
the worker rather than blocking the application's UI thread.

Build the native library with `build-host-vm.py` and compose Java with
`scripts/runtime/build-media-player-runtime-vm.py` inside MeeGo Build. The Java
builder verifies its source baseline by reproducing the original class bytes;
it copies into a new output directory and never edits frozen runtime inputs.
Apply the existing hidden-API encoder before packaging. Preserve the original
core/framework jars, boot images, API flags and component rollback release.

This is an initial media implementation. Hardware/zero-copy video decoding,
DRM, track selection, playback-speed changes, device routing and auxiliary
effects are unsupported. Unequal stereo volume currently uses the average
volume. Unsupported JNI methods throw or report an unsupported status, rather
than falling through to the incompatible original native context.

Evidence for this work is under
`build/evidence/qq-media-player312-20261103-v1/`. Failed candidates and probes are
retained. A fixture playback pass is separate from a real QQ acceptance pass;
require video-frame/PTS changes, visible output, physical playback controls,
same-process continuity, and safe cleanup before claiming QQ playback works.
