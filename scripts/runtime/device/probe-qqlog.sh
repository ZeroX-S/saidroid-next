#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH 'L=/home/art/data/logs/com.tencent.mobileqq/20261027T042657-35564.log; wc -l $L; grep -nE "SDACTIVITY|SDWINDOW|SDLAUNCHER|NullPointer|WebView|Cookie" $L | tail -40'
