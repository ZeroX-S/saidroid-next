# Delayed duplicate Activity.finish regression

This ordinary two-Activity application opens a child, finishes it, and invokes
finish again from a delayed callback after onDestroy. The main Activity must
resume twice and remain alive; the child must be destroyed exactly once.

Acceptance requires the actual first finish/destruction/resume markers, the
already-absent token acceptance marker, the second callback returning, and the
final MainActivity marker. Process liveness alone is insufficient.

The retained 2026-11-03 device matrix is under
`build/evidence/qq-media-player312-20261103-v1/finish-fixture/`: r312g on
SDK 29 reproduces the Unknown Activity token exit 10, while r312i on target
SDK 29 and 34 passes. Each fixture has a unique private app record, creates no
desktop entry, and is removed after the owned process exits and the panel is off.
