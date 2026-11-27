#!/bin/bash
set -u
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=6 root@bonito"
$SSH '
python3 -V 2>&1; python3 -c "import PIL;print(\"PIL\",PIL.__version__)" 2>&1 | head -2
for t in convert magick pngtopnm ffmpeg gst-launch-1.0; do printf "%s: " $t; command -v $t || echo no; done
echo "== numpy"; python3 -c "import numpy;print(numpy.__version__)" 2>&1|head -1
ls /home/art/inject_touch /home/art/test/delivery-touch-tool-r3/inject-touch 2>&1
'
