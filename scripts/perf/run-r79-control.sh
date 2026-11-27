#!/bin/bash
# Second short r79 window: the control that separates "one less copy" from "one
# more buffer", plus a touch run on the direct path. Takes and releases the lock.
set -uo pipefail
export SSHPASS="${SSHPASS:?Set SSHPASS for device development}"
cd /media/psf/Home/WorkSpace/saidroid-next

status=0
cleanup() {
  python3 scripts/perf/close-owned-vm.py >/dev/null 2>&1
  python3 scripts/perf/restore-baseline-vm.py api29-r78 || status=7
  scripts/devlock.sh release sd-runtime || status=8
}
trap cleanup EXIT

scripts/devlock.sh acquire 600 sd-runtime || { echo "WINDOW_REFUSED reason=lock"; exit 2; }
python3 scripts/perf/close-owned-vm.py || exit 4
sshpass -e ssh -o StrictHostKeyChecking=no root@bonito 'rm -rf /home/art/test/api29-deploy-r79c' || exit 5
python3 scripts/runtime/deploy-component.py /var/tmp/saidroid-next-api29-component-r79 r79c || exit 5
readlink /home/art/api29-root
python3 scripts/perf/install-scroll-vm.py r79-probe4 || exit 6
python3 scripts/perf/run-matrix-vm.py r79c --only scroll-triple-legacy --only scroll-copy-touch
status=$?
echo "WINDOW_DONE status=$status"
exit $status
