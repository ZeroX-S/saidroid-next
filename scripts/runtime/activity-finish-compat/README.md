# API29 Activity finish compatibility

The source overlay changes only finishActivity's already-absent token handling.
Android 10 ActivityTaskManagerService returns true when no ActivityRecord remains;
SailDroid previously threw from a strict lookup, allowing an app's delayed second
finish to terminate its process. Other strict token lookups remain unchanged.
Intent file descriptors are still rejected before token lookup, as upstream does.
The original asynchronous lifecycle ordering and result delivery remain intact.

`sources.json` pins the baseline source and upstream reference. The media runtime
composer first recompiles that baseline and verifies every generated class against
the accepted base, then changes only allowed overlay class families. The companion
SdViewDump change adds bounds/alpha/input properties to opt-in diagnostics; it
contains no application dispatch or click simulation.

Use `scripts/runtime/tests/activity-finish` for the focused delayed-close regression.
