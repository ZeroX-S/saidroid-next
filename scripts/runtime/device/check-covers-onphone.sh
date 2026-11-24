#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
S=/media/psf/Home/WorkSpace/saidroid-next
sshpass -e scp -O -o StrictHostKeyChecking=no $S/scripts/runtime/tests/sd_covers.py root@bonito:/home/art/test/matrix-tools/sd_covers.py
$SSH 'cd /home/art/test/matrix-tools && python3 - <<PY
import sys
sys.path.insert(0, ".")
import sd_covers
base = "/home/defaultuser/Downloads/SailDroid-Screenshots/"
want = ["int-home-covers2.png","int-home-manager2.png","int-calib-01.png","multi-shell-r18.png"]
for name in want:
    covers, cells, stats = sd_covers.analyze(base + name)
    print("%-30s covers=%d blank=%s low=%s edge=%.4f" % (name, covers, stats["blank"], stats["low_content"], stats["edge_fraction"]))
PY'
