#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
for p in 40797 40798 40800 40832 40844; do printf "%s " $p; if [ -d /proc/$p ]; then echo -n "ALIVE ppid="; awk "{print \$4}" /proc/$p/stat; echo -n "  cmd="; tr "\0" " " < /proc/$p/cmdline; echo; else echo GONE; fi; done
echo "== ssh sessions"; ps -ef | grep -c "sshd-session"
'
