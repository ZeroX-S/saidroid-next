#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'export XDG_RUNTIME_DIR=/run/user/100000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket
echo "== lipstick process"; ps -ef | grep -i lipstick | grep -v grep | head
echo "== journal works"; journalctl -b --no-pager -n 3 2>&1 | tail -5
echo "== com.jolla.lipstick root"; gdbus introspect --session --dest com.jolla.lipstick --object-path / 2>&1 | head -40
echo "== paths under org"; for p in /org /org/nemomobile /org/nemomobile/lipstick; do echo "-- $p"; gdbus introspect --session --dest org.nemomobile.lipstick --object-path $p 2>&1 | head -25; done
'
