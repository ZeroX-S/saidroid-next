#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
echo "== ps 40800"; ps -p 40800 -o pid,ppid,user,stat,etime,args 2>&1
echo "== tail procs"; ps -ef | tail -15
echo "== manager log full"; cat /home/art/data/logs/org.saildroid.manager/20261027T043840-27196.log | tail -40
echo "== qq dirs"; ls -lt /home/art/data/logs/com.tencent.mobileqq/ | head -5
'
