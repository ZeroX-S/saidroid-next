#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
for m in get_display_status get_tklock_mode; do printf "%s: " $m; dbus-send --system --print-reply --reply-timeout=2000 --dest=com.nokia.mce /com/nokia/mce/request com.nokia.mce.request.$m 2>&1 | tr "\n" " "; echo; done
grep -E "^(State|Name)" /sys/class/backlight/*/brightness 2>/dev/null
cat /sys/class/backlight/*/brightness 2>/dev/null; cat /sys/class/backlight/*/actual_brightness 2>/dev/null
'
