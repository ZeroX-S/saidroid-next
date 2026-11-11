# Declared-provider bootstrap for receiver processes

The deployed API28 JAR contains manifest receiver dispatch, but its HostApi and
native host do not expose `startReceiverProcess`. Calling that absent method
raises `NoSuchMethodError` on a worker and QQ's uncaught handler closes the app.
The process Binder endpoint also lacks transaction 9, which the existing
manifest receiver sender uses. Both gaps must be addressed together.

`SdReceiverProcess.start` validates the receiver and selects an enabled provider
declared in the same APK and exact receiver process. It uses the existing native
provider launch API with the actual provider identity, not the receiver name.
Normal application binding initializes that process's providers and publishes
its service endpoint without opening an Activity or starting an unrelated
Service. QQ declares FileProvider in `:tool`, so this starts the real process
needed by WebProcessReceiver. No provider query or file read is performed.

This is a constrained compatibility path, not a new native receiver-launch API:
when a receiver process has no such provider, it fails explicitly. It does not
claim general cold receiver process support or change native security checks.

`patch.py` narrowly updates the manifest receiver worker to use this bootstrap
and the shared live-Binder, 120-second startup wait, restoring interrupt status.
It adds endpoint transaction 9 behind the original UID and interface-token
checks; transaction 8 retains its original value and Activity behavior. The new
dispatch helper checks caller UID/package and hands all payload/permission/user
fields to existing real manifest receiver validation and ActivityThread
scheduling. Success is written only after that call succeeds.

The Java helper source is the reference for the matching smali implementation.
Do not replace the deployed runtime with older whole-class sources. Preserve
all old member flags/restrictions and rebuild the complete boot-image closure
when applying this overlay.

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-receiver-process.py
```

Tests compile the Java reference against controlled metadata/Parcel/receiver
stubs and check the smali patch boundaries. They do not by themselves prove
QQ's receiver initialization or preview-kernel download works on the phone.
