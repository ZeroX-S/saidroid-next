#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket
echo "== rowCount WindowModel"; gdbus call --session --dest org.nemomobile.lipstick --object-path /WindowModel --method org.qtproject.Qt.QAbstractItemModel.rowCount 2>&1
echo "== rowCount LauncherModel"; gdbus call --session --dest org.nemomobile.lipstick --object-path /LauncherModel --method org.qtproject.Qt.QAbstractItemModel.rowCount 2>&1
echo "== available names"; gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.ListNames 2>&1 | tr "," "\n" | grep -i -E "lipstick|nemomobile|jolla|compositor|switcher" 
echo "== lipstick journal cover"; journalctl -b --no-pager 2>/dev/null | grep -iE "lipstick.*(cover|window)" | tail -20
'
