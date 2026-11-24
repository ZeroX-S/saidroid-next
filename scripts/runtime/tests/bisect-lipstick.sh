#!/bin/bash
# A/B bisect: does SailDroid's traffic crash Lipstick by taking screenshots (A)
# or by creating/destroying a uinput device per injection (B)?
#
#   A  screenshots only  : saveScreenshot every 1.6 s for 60 s, no injection
#   B  injection only    : short tap every 1.6 s for 60 s, no screenshot
#
# Verdict per mode:
#   LIPSTICK_CRASHED   pid changed / gone / restart counter increased
#   SURVIVED           same pid + same start_ticks for the whole window
#
# This script NEVER takes the device lock and never releases it: it refuses to
# run unless the lock is currently held by this line (the token system in
# docs/ACCEPTANCE.md). It also never writes outside /home/art + the screenshot
# directory used by sd.sh.
#
# usage: bisect-lipstick.sh A|B [seconds] [label]
set -u

MODE=${1:?mode A (screenshots) or B (injection)}
SECS=${2:-60}
LABEL=${3:-bisect-$(date +%H%M%S)}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SHOT_DIR=/home/defaultuser/Downloads/SailDroid-Screenshots
TAP_X=540
TAP_Y=1900

export SSHPASS=${SSHPASS:?Set SSHPASS for device development}
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 root@bonito"
dev() { $SSH "$1"; }

case "$MODE" in A|B) ;; *) echo "MODE must be A or B" >&2; exit 2 ;; esac

# --- gate 1: api29-root must be a real release ------------------------------
ROOT=$(dev 'readlink -f /home/art/api29-root')
echo "COMPONENT=$ROOT"
case "$ROOT" in /home/art/releases/api29-*) ;; *) echo "BISECT=REFUSED|api29-root=$ROOT" >&2; exit 2 ;; esac

# --- gate 2: lock must be held by this line --------------------------------
LOCK=$(dev 'cat /home/art/test/.device-lock/owner 2>/dev/null')
echo "LOCK_HOLDER=${LOCK:-none}"
case "$LOCK" in
  sd-integration*) ;;
  *) echo "BISECT=REFUSED|lock_not_mine|holder=${LOCK:-none}" >&2; exit 2 ;;
esac

# --- gate 3: only one companion injection device allowed at a time ----------
if [ "$MODE" = B ] && ! dev 'test -x /home/art/bin/sdinput'; then
  echo "BISECT=REFUSED|no_sdinput" >&2; exit 2
fi

ipid() { dev 'pidof lipstick || echo 0'; }
istart() { dev 'cut -d" " -f22 /proc/$(pidof lipstick || echo 1)/stat 2>/dev/null || echo 0'; }
input_count() { dev 'dmesg 2>/dev/null | grep -c "input: sdinput as"'; }

BEFORE_PID=$(ipid); BEFORE_START=$(istart); BEFORE_INPUTS=$(input_count)
echo "BISECT_START|label=$LABEL|mode=$MODE|secs=$SECS|lipstick=$BEFORE_PID|start=$BEFORE_START|sdinput_devices=$BEFORE_INPUTS"

n=0; t=0
while [ "$t" -lt "$SECS" ]; do
  n=$((n+1))
  if [ "$MODE" = A ]; then
    dev "export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket; gdbus call --session --dest org.nemomobile.lipstick --object-path / --method org.nemomobile.lipstick.saveScreenshot $SHOT_DIR/$LABEL-\$RANDOM.png >/dev/null 2>&1 || echo SHOT_FAIL"
  else
    dev "/home/art/bin/sdinput tap $TAP_X $TAP_Y" 2>&1 | grep -E "SDINPUT=" | head -2
  fi
  [ "$(ipid)" = "$BEFORE_PID" ] || { echo "LIPSTICK_LOST|after_iteration=$n"; break; }
  sleep 1.6; t=$((t+2))
done

AFTER_PID=$(ipid); AFTER_START=$(istart); AFTER_INPUTS=$(input_count)
NEW_DEVICES=$((AFTER_INPUTS - BEFORE_INPUTS))
echo "BISECT_END|label=$LABEL|mode=$MODE|iterations=$n|lipstick_before=$BEFORE_PID|lipstick_after=$AFTER_PID|start_before=$BEFORE_START|start_after=$AFTER_START|sdinput_devices_new=$NEW_DEVICES"

if [ "$BEFORE_PID" != "$AFTER_PID" ] || [ "$BEFORE_START" != "$AFTER_START" ] || [ "$AFTER_PID" = 0 ]; then
  # pull the crash lines so the failure carries evidence instead of a guess
  dev 'journalctl -b --no-pager 2>/dev/null | grep -E "lipstick\[|ANOM_ABEND|restart counter is at" | tail -12'
  echo "BISECT=$LABEL|LIPSTICK_CRASHED|mode=$MODE|before=$BEFORE_PID|after=$AFTER_PID|new_uinput=$NEW_DEVICES"
  exit 1
fi
echo "BISECT=$LABEL|SURVIVED|mode=$MODE|lipstick=$AFTER_PID|new_uinput=$NEW_DEVICES"
