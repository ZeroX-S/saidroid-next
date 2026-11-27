#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket
echo "== WindowModel"; gdbus introspect --session --dest org.nemomobile.lipstick --object-path /WindowModel 2>&1 | head -100
echo "== LauncherModel"; gdbus introspect --session --dest org.nemomobile.lipstick --object-path /LauncherModel 2>&1 | head -60
'
