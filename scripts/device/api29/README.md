# Android 10 source variants

These sources preserve the service/window and media interfaces of the accepted
API29 r321o release. `scripts/api29/build-product.py --api 29` selects a variant
by Java filename before adding common sources; `--api 28` uses the main device
source set. The build manifest records every selected file's SHA-256.

The retained source families were verified by compiling each candidate source
against the accepted API29 classes and checking all emitted class files for
byte identity. The integration then applies explicit changes to popup pointer
dispatch, input finish retirement, permission settings callbacks and safe-mode
queries. Shared permission policy, WebView geometry/history and diagnostics use
the main source set. See `docs/PR3-INTEGRATION.md` for the acceptance boundary.

Do not copy an API28 IWindowSession implementation over this variant solely
because javac can compile its reflective proxy. SurfaceControl/InsetsState,
activity tasks and display-event callbacks have different runtime ABIs.
