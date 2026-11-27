#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket
echo "== objects"; gdbus call --session --dest org.nemomobile.lipstick --object-path / --method org.freedesktop.DBus.Introspectable.Introspect 2>&1 | head -60
echo "== root ifaces"; gdbus introspect --session --dest org.nemomobile.lipstick --object-path / 2>&1 | head -80
'
