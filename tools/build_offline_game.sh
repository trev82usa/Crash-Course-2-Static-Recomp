#!/bin/bash
# Makes the game files this build needs from your own Crash Course 2 files (nothing is downloaded
# except two MIT-licensed tool repositories, and no game data leaves your machine).
#
#   tools/build_offline_game.sh <folder with your original default.xex, data.pak, ...> \
#                               <Title Update 2 file: TU_1C424IF_000000K000000.00000000000G5> \
#                               [output folder, default: ./assets]
#
# Needs: python3 (3.11+), git, make, g++ (or clang++).
set -euo pipefail
GAME="${1:?original game folder}"; TU="${2:?Title Update 2 file}"; OUT="${3:-assets}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${CC2_TOOLS_DIR:-$HOME/.cache/crashcourse2-tools}"
mkdir -p "$WORK"
[ -d "$WORK/revived" ] || git clone --depth 1 https://github.com/LegendaryFire/crash-course-2-revived "$WORK/revived"
[ -d "$WORK/xenia-mod" ] || git clone --depth 1 https://github.com/Lken-cmd/doritos-crash-course-xenia "$WORK/xenia-mod"
[ -x "$WORK/revived/xexmerge" ] || make -C "$WORK/revived" build
python3 -I "$HERE/make_offline_game.py" "$GAME" "$TU" "$OUT" \
    --revived "$WORK/revived" --xenia-mod "$WORK/xenia-mod"
