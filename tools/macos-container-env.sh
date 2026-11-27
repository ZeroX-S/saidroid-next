#!/usr/bin/env bash
# Set up and run a native aarch64 Linux build/test environment on macOS using
# Apple's `container` CLI (with automatic fallback to docker/podman).
#
# Usage:
#   bash tools/macos-container-env.sh setup          # Build image, apply patches, fetch API 28 inputs
#   bash tools/macos-container-env.sh test           # Run full 38-suite regression & native compile gate
#   bash tools/macos-container-env.sh build-native [out_dir]  # Build runtime.jar + native aarch64 binaries
#   bash tools/macos-container-env.sh shell          # Open interactive Linux shell in /workspace
#   bash tools/macos-container-env.sh exec <cmd...>  # Execute command inside container
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_DIR="${SAILDROID_INPUTS:-${HOME}/.cache/saidroid-inputs}"
CPUS="${SAILDROID_CONTAINER_CPUS:-4}"
MEMORY="${SAILDROID_CONTAINER_MEMORY:-6g}"
TARGET_ARCH="${SAILDROID_CONTAINER_ARCH:-arm64}"
IMAGE="${SAILDROID_CONTAINER_IMAGE:-saildroid-dev:ubuntu24-${TARGET_ARCH}}"

detect_cli() {
  if [[ -n "${SAILDROID_CONTAINER_CLI:-}" ]]; then
    echo "${SAILDROID_CONTAINER_CLI}"
    return
  fi
  if command -v container >/dev/null 2>&1; then
    echo "container"
  elif command -v docker >/dev/null 2>&1; then
    echo "docker"
  elif command -v podman >/dev/null 2>&1; then
    echo "podman"
  else
    echo "ERROR: No container runtime found. Install Apple 'container' (brew install container) or Docker." >&2
    exit 1
  fi
}

CLI="$(detect_cli)"

ensure_runtime_started() {
  if [[ "$CLI" == "container" ]]; then
    if ! container ls >/dev/null 2>&1; then
      echo "==> Starting Apple container system service..."
      container system start
    fi
  fi
}

build_image() {
  ensure_runtime_started
  echo "==> Building ${IMAGE} (${TARGET_ARCH}) via ${CLI}..."
  local ctx
  ctx="$(mktemp -d)"
  trap 'rm -rf "${ctx:-}"' RETURN
  if [[ "$CLI" == "container" ]]; then
    container build \
      --arch "${TARGET_ARCH}" \
      --cpus "${CPUS}" \
      --memory "${MEMORY}" \
      --file "${REPO_ROOT}/tools/Containerfile.dev" \
      --tag "${IMAGE}" \
      "${ctx}"
  else
    "${CLI}" build \
      --platform "linux/${TARGET_ARCH}" \
      -f "${REPO_ROOT}/tools/Containerfile.dev" \
      -t "${IMAGE}" \
      "${ctx}"
  fi
}

image_exists() {
  if [[ "$CLI" == "container" ]]; then
    container image ls --quiet 2>/dev/null | grep -Fxq "${IMAGE}" || \
      container image ls 2>/dev/null | awk '{print $1":"$2}' | grep -Fxq "${IMAGE}"
  else
    "${CLI}" image inspect "${IMAGE}" >/dev/null 2>&1
  fi
}

run_in_container() {
  local interactive="$1"
  shift
  ensure_runtime_started
  mkdir -p "${CACHE_DIR}" "${REPO_ROOT}/build"
  if ! image_exists; then
    build_image
  fi

  local args=(run --rm)
  if [[ "$interactive" == "1" ]]; then
    args+=(-i -t)
  fi
  if [[ "$CLI" == "container" ]]; then
    args+=(
      --arch "${TARGET_ARCH}"
      --cpus "${CPUS}"
      --memory "${MEMORY}"
      --mount "type=bind,source=${REPO_ROOT},target=/workspace"
      --mount "type=bind,source=${CACHE_DIR},target=/cache/saidroid-inputs"
      --workdir /workspace
      -e "SAILDROID_INPUTS=/cache/saidroid-inputs"
    )
  else
    args+=(
      --platform "linux/${TARGET_ARCH}"
      -v "${REPO_ROOT}:/workspace"
      -v "${CACHE_DIR}:/cache/saidroid-inputs"
      -w /workspace
      -e "SAILDROID_INPUTS=/cache/saidroid-inputs"
    )
  fi
  exec "${CLI}" "${args[@]}" "${IMAGE}" "$@"
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  build-image)
    build_image
    ;;
  setup)
    build_image
    run_in_container 0 bash -lc '
      set -euo pipefail
      git submodule update --init
      git submodule foreach "git checkout -- . && git clean -fdx" >/dev/null
      python3 tools/apply-third-party-patches.py
      mkdir -p "$SAILDROID_INPUTS" build
      python3 scripts/runtime/fetch-inputs.py "$SAILDROID_INPUTS" --skip-sysimg
      ln -sfn "$SAILDROID_INPUTS" build/inputs
      echo "SAILDROID_CONTAINER_ENV=ready|arch=$(uname -m)|java=$JAVA_HOME|inputs=$SAILDROID_INPUTS"
    '
    ;;
  test)
    run_in_container 0 python3 tools/run-tests.py "$@"
    ;;
  build-native)
    out_rel="${1:-build/out-aarch64}"
    run_in_container 0 bash -lc "
      set -euo pipefail
      out=\"/workspace/${out_rel}\"
      rm -rf \"\$out\"
      python3 scripts/runtime/build-product.py /cache/saidroid-inputs \"\$out/product\" --compat-only
      python3 - \"\$out/native\" \"\$JAVA_HOME/include\" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, '/workspace/tools')
import importlib.util
spec = importlib.util.spec_from_file_location('rt', '/workspace/tools/run-tests.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out_dir = mod.verify_native_builds(Path(sys.argv[1]), Path(sys.argv[2]))
print('SAILDROID_NATIVE_OUT=' + str(out_dir))
PY
      ls -lh \"\$out/product/runtime.jar\" \"\$out/native/native\"
    "
    ;;
  shell)
    run_in_container 1 /bin/bash
    ;;
  exec)
    if [[ $# -eq 0 ]]; then
      echo "Usage: $0 exec <command...>" >&2
      exit 2
    fi
    run_in_container 0 "$@"
    ;;
  *)
    sed -n '2,11p' "$0"
    ;;
esac
