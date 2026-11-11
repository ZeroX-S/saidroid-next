# Document picker rendering

The API28 r323k built-in `SdDocumentPicker` synthesizes its own `ActivityInfo`.
It omitted `FLAG_HARDWARE_ACCELERATED`, so Android launched the picker with
software drawing even when the caller used the hardware renderer. The installed
host supplies an Android/HWUI Surface; repeated software `Surface.nativeLockCanvas`
calls failed with `IllegalArgumentException`. The picker was running and its
directory worker was not blocked, but no picker content reached the screen.

`source/SdDocumentPicker.java` preserves the deployed picker implementation and
sets hardware acceleration on its own Activity metadata. It does not change the
caller application's flags, file access, MIME filtering, URI grants or selection
results. It does not disable ART or hidden API enforcement.

The source originates from the active component's
`share/build/document-picker-20261110/source/scripts/device/SdDocumentPicker.java`.
This source overlay targets that API28 implementation; it is not a new picker for
the repository's older API29 base.
The original source SHA256 is
`0b2e82d17450707ea71b19f9c1b7302736d53de09c562f505dec0912432bd966`;
the only source change is the hardware-acceleration metadata line.

Run the metadata regression with:

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-document-picker-render.py
```

The regression compiles the actual `activityInfo()` method against minimal
Android metadata stubs, verifies hardware rendering with or without caller
hardware flags, and verifies caller flags and component identity are unchanged.
It does not stand in for visible device rendering or file-transfer acceptance.

Deploying the change requires rebuilding the complete boot-image closure against
the updated runtime JAR, preserving all other runtime methods and hidden API
metadata, closing image users through the native host, backing up old images,
and installing the JAR, images and manifests together. Verify the actual picker
is visible and usable before declaring this rendering issue fixed. Selecting or
transmitting a private file remains a user action.

The November 11, 2026 device hotfix is recorded under
`build/qq-picker-20261111-v1/`. The DEX overlay changes only `activityInfo()` in
`SdDocumentPicker`, preserves all 2,758 existing member flags and the login
startup/remote-process fixes, and passes the installed ART DEX verifier.
All 42 boot-image files are rebuilt together. `boot-image/install-result.json`
records the deployment and rollback backup; `loaded-image-validation.json`
checks the new QQ, Binder and child processes actually map the new runtime image.
`picker-observation.json` records picker startup and software-lock failures;
log-only `drawn` markers must be corroborated with visible picker content.

The user confirmed successful file sending on November 11, 2026, and the device
log records a single selected file and a real `RESULT_OK` delivered to QQ.
`boot-image/file-send-acceptance.json` records that acceptance. The separate QQ
"Photos" button uses its own album/return-Intent flow and is not covered by this
document-picker rendering fix.
