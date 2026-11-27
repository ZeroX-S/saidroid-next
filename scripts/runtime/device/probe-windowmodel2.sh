#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket
D="gdbus call --session --dest org.nemomobile.lipstick --object-path /WindowModel"
echo "-- noarg"; $D --method local.Lipstick.WindowModel.windowId 2>&1|head -3
echo "-- u0"; $D --method local.Lipstick.WindowModel.windowId 0 2>&1|head -3
echo "-- properties GetAll WindowModel"; gdbus call --session --dest org.nemomobile.lipstick --object-path /WindowModel --method org.freedesktop.DBus.Properties.GetAll local.Lipstick.WindowModel 2>&1|head -5
echo "-- properties GetAll QAbstractItemModel"; gdbus call --session --dest org.nemomobile.lipstick --object-path /WindowModel --method org.freedesktop.DBus.Properties.GetAll org.qtproject.Qt.QAbstractItemModel 2>&1|head -5
echo "-- submit"; $D --method org.qtproject.Qt.QAbstractItemModel.submit 2>&1|head -3
echo "-- count var"; for m in count rowCount length windows; do printf "%s: " "$m"; $D --method local.Lipstick.WindowModel.$m 2>&1|head -1; done
echo "-- xml"; $D --method org.freedesktop.DBus.Introspectable.Introspect 2>&1 | head -3
'
