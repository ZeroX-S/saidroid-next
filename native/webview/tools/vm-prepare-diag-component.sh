#!/bin/sh
# Package the draw-audit product into a deployable component (no device writes).
# Mirrors build/codex-api29/prepare-r78-vm.py so the only difference from r78
# is runtime.jar (my provider with the draw audit); the framework is r6, i.e.
# Lead's View.getLayoutParams()/measureChild* null-params repair.
set -eu
REPO=/media/psf/Home/WorkSpace/saidroid-next
COMP=/var/tmp/saidroid-next-api29-component-webview-diag
rm -rf "$COMP"
python3 "$REPO/scripts/runtime/package-component.py" \
    "$REPO/build/codex-api29/inputs" \
    /var/tmp/saidroid-next-api29-framework-20261027-r6 \
    /var/tmp/saidroid-next-api29-core-20261025-r10 \
    /var/tmp/saidroid-next-webview-diag \
    /var/tmp/saidroid-next-api29-manager-20261026-r18 \
    /var/tmp/saidroid-next-api29-native-20261025-r1 \
    /var/tmp/saidroid-next-api29-linker-20261026-r6 \
    "$COMP" \
    --binder-device /home/art/runtime/binder/binder
echo "COMPONENT=$COMP"
ls -la "$COMP" | head
