#!/bin/bash
# Packages the Linux build as CrashCourse2-linux-x64.tar.gz (no game files inside).
#   tools/package_linux.sh [output dir]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/out/build/linux-amd64-release"
SDK_LIB="${REXSDK_PREFIX:-/root/rexsdk-install}/lib"
OUT="${1:-$ROOT/out}"
STAGE="$(mktemp -d)"; PKG="$STAGE/CrashCourse2"
mkdir -p "$PKG/assets"
cp "$BUILD/crashcourse2" "$PKG/"
cp "$BUILD"/librexgpu-xenos.so "$SDK_LIB/librexruntime.so" "$PKG/"
# Every library finds its siblings next to itself.
for f in "$PKG"/*.so; do patchelf --set-rpath '$ORIGIN' "$f"; done
cp "$ROOT/packaging/README-linux.txt" "$PKG/README.txt"
cp "$ROOT/crashcourse2.toml" "$PKG/crashcourse2.toml"
echo "Run tools/build_offline_game.sh to make the game files here (see README.txt)." \
  > "$PKG/assets/PUT_GAME_FILES_HERE.txt"
mkdir -p "$PKG/tools"
cp "$ROOT/tools/build_offline_game.sh" "$ROOT/tools/make_offline_game.py" "$PKG/tools/"
(cd "$PKG" && ldd ./crashcourse2 ./*.so | grep "not found") && { echo "missing libraries"; exit 1; }
tar -C "$STAGE" -czf "$OUT/CrashCourse2-linux-x64.tar.gz" CrashCourse2
rm -rf "$STAGE"
ls -la "$OUT/CrashCourse2-linux-x64.tar.gz"
