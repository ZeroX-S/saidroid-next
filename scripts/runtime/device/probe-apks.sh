#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'ls -la /home/defaultuser/Downloads/SailDroid-APKs/ 2>&1; echo ---; ls /home/art/apps/; echo ---; ls /home/defaultuser/Downloads/ | head'
