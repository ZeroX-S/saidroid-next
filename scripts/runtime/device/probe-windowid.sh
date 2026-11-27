#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket
for i in 0 1 2 3 4 5 8 12 -1; do printf "windowId(%s): " "$i"; gdbus call --session --dest org.nemomobile.lipstick --object-path /WindowModel --method local.Lipstick.WindowModel.windowId "$i" 2>&1 | head -2; done
echo "== topmost"; gdbus call --session --dest org.nemomobile.lipstick --object-path / --method org.nemomobile.compositor.privateTopmostWindowProcessId
echo "== policy appid"; gdbus call --session --dest org.nemomobile.lipstick --object-path / --method org.nemomobile.compositor.privateTopmostWindowPolicyApplicationId
'
