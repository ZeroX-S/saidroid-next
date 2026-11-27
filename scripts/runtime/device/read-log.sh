#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'L=/home/art/data/logs/com.tencent.mobileqq/20261027T044933-36648.log; wc -l $L; grep -nE "SDLAUNCHER|SDWINDOW=|SDACTIVITY|SDRUNTIME=(failed|application_ready)|SDWINDOW_SESSION=drawn" $L | head -40; echo ==TAIL==; tail -6 $L'
