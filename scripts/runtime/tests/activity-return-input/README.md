# Input after child Activity finish

Build this two-Activity application separately from `activity-finish` (the
fixture package and class names are intentionally the same). It preserves the
delayed duplicate-finish scenario and gives the resumed parent a real Button.

Wait for the child destruction, second finish acceptance and parent resume
markers, then tap the parent through physical uinput. Require
`SD_RETURN_TOUCH=clicked|resumes=2|destroyed=true`, a changed screenshot and the
same main PID/start time. An input acknowledgement alone is not acceptance.

The retained SDK 29/34 matrix, build commands and bounded phone transaction are
under `build/evidence/qq-media-player312-20261103-v1/return-input-fixture/`.
Fixtures have no desktop entry and are removed after owned-process and display
cleanup. This checks generic lifecycle input; it does not claim that QQ's
media-history navigation works.
