#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
echo "== who"; id defaultuser; echo
echo "== api29-root"; ls -la /home/art/ | head -30
echo "== lock"; ls -ld /home/art/test 2>/dev/null; ls -l /home/art/test/.device-lock 2>/dev/null || echo no-lock
echo "== running app procs"; for p in /proc/[0-9]*; do c=$(tr "\0" " " < $p/cmdline 2>/dev/null | head -c 120); case "$c" in *saildroid*|*saidroid*|*dalvikvm*) echo "$p: $c";; esac; done
echo "== runtime dir"; ls -la /run/user/100000/saildroid/ 2>/dev/null
echo "== apps"; ls /home/art/apps/ 2>/dev/null
echo "== desktop"; ls /home/defaultuser/.local/share/applications/ 2>/dev/null
echo "== test tools"; ls /home/art/test/ | head -40
'
