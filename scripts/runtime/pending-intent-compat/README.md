# Application-owned PendingIntent candidate

This opt-in r301 overlay adds actual IIntentSender Binder tokens owned by the
current application process. Equivalent type, request code, owner, user,
retained flags, resolved type and Intent.filterEquals fields reuse a token.
Extras do not participate in identity. UPDATE_CURRENT replaces stored extras;
CANCEL_CURRENT cancels the old token; NO_CREATE avoids allocation; ONE_SHOT
consumes a token; IMMUTABLE ignores sender fill-in fields. Parceling preserves
the Binder identity. Cancellation and creator/type queries use the registry.
Broadcast sends reach the existing registered/manifest receiver backends;
activity and service sends use their existing application backends.

Tokens are process-lifetime and application-owned. This does not implement a
persistent system PendingIntent broker or host notification actions. Foreign
applications/users, multi-activity stacks, activity-result tokens, nonempty
launch options, whitelist tokens and ordered broadcast completion callbacks
remain explicit unsupported operations. The existing notification policy
reports delivery disabled; enqueue now validates ownership and drops the post
under that same policy with an explicit delivery_blocked marker. It does not
claim to post a host notification or to trigger its PendingIntent.

The normal signed SDK29/34 fixture exercises public APIs: identity, no-create,
update, cancellation, one-shot, immutable/mutable fill-in, Parcel round trip,
HandlerThread creation/sending, real BroadcastReceiver delivery, creator
identity, foreign-owner rejection, and disabled NotificationManager delivery.
It runs first against r300 as a negative control. Phone fixture results belong
under build/evidence/qq-pending-intent301-20261102-v1; acceptance is pending.

snapshot.json pins the exact source, patches, fixture and VM recipes. The
recipes retain original audit paths; use fresh evidence/output directories
for a future build. They compile the pinned baseline byte-for-byte first,
change only the application runtime overlay, and preserve existing hidden API
flags, core/framework/boot/ART and r300 native graphics bytes. This candidate
has not been promoted. The daily version remains r293 until real QQ
conversation regression passes.
