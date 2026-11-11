# Touch targets are not keyboard-focus targets

The deployed WindowSession sends the first touch of every gesture to `top()`,
which intentionally excludes `FLAG_NOT_FOCUSABLE` windows. That rule is correct
for keyboard focus, but it makes a visible, touchable, non-focusable PopupWindow
unclickable: its tap is delivered to the underlying Activity instead.

The source reference and narrow smali overlay select touch targets separately,
in existing visual layer order. Invisible windows, windows without an input
sender, and `FLAG_NOT_TOUCHABLE` windows are skipped. A non-focusable popup can
receive touches inside its frame; outside touches pass through. Focusable modal
windows retain outside-touch delivery. Keyboard focus, gesture capture, pointer
coordinates and subsequent multi-touch delivery are unchanged.

This patch does not claim complete Android input routing: custom inset regions,
`ACTION_OUTSIDE` watchers and split-touch routing are not newly implemented.
It does not alter QQ, select a recipient, send files, or claim backend forwarding
succeeded. The safe diagnostic marker records only that a non-focusable window
was selected, never file contents or recipient identities.

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-popup-touch-target.py
```

Preserve all existing member access and hidden-API flags when applying this
overlay. Deploy the runtime JAR and its complete matching boot-image closure
together; do not replace the newer deployed class with the older source file.
