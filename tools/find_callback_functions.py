#!/usr/bin/env python3
"""
Find functions that ReXGlue's discovery missed: code addresses that the game
loads as constants (lis/addi or lis/ori pairs) and later calls through a
pointer (sort comparators, thread entry points), plus MSVC virtual-call
thunks. These often have no .pdata entry and no direct `bl` callers, and
calling one at runtime aborts with "Call to invalid or unregistered function".

Ported from the Doritos Crash Course port (same engine); addresses below are
Crash Course 2's (Title Update 2, offline build).

usage: find_callback_functions.py <image.bin> <generated/default/*_init.cpp> [out.toml]

image.bin is the decoded XEX image (tools/xexdump/xexdump.py).
Prints a [functions] TOML fragment for the codegen config.
"""
import bisect
import re
import struct
import sys

IMG_BASE = 0x82000000
TEXT_START, TEXT_END = 0x82230000, 0x82230000 + 0xABEACC
PDATA_START, PDATA_END = 0x821F3000, 0x821F3000 + 0x34040
DATA_SECTIONS = ((0x82000400, 0x1F2AC4), (0x82D00000, 0x6275FC))   # .rdata, .data

# Constant-loaded code addresses that are not function entries (checked by hand).
EXCLUDE = {
    0x828D4A00,  # exception-return path in the middle of a function epilogue
}


def main(image_path, init_cpp, out_path=None):
    img = open(image_path, 'rb').read()

    def word(a):
        return struct.unpack('>I', img[a - IMG_BASE:a - IMG_BASE + 4])[0]

    known = sorted(int(m, 16) for m in re.findall(r'\{\s*0x([0-9A-F]+),\s*sub_', open(init_cpp).read()))
    known_set = set(known)
    if not known:
        sys.exit('no functions found in ' + init_cpp)

    def containing(a):
        i = bisect.bisect_right(known, a) - 1
        return known[i] if i >= 0 else None

    # .pdata function starts, and ends: code right after a .pdata function is a
    # function boundary even when that function ends in a call that never returns.
    pdata, pdata_ends = set(), set()
    for o in range(PDATA_START - IMG_BASE, PDATA_END - IMG_BASE, 8):
        b, f = struct.unpack('>II', img[o:o + 8])
        if b:
            pdata.add(b)
            pdata_ends.add(b + ((f >> 8) & 0x3FFFFF) * 4)

    found = {}
    for a in range(TEXT_START, TEXT_END, 4):
        w = word(a)
        if (w >> 26) != 15 or ((w >> 16) & 31) != 0:      # lis rD, hi  (addis rD, 0, hi)
            continue
        rd = (w >> 21) & 31
        hi = w & 0xFFFF
        for k in range(1, 10):
            v = word(a + 4 * k)
            op = v >> 26
            ra = (v >> 16) & 31
            rs = (v >> 21) & 31
            if op == 14 and ra == rd:                     # addi rX, rD, lo
                lo = v & 0xFFFF
                target = ((hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF
            elif op == 24 and rs == rd:                   # ori rX, rD, lo
                target = (hi << 16) | (v & 0xFFFF)
            else:
                # stop if rD is overwritten or control flow leaves the block
                if op in (16, 18, 19):
                    break
                if ((v >> 21) & 31) == rd and op not in (36, 37, 38, 44, 45, 62, 52, 53, 54, 55):
                    break
                continue
            if not (TEXT_START <= target < TEXT_END) or target & 3 or target in known_set:
                break
            # A target inside the referencing function is a jump-table base or
            # local label, not a callback.
            if containing(target) == containing(a) or target in EXCLUDE:
                break
            prev = word(target - 4)
            boundary = (prev == 0x4E800020                 # blr
                        or prev == 0x4E800420              # bctr (thunk tails)
                        or prev == 0
                        or ((prev >> 26) == 18 and (prev & 1) == 0)   # b (no link)
                        or target in pdata or target in pdata_ends)
            if boundary:
                found.setdefault(target, []).append(a + 4 * k)
            break

    # Virtual-call thunks: lwz rA,0(rObj); lwz rB,off(rA); mtctr rB; bctr.
    # MSVC emits runs of these back to back; each is a complete function.
    thunks = set()
    for a in range(TEXT_START, TEXT_END - 12, 4):
        w0, w1, w2, w3 = (word(a + i) for i in range(0, 16, 4))
        if (w0 >> 26) != 32 or (w0 & 0xFFFF) != 0:                  # lwz rA, 0(rObj)
            continue
        ra = (w0 >> 21) & 31
        if (w1 >> 26) != 32 or ((w1 >> 16) & 31) != ra:            # lwz rB, off(rA)
            continue
        rb = (w1 >> 21) & 31
        if w2 != (0x7C0903A6 | (rb << 21)) or w3 != 0x4E800420 or a in known_set:
            continue
        # The same four instructions also appear as an inlined tail call inside
        # other functions (after a conditional branch, or after the function's own
        # first instruction). Only a pattern that starts right after the end of
        # the previous code is a stand-alone thunk.
        prev = word(a - 4)
        if (prev in (0x4E800020, 0x4E800420, 0) or ((prev >> 26) == 18 and (prev & 1) == 0)
                or a in pdata or a in pdata_ends):
            thunks.add(a)

    # Code pointers stored in data (CRT static-initializer tables, vtables,
    # callback tables). Same boundary rule, plus the target must decode as
    # instructions up to a terminator and must not lie inside a .pdata function.
    pd_ranges = []
    for o in range(PDATA_START - IMG_BASE, PDATA_END - IMG_BASE, 8):
        b, f = struct.unpack('>II', img[o:o + 8])
        if b:
            pd_ranges.append((b, b + ((f >> 8) & 0x3FFFFF) * 4))
    pd_ranges.sort()
    pd_starts = [r[0] for r in pd_ranges]

    def inside_pdata(a):
        i = bisect.bisect_right(pd_starts, a) - 1
        return i >= 0 and pd_ranges[i][0] < a < pd_ranges[i][1]

    def decodes_to_terminator(a):
        for k in range(256):
            v = word(a + 4 * k)
            if v == 0:
                return False
            op = v >> 26
            if op in (0, 1, 5, 6, 56, 57, 60, 61):          # unused/invalid primary opcodes
                return False
            if v in (0x4E800020, 0x4E800420) or (op == 18 and (v & 1) == 0):
                return True
        return False

    data_ptrs = {}
    for sec_start, sec_size in DATA_SECTIONS:
        for a in range(sec_start, sec_start + sec_size - 3, 4):
            t = word(a)
            if not (TEXT_START <= t < TEXT_END) or t & 3 or t in known_set or t in EXCLUDE:
                continue
            prev = word(t - 4)
            if not (prev in (0x4E800020, 0x4E800420, 0) or ((prev >> 26) == 18 and (prev & 1) == 0)
                    or t in pdata or t in pdata_ends):
                continue
            if inside_pdata(t) or not decodes_to_terminator(t):
                continue
            data_ptrs.setdefault(t, []).append(a)
    for t, refs in data_ptrs.items():
        if t not in thunks:
            found.setdefault(t, []).extend(refs)

    lines = ['# Functions reached only through pointers (found by tools/find_callback_functions.py)\n',
             '[functions]\n']
    for t in sorted(thunks):
        lines.append(f'0x{t:08X} = {{ size = 0x10 }}  # virtual-call thunk\n')
    for t in sorted(found):
        if t in thunks:
            continue
        refs = ', '.join(f'0x{r:08X}' for r in found[t][:3])
        lines.append(f'0x{t:08X} = {{}}  # referenced at {refs}\n')
    text = ''.join(lines)
    if out_path:
        open(out_path, 'w').write(text)
    print(f'{len(thunks)} virtual-call thunks, {len(set(found) - thunks)} other callbacks', file=sys.stderr)
    print(text)


if __name__ == '__main__':
    main(*sys.argv[1:])
