#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
echo "== lipstick lines count"; journalctl -b --no-pager 2>/dev/null | grep -c lipstick
echo "== sample"; journalctl -b --no-pager 2>/dev/null | grep -i lipstick | tail -15
echo "== cover/launching grep"; journalctl -b --no-pager 2>/dev/null | grep -iE "temporary ?cover|cover|launching" | tail -20
echo "== lipstick log files"; ls -la /home/defaultuser/.cache/lipstick* /var/log/lipstick* 2>/dev/null; find /home/defaultuser -maxdepth 3 -name "*.log" 2>/dev/null | head
echo "== qq last log tail"; tail -5 /home/art/data/logs/com.tencent.mobileqq/20261027T042657-35564.log
'
