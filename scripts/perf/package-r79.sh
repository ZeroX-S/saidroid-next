#!/bin/bash
# Package the already-built r79 product into a component bundle.
set -euo pipefail
cd /media/psf/Home/WorkSpace/saidroid-next
CMP=/var/tmp/saidroid-next-api29-component-r79
rm -rf "$CMP"
python3 scripts/runtime/package-component.py build/codex-api29/inputs \
  /var/tmp/saidroid-next-api29-framework-20261025-r4 \
  /var/tmp/saidroid-next-api29-core-20261025-r10 \
  /var/tmp/saidroid-next-api29-product-r79 \
  /var/tmp/saidroid-next-api29-manager-20261026-r18 \
  /var/tmp/saidroid-next-api29-native-20261025-r1 \
  /var/tmp/saidroid-next-api29-linker-20261026-r6 \
  "$CMP" --binder-device /home/art/runtime/binder/binder
