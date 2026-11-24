#!/bin/bash
# One lock window for the direct-copy optimisation (r79). Run inside the VM with the
# device lock already held by sd-runtime; this script does not acquire or release it.
set -uo pipefail
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
cd /media/psf/Home/WorkSpace/saidroid-next

echo "=== close owned processes"
python3 scripts/perf/close-owned-vm.py || exit 4

echo "=== deploy r79"
sshpass -e ssh -o StrictHostKeyChecking=no root@bonito 'rm -rf /home/art/test/api29-deploy-r79' || exit 5
python3 scripts/runtime/deploy-component.py /var/tmp/saidroid-next-api29-component-r79 r79 || exit 5
readlink /home/art/api29-root

echo "=== install probe APK"
rm -rf /var/tmp/saidroid-next-api29-perfscroll-r79-scroll
cp -a /var/tmp/saidroid-next-api29-perfscroll-r79-probe4 /var/tmp/saidroid-next-api29-perfscroll-r79-scroll
python3 scripts/perf/install-scroll-vm.py r79-probe4 || exit 6

echo "=== runs"
python3 scripts/perf/run-matrix-vm.py r79 \
  --only scroll-color-legacy --only scroll-color-copy \
  --only scroll-pulse-handler --only scroll-pulse-copy \
  --only scroll-copy --only scroll-copy-triple --only qq-copy
status=$?
echo "WINDOW_DONE status=$status"
exit $status
