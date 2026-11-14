#!/usr/bin/env python3
"""Build the offline Crash Course 2 game files this port runs on.

  python3 tools/make_offline_game.py <game folder> <title update> <out folder> \
      --revived <crash-course-2-revived checkout> --xenia-mod <doritos-crash-course-xenia checkout>

<game folder> holds the original default.xex, data.pak and the rest. <title update> is
Title Update 2 (TU_1C424IF_000000K000000.00000000000G5). Both projects are MIT licensed:
  https://github.com/LegendaryFire/crash-course-2-revived   (TU merge, XEX repack; run `make` in it once)
  https://github.com/Lken-cmd/doritos-crash-course-xenia    (the offline patches and data.pak mod)

What comes out:
  default.xex  Title Update 2 merged (0.0.2.5), every patch the Xenia mod enables applied,
               repacked as a plain XEX. The port is recompiled from exactly this file, so the
               copy in assets/ has to be this one too.
  data.pak     the game's data.pak + the update's patch_tu1.pak + the Xenia mod's edits
               (offline course list, stars instead of coins, stand-in player models).
  the rest     copied unchanged.
The Xenia set is used rather than the console set because ReXGlue, like Xenia, draws no
Xbox avatars: the players need the stand-in models.
"""
import argparse
import os
import shutil
import sys
import tempfile
import tomllib

PATCH_TOML = "patches/5841124F - Doritos Crash Course 2 (offline).patch.toml"

# Sites where the patches `b` into their new code and jump back mid-function. A static
# recompiler cannot follow that, so these keep the game's own instruction and the port does
# the same work with mid-asm hooks (src/offline_detours.cpp, cc2_offline_hooks.toml).
# address -> the patch's value, checked so a different patch file is noticed.
DETOURS = {
    0x829ECC48: 0x4B8ECE38, 0x829EB7C8: 0x4B8EE2E0, 0x82AF3470: 0x4B7E6EE0,
    0x82B7D588: 0x4B75C548, 0x82B7235C: 0x4B7677A8, 0x829EEE60: 0x4B8EB5B4,
    0x82A88970: 0x4B851ABC,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("game")
    ap.add_argument("update")
    ap.add_argument("out")
    ap.add_argument("--revived", required=True)
    ap.add_argument("--xenia-mod", required=True)
    ap.add_argument("--unlock-all", action="store_true", help="every course unlocked, no stars")
    ap.add_argument("--race-solo", action="store_true", help="World Tour without AI racers")
    a = ap.parse_args()

    revived, xmod = os.path.abspath(a.revived), os.path.abspath(a.xenia_mod)
    sys.path[:0] = [revived, os.path.join(xmod, "tools")]
    import xexpatch          # crash-course-2-revived
    import tongaspak         # same file in both projects
    import build_cc2         # doritos-crash-course-xenia

    toml_path = os.path.join(xmod, PATCH_TOML)
    with open(toml_path, "rb") as f:
        patches = tomllib.load(f)["patch"]
    extra = {"Unlock all courses": a.unlock_all, "Race solo (no AI racers)": a.race_solo}
    enabled = [p["name"] for p in patches if p.get("is_enabled") or extra.get(p["name"])]
    print("Patches:\n  " + "\n  ".join(enabled))

    xexmerge = os.path.join(revived, "xexmerge")
    xexpatch.check_xexmerge(xexmerge)
    os.makedirs(a.out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        xex = xexpatch.find(a.game, "default.xex", tmp)
        xexp = xexpatch.find(a.update, "default.xexp", tmp)
        print("\nMerging Title Update 2:")
        image, header = xexpatch.merge_update(xexmerge, xex, xexp, tmp)
        print("Applying the offline patches:")
        original = bytes(image)
        xexpatch.apply_patches(image, xexpatch.patch_writes(toml_path, enabled))
        for addr, value in DETOURS.items():
            o = addr - xexpatch.BASE
            if int.from_bytes(image[o:o + 4], "big") != value:
                raise RuntimeError(f"unexpected patch at {addr:08X}: not the detour expected")
            image[o:o + 4] = original[o:o + 4]
        print(f"  {len(DETOURS)} detour sites left as the game had them (the port hooks them)")
        out_xex = os.path.join(a.out, "default.xex")
        with open(out_xex, "wb") as f:
            f.write(xexpatch.repack_xex(header, image))
        xexpatch.verify_xex(out_xex, image)

        print("\nBuilding data.pak (a couple of minutes):")
        pak = tongaspak.Pak.load(xexpatch.find(a.game, "data.pak", tmp))
        with open(xexpatch.find(a.update, "patch_tu1.pak", tmp), "rb") as f:
            tu = tongaspak.Pak(f.read())
        for name in tu.index:
            pak.put(name, tu.get(name))
        print(f"  merged the update's patch_tu1.pak: {len(tu.index)} files")
        build_cc2.apply_mod(pak)
        pak.save(os.path.join(a.out, "data.pak"))

    game_dir = os.path.abspath(a.game)
    for name in sorted(os.listdir(game_dir)):
        src = os.path.join(game_dir, name)
        if name in ("default.xex", "data.pak"):
            continue
        dst = os.path.join(a.out, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    print(f"\nDone: {a.out}")


if __name__ == "__main__":
    main()
