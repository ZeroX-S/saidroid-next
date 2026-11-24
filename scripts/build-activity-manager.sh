#!/bin/bash
# Compatibility entry point: current sources require the real API 29 build.
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
: "${OUTPUT_DIR:?Set a new absolute VM build directory}"
case "$OUTPUT_DIR" in /var/tmp/saidroid-next-*) ;; *) exit 2 ;; esac
exec python3 "$task_root/scripts/runtime/build-product.py" \
    "${SAILDROID_API29_INPUTS:-$task_root/build/codex-api29/inputs}" "$OUTPUT_DIR"
