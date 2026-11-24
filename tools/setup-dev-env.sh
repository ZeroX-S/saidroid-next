#!/usr/bin/env bash
# Idempotent, non-interactive development environment setup for SailDroid (API 28).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

APT_PACKAGES=(
  openjdk-21-jdk
  aidl
  aapt
  libsmali-java
  rpm
  libcap2-bin
  bubblewrap
  weston
  sshpass
  pkg-config
  libglib2.0-dev
  libpulse-dev
  libwayland-dev
  wayland-protocols
  libegl-dev
  libgles-dev
  libpng-dev
  libdbus-1-dev
  libgstreamer1.0-dev
  libgstreamer-plugins-base1.0-dev
  qtbase5-dev
  qtdeclarative5-dev
  gcc-aarch64-linux-gnu
  g++-aarch64-linux-gnu
  binutils-aarch64-linux-gnu
  qemu-user
)

if command -v apt-get >/dev/null 2>&1; then
  missing_pkgs=()
  for pkg in "${APT_PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" >/dev/null 2>&1; then
      missing_pkgs+=("$pkg")
    fi
  done
  if (( ${#missing_pkgs[@]} > 0 )); then
    sudo_cmd=()
    if [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
      sudo_cmd=(sudo)
    fi
    if [[ -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
      "${sudo_cmd[@]}" apt-get update \
        -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/ubuntu.sources \
        -o Dir::Etc::sourceparts=/nonexistent \
        -o APT::Get::List-Cleanup=0
    else
      "${sudo_cmd[@]}" apt-get update
    fi
    "${sudo_cmd[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y \
      --no-upgrade --no-install-recommends "${missing_pkgs[@]}"
  fi
fi

if ! python3 -c "import paramiko" >/dev/null 2>&1; then
  python3 -m pip install --quiet --no-input paramiko
fi

BASHRC="${HOME}/.bashrc"
touch "$BASHRC"
sed -i '/case \$- in/,/esac/d' "$BASHRC" 2>/dev/null || true

if [[ -d /usr/lib/jvm/java-21-openjdk-amd64 ]]; then
  export JAVA_HOME="/usr/lib/jvm/java-21-openjdk-amd64"
  grep -qxF 'export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64' "$BASHRC" || \
    echo 'export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64' >> "$BASHRC"
fi

export SAILDROID_INPUTS="${SAILDROID_INPUTS:-${HOME}/.cache/saidroid-inputs}"
grep -qxF 'export SAILDROID_INPUTS="$HOME/.cache/saidroid-inputs"' "$BASHRC" || \
  echo 'export SAILDROID_INPUTS="$HOME/.cache/saidroid-inputs"' >> "$BASHRC"

git -C "$REPO_ROOT" submodule update --init
git -C "$REPO_ROOT" submodule foreach 'git checkout -- . && git clean -fdx' >/dev/null
python3 "$REPO_ROOT/tools/apply-third-party-patches.py"

mkdir -p "$SAILDROID_INPUTS" "$REPO_ROOT/build"
python3 "$REPO_ROOT/scripts/api29/fetch-inputs.py" "$SAILDROID_INPUTS" --skip-sysimg
ln -sfn "$SAILDROID_INPUTS" "$REPO_ROOT/build/inputs"

echo "SAILDROID_DEV_ENV=ready|inputs=$SAILDROID_INPUTS"
