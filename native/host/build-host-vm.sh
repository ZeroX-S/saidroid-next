#!/bin/bash
set -euo pipefail
out=${1:?output directory required}
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
mkdir -p "$out"
gcc -O2 -Wall -Wextra -o "$out/saildroid-app" "$repo/native/host/host-bootstrap.c"
includes=(-I"$repo/third_party/art-standalone/libnativehelper/include/nativehelper" -I"$repo/third_party/art-standalone/libnativehelper/include")
read -ra pulse_flags <<< "$(pkg-config --cflags --libs libpulse)"
read -ra gio_flags <<< "$(pkg-config --cflags --libs gio-2.0)"
g++ -std=c++17 -O2 -Wall -Wextra -rdynamic -o "$out/saildroid-host" \
 "$repo/native/host/saildroid-app.cpp" "$repo/native/host/host-entry.cpp" "$repo/native/host/host-manager.cpp" \
 "${includes[@]}" "${gio_flags[@]}" -L/home/art/lib -Wl,-rpath,/home/art/lib -lnativehelper -ldl -pthread
g++ -std=c++17 -O2 -Wall -Wextra -fPIC -shared -o "$out/libsdhostapi.so" \
 "$repo/native/host/host-api.cpp" "$repo/native/host/host-audio.cpp" "$repo/native/host/host-audio-record.cpp" "$repo/native/host/host-network.cpp" "${includes[@]}" "${gio_flags[@]}" "${pulse_flags[@]}" -pthread
