#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'echo DEV_OK; sed -n 1,2p /etc/os-release; readlink -f /home/art/api29-root; cat /proc/sys/kernel/random/boot_id; pgrep -x lipstick'
