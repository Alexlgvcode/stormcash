#!/usr/bin/env bash
# Builds the C++ proof check as WebAssembly for the public proof page and
# copies it to dashboard/src/wasm/ (stormcash_verify.mjs and .wasm).
#
# Those two files are committed, so the dashboard builds them in as they are,
# with no Emscripten. `build.sh --check` (CI's wasm job) builds from the
# current sources and fails unless the result equals the committed files byte
# for byte, so what the page runs is exactly this C++ code.
#
# Needs Emscripten $EMSCRIPTEN_VERSION, from emsdk:
#   git clone --depth 1 --branch 6.0.10 https://github.com/emscripten-core/emsdk.git
#   emsdk/emsdk install 6.0.10 && emsdk/emsdk activate 6.0.10
#   source emsdk/emsdk_env.sh
set -euo pipefail

EMSCRIPTEN_VERSION=6.0.10

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
build="${STORMCASH_WASM_BUILD_DIR:-$repo/cpp/build-wasm}"
out="$repo/dashboard/src/wasm"
check=false
case "${1:-}" in
  "") ;;
  --check) check=true ;;
  *) echo "usage: cpp/verify/wasm/build.sh [--check]" >&2; exit 2 ;;
esac

if ! command -v emcc >/dev/null; then
  echo "build.sh: emcc not found; install Emscripten $EMSCRIPTEN_VERSION (see the top of this file)" >&2
  exit 2
fi
found="$(emcc --version 2>/dev/null | head -n 1 | sed -E 's/.* ([0-9]+\.[0-9]+\.[0-9]+) .*/\1/')"
if [ "$found" != "$EMSCRIPTEN_VERSION" ]; then
  echo "build.sh: need Emscripten $EMSCRIPTEN_VERSION, found $found" >&2
  exit 2
fi

emcmake cmake -S "$repo/cpp" -B "$build" -DCMAKE_BUILD_TYPE=MinSizeRel -DSTORMCASH_WERROR=ON >/dev/null
cmake --build "$build" -j 4

status=0
for f in stormcash_verify.mjs stormcash_verify.wasm; do
  built="$build/verify/wasm/$f"
  size="$(wc -c <"$built" | tr -d ' ')"
  if $check; then
    if cmp -s "$built" "$out/$f"; then
      echo "ok    dashboard/src/wasm/$f matches this build ($size bytes)"
    else
      echo "DIFF  dashboard/src/wasm/$f is not what these sources build; run cpp/verify/wasm/build.sh and commit it" >&2
      status=1
    fi
  else
    cp "$built" "$out/$f"
    chmod 644 "$out/$f"
    echo "wrote dashboard/src/wasm/$f ($size bytes)"
  fi
done
exit "$status"
