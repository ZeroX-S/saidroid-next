#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
echo "== wrapper"; cat /home/art/apps/com.tencent.mobileqq/com.tencent.mobileqq
echo "== desktop files"; ls /home/defaultuser/.local/share/applications/ | grep -i saildroid
echo "== qq desktop"; cat /home/defaultuser/.local/share/applications/*p1d47ed0aadf712ce2c80.desktop
echo "== manager desktop"; cat /home/defaultuser/.local/share/applications/*manager*.desktop
'
