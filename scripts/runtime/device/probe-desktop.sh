#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
echo "== qq desktop"; cat /home/defaultuser/.local/share/applications/org.saildroid.app.p1d47ed0aadf712ce2c80.desktop
echo "== manager desktop"; cat /home/defaultuser/.local/share/applications/org.saildroid.app.pf1ce1af3b1b430c137db.desktop
echo "== qq record"; cat /run/user/100000/saildroid/com.tencent.mobileqq.json
echo "== manager record"; cat /run/user/100000/saildroid/org.saildroid.manager.json
echo "== touch tool"; ls -l /home/art/test/delivery-touch-tool-r3/ 2>/dev/null
'
