# Window/IME compatibility source overlay

`source/scripts/device/SdWindowSession.java` is the owned source for the r311
window/IME changes. It is based on the exact accepted presentation source,
not the older copy in `scripts/device`. `sources.json` and `window.patch` record
the baseline and change.

IME resize delivers updated window geometry and insets to the real Android
view root when Maliit opens or closes. System gesture exclusion requests are
accepted as metadata without claiming that a Sailfish host exclusion region was
installed. This avoids the QQ gallery's unsupported binder-method failure.

Compose this overlay with the media builder's `--include-window-ime` only when
the supplied baseline predates these fixes. A baseline that already contains
them must remain byte-identical outside the intentionally replaced classes.

The SDK 29/34 two-cycle Maliit fixtures and real QQ editor evidence live under
`build/evidence/qq-video-ime311-20261103-v1/`. Keep physical input and visible
editor-above-keyboard checks separate from geometry-only assertions.
