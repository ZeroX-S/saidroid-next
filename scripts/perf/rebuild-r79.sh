#!/bin/bash
# Rebuild + repackage the r79 performance component (direct wl_shm copy + proof counters).
set -euo pipefail
cd /media/psf/Home/WorkSpace/saidroid-next
OUT=/var/tmp/saidroid-next-api29-product-r79
CMP=/var/tmp/saidroid-next-api29-component-r79
rm -rf "$OUT" "$CMP"
python3 scripts/runtime/build-product.py build/codex-api29/inputs "$OUT"
python3 scripts/runtime/package-component.py build/codex-api29/inputs \
  /var/tmp/saidroid-next-api29-framework-20261025-r4 \
  /var/tmp/saidroid-next-api29-core-20261025-r10 \
  "$OUT" \
  /var/tmp/saidroid-next-api29-manager-20261026-r18 \
  /var/tmp/saidroid-next-api29-native-20261025-r1 \
  /var/tmp/saidroid-next-api29-linker-20261026-r6 \
  "$CMP" --binder-device /home/art/runtime/binder/binder
echo "LIBSD_WINDOW_SHA256=$(sha256sum "$OUT/libsdwindow.so" | cut -d' ' -f1)"
echo "RUNTIME_JAR_SHA256=$(sha256sum "$OUT/runtime.jar" | cut -d' ' -f1)"
