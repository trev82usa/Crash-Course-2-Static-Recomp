#!/usr/bin/env python3
"""Find where functions of one build of the game sit in another build (base -> Title Update 2).

  remap_functions.py old_image.bin new_image.bin 0x82B30990 0x82AE0E50 ...

Each old function (bounds from .pdata) is compared, instruction by instruction, with every
.pdata function of the new image of the same length. Immediate fields that hold addresses or
offsets that move when the executable is relinked (branch targets, D-form immediates) are
ignored; register fields and opcodes must match. Prints old -> new, or the candidates when
the match is not unique.
"""
import struct
import sys
from collections import defaultdict

B = 0x82000000


def pdata(img):
    pe = struct.unpack("<I", img[0x3C:0x40])[0]
    n = struct.unpack("<H", img[pe + 6:pe + 8])[0]
    opt = struct.unpack("<H", img[pe + 20:pe + 22])[0]
    s = pe + 24 + opt
    for i in range(n):
        name, vs, va = struct.unpack("<8sII", img[s + i * 40:s + i * 40 + 16])
        if name.rstrip(b"\0") == b".pdata":
            break
    out = {}
    for o in range(va, va + vs, 8):
        begin, info = struct.unpack(">II", img[o:o + 8])
        if begin:
            out[begin] = ((info >> 8) & 0x3FFFFF) * 4
    return out


def masked(img, addr, size):
    words = struct.unpack(f">{size // 4}I", img[addr - B:addr - B + size])
    out = []
    for w in words:
        op = w >> 26
        if op == 18:                     # b / bl
            w &= 0xFC000003
        elif op == 16:                   # bc: keep (function-internal), but tail bc may move
            w &= 0xFFFF0003
        elif op in (7, 8, 10, 11, 12, 13, 14, 15, 24, 25, 26, 27, 28, 29) or 32 <= op <= 55 \
                or op in (58, 62):
            w &= 0xFFFF0000
        out.append(w)
    return tuple(out)


def main(old_path, new_path, *addrs):
    old, new = open(old_path, "rb").read(), open(new_path, "rb").read()
    op, np_ = pdata(old), pdata(new)
    by_size = defaultdict(list)
    for a, s in np_.items():
        by_size[s].append(a)
    cache = {}
    for text in addrs:
        a = int(text, 16)
        start = max((b for b in op if b <= a and a < b + op[b]), default=None)
        if start is None:
            print(f"{a:08X} -> ? (not in any .pdata function)")
            continue
        size = op[start]
        key = masked(old, start, size)
        hits = []
        for b in by_size[size]:
            if b not in cache:
                cache[b] = masked(new, b, size)
            if cache[b] == key:
                hits.append(b)
        off = a - start
        if len(hits) == 1:
            print(f"{a:08X} -> {hits[0] + off:08X}")
        else:
            print(f"{a:08X} -> {len(hits)} matches: " + " ".join(f"{h + off:08X}" for h in hits[:6]))


if __name__ == "__main__":
    main(*sys.argv[1:])
