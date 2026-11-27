# Service process defaults and unowned audio focus release

The API29 parser can leave a service process name unset when the manifest does
not declare `android:process`. The component returned that empty name to its
service router, allowing a default service to be created in the caller's
secondary process. Normalize both `getServiceInfo` and `GET_SERVICES` inventory
to the application's declared default process before routing. Keep explicit
secondary process names unchanged.

The read-only audio backend cannot acquire Android audio focus. Abandoning an
unowned client now acknowledges removal with the Android success status,
matching Android 10's absent-owner abandon contract. It validates the calling
package and leaves host audio focus unchanged. Focus acquisition remains
explicitly unsupported.

The r305 build reproduces the r301 class baseline, changes only SdAudio and
SdApkPackage classfiles, and preserves every existing hidden API flag. Core,
framework, ART, boot images, and native libraries remain byte-identical to r304.
The source/patches here record the selected change; the VM recipes replay the
isolated evidence build under build/evidence/qq-service-lifecycle305-20261103-v1.
They require the recorded predecessor workspaces, the private existing Java
compiler/signing environment, and fresh output directories.

Use build-fixtures-v2-vm.py and phone-fixtures-v2-vm.py for the corrected signed
SDK29/34 tests. Their worker process checks public service metadata, performs
34 focus abandons, starts an app-default service, and verifies the callback PID
and Android process name belong to the primary process. Both positive runs
passed 40 checks. The r304 negative control rejects the unset default process.
No audio capture/playback, launcher entries or system service changes occur.

Full QQ functional acceptance is recorded separately. These fixture passes
alone do not establish an end-to-end application pass or a full CTS result.
