#!/bin/bash
# Build a performance component (r79 = r78 sources + direct wl_shm pixel copy).
set -euo pipefail
cd /media/psf/Home/WorkSpace/saidroid-next
OUT=/var/tmp/saidroid-next-api29-product-r79
CMP=/var/tmp/saidroid-next-api29-component-r79
rm -rf "$OUT" "$CMP"
python3 scripts/runtime/build-product.py build/codex-api29/inputs "$OUT"
python3 scripts/runtime/package-component.py build/codex-api29/inputs \
  /var/tmp/saidroid-next-framework-20261025-r4 \
  /var/tmp/saidroid-next-core-20261025-r10 \
  "$OUT" \
  /var/tmp/saidroid-next-manager-20261026-r18 \
  /var/tmp/saidroid-next-native-20261025-r1 \
  /var/tmp/saidroid-next-linker-20261026-r6 \
  "$CMP" --binder-device /home/art/runtime/binder/binder
