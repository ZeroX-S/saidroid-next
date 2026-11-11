# Explicit broadcast dispatch in the deployed API28 runtime

The r323k `broadcastIntent(Object[])` implementation passes explicit broadcasts
to `deliverBroadcast()`, which supports registered receivers only and throws
`Manifest receivers unavailable` for a component-targeted Intent. The runtime
already contains `SdManifestReceivers`, with declaration/enabled-state,
package, user, permission and receiver-process checks. Its PendingIntent route
is connected, but the normal Context sendBroadcast route is not.

`patch.py` reconnects the normal explicit-broadcast route to that existing
implementation before local/remote registered-receiver delivery. It preserves
the result code, result data, Bundle, required permissions and user. Unsupported
ordered/sticky/app-op/options broadcasts still fail before routing. Implicit
broadcasts retain their existing local and remote paths, including the accepted
foreign-package handling. This does not implement arbitrary cross-application
or ordered broadcasts.

The Java reference in
`../foreign-broadcast-compat/source/SdActivityManagerService.java` already has
the intended explicit branch. Do not overwrite the deployed class using the
older `scripts/device/SdActivityManagerService.java`: that source does not
contain the deployed manifest-receiver machinery or other accepted overlays.

Apply to a disassembly of the accepted runtime, assemble it, and preserve all
member access and hidden API restrictions. The patch rejects unfamiliar
register layouts and changes only `broadcastIntent`. Rebuild and install all
matching boot images and their manifest with the JAR; a JAR-only replacement
does not update running boot-image code.

Regression checks:

```sh
JAVA_HOME=/path/to/jdk python3 scripts/api29/tests/test-explicit-broadcast-dispatch.py
```

The tests check the narrow smali transformation and compile the actual Java
reference method against controlled routing stubs. Device verification must
also observe the original file-browser Activity completing launch; reference
tests alone do not prove received-file preview or remote receiver startup.
