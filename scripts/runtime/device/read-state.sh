#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket
echo -n "topmost: "; gdbus call --session --dest org.nemomobile.lipstick --object-path / --method org.nemomobile.compositor.privateTopmostWindowProcessId 2>&1
echo -n "qq: "; python3 -c "import json;d=json.load(open(\"/run/user/100000/saildroid/com.tencent.mobileqq.json\"));print(d.get(\"state\"),d.get(\"pid\"),d.get(\"log\"))" 2>&1
echo -n "qqprocs: "; for p in /proc/[0-9]*; do c=$(tr "\0" " " < $p/cmdline 2>/dev/null); case "$c" in com.tencent.mobileqq*|saildroid-supervisor*com.tencent*) echo -n "$p "; ; esac; done; echo
echo -n "lock: "; cat /home/art/test/.device-lock/owner 2>/dev/null || echo FREE
'
