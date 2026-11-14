#!/usr/bin/env python3
"""Detect PPC jump tables in a decrypted Xbox 360 image and emit a
XenonRecomp switch-table TOML.

Instead of matching fixed instruction orderings, every `mtctr rN; bctr` is
traced back to its bounds check (`cmplwi crF, rX, N`) and the instructions in
between are executed concretely once per index 0..N, reading table data from
the image. That handles absolute, byte-offset and short-offset tables
regardless of how the compiler scheduled them.

Usage: find_switch_tables.py <image.bin> <out.toml> [functions_out.toml] [--base 0x82000000]
       [--text 0x82230000:0xABEACC]
"""
import struct
import sys

BASE = 0x82000000
MAX_BACK = 24


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def rotl32(v, n):
    v &= 0xFFFFFFFF
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF if n else v


def mask32(mb, me):
    m = 0
    for b in range(32):
        bit = 31 - b
        inside = (mb <= b <= me) if mb <= me else (b >= mb or b <= me)
        if inside:
            m |= 1 << bit
    return m


class Image:
    def __init__(self, data, base):
        self.data = data
        self.base = base

    def word(self, addr):
        return struct.unpack_from(">I", self.data, addr - self.base)[0]

    def load(self, addr, size):
        off = addr - self.base
        if off < 0 or off + size > len(self.data):
            raise ValueError("load out of image")
        return int.from_bytes(self.data[off : off + size], "big")


def is_mtctr(w):
    return (w & 0xFC1FFFFF) == 0x7C0903A6


def mtctr_reg(w):
    return (w >> 21) & 31


def run(img, insns, regs):
    """Execute a straight-line list of (addr, word). Returns regs or None."""
    for addr, w in insns:
        op = w >> 26
        rd = (w >> 21) & 31
        ra = (w >> 16) & 31
        rb = (w >> 11) & 31
        imm = w & 0xFFFF
        if op == 15:  # addis / lis
            regs[rd] = ((regs.get(ra, 0) if ra else 0) + (s16(imm) << 16)) & 0xFFFFFFFF
            if ra and ra not in regs:
                return None
        elif op == 14:  # addi / li
            if ra and ra not in regs:
                return None
            regs[rd] = ((regs[ra] if ra else 0) + s16(imm)) & 0xFFFFFFFF
        elif op == 21:  # rlwinm
            rs, sh, mb, me = rd, rb, (w >> 6) & 31, (w >> 1) & 31
            if rs not in regs:
                return None
            regs[ra] = rotl32(regs[rs], sh) & mask32(mb, me)
        elif op == 24 and w == 0x60000000:  # nop
            pass
        elif op == 16:  # bc: bounds-check branch, assume not taken
            pass
        elif op == 10:  # cmplwi
            pass
        elif op == 31:
            xo = (w >> 1) & 0x3FF
            if xo in (23, 279, 87):  # lwzx, lhzx, lbzx
                if (ra and ra not in regs) or rb not in regs:
                    return None
                ea = ((regs[ra] if ra else 0) + regs[rb]) & 0xFFFFFFFF
                size = {23: 4, 279: 2, 87: 1}[xo]
                regs[rd] = img.load(ea, size)
            elif xo == 266:  # add
                if ra not in regs or rb not in regs:
                    return None
                regs[rd] = (regs[ra] + regs[rb]) & 0xFFFFFFFF
            elif xo == 444 and rd == rb:  # mr (or rA,rS,rS)
                if rd not in regs:
                    return None
                regs[ra] = regs[rd]
            elif xo == 467:  # mtspr (mtctr)
                pass
            else:
                return None
        else:
            return None
    return regs


def regs_rw(w):
    """(reads, writes) for the subset of ops `run` understands, else None."""
    op = w >> 26
    rd = (w >> 21) & 31
    ra = (w >> 16) & 31
    rb = (w >> 11) & 31
    if op in (14, 15):
        return ({ra} if ra else set(), {rd})
    if op == 21:
        return ({rd}, {ra})
    if w == 0x60000000 or op in (10, 16):
        return (set(), set())
    if op == 31:
        xo = (w >> 1) & 0x3FF
        if xo in (23, 279, 87):
            return (({ra} if ra else set()) | {rb}, {rd})
        if xo == 266:
            return ({ra, rb}, {rd})
        if xo == 444 and rd == rb:
            return ({rd}, {ra})
        if xo == 467:
            return ({rd}, set())
    return None


def load_functions(img, pdata_lo, pdata_size):
    funcs = []
    for off in range(0, pdata_size, 8):
        begin = img.word(pdata_lo + off)
        data = img.word(pdata_lo + off + 4)
        length = ((data >> 8) & 0x3FFFFF) * 4
        if begin:
            funcs.append((begin, begin + length))
    funcs.sort()
    return funcs


def containing_function(funcs, addr):
    import bisect
    i = bisect.bisect_right(funcs, (addr, 0xFFFFFFFF)) - 1
    if i >= 0 and funcs[i][0] <= addr < funcs[i][1]:
        return funcs[i]
    return None


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    base = BASE
    text_lo, text_size = 0x82230000, 0xABEACC
    pdata_lo, pdata_size = 0x821F3000, 0x34040
    if "--base" in args:
        base = int(args[args.index("--base") + 1], 0)
    if "--text" in args:
        a, s = args[args.index("--text") + 1].split(":")
        text_lo, text_size = int(a, 0), int(s, 0)
    if "--pdata" in args:
        a, s = args[args.index("--pdata") + 1].split(":")
        pdata_lo, pdata_size = int(a, 0), int(s, 0)
    text_hi = text_lo + text_size

    img = Image(open(args[0], "rb").read(), base)
    funcs = load_functions(img, pdata_lo, pdata_size)
    tables = []
    unresolved = []
    indirect_calls = 0
    unbounded = 0
    explicit = {}

    for addr in range(text_lo, text_hi - 4, 4):
        w = img.word(addr)
        if not is_mtctr(w) or img.word(addr + 4) != 0x4E800420:
            continue
        ctr_reg = mtctr_reg(w)

        # Walk back over straight-line code we can execute, stopping at
        # anything else (calls, loads with displacement, branches out).
        window = []
        cmp_at = None
        a = addr - 4
        for _ in range(MAX_BACK):
            iw = img.word(a)
            op = iw >> 26
            if op == 10 and ((iw >> 21) & 1) == 0 and (iw & 0xFFFF) != 0:
                cmp_at = a
                break
            if regs_rw(iw) is None:
                break
            window.insert(0, (a, iw))
            a -= 4

        # How is the jump target produced? Only table loads are switches.
        producer = None
        for pa, pw in reversed(window):
            rw = regs_rw(pw)
            if rw and ctr_reg in rw[1]:
                producer = pw
                break
        is_table = False
        if producer is not None:
            pop, pxo = producer >> 26, (producer >> 1) & 0x3FF
            is_table = pop == 31 and pxo in (23, 279, 87, 266)
        if not is_table:
            indirect_calls += 1
            continue

        # Registers read before being written inside the window are inputs;
        # exactly one must be free (the switch index).
        written, inputs = set(), []
        for _, iw in window:
            rd_, wr_ = regs_rw(iw)
            for r in rd_:
                if r not in written and r not in inputs:
                    inputs.append(r)
            written |= wr_

        if cmp_at is not None:
            cw = img.word(cmp_at)
            idx_reg = (cw >> 16) & 31
            count = (cw & 0xFFFF) + 1
            default = 0
            bw = img.word(cmp_at + 4)
            if (bw >> 26) == 16:
                default = cmp_at + 4 + s16(bw & 0xFFFC)
            table_base = cmp_at
            body = [(x, img.word(x)) for x in range(cmp_at + 4, addr + 4, 4)]
        else:
            if len(inputs) != 1:
                unresolved.append((addr, f"inputs={inputs}"))
                continue
            idx_reg = inputs[0]
            count = None
            default = 0
            table_base = window[0][0]
            body = window

        fn = containing_function(funcs, addr)
        if fn:
            lo, hi = fn
        else:
            # Frameless code between .pdata entries: bound by the gap.
            import bisect
            i = bisect.bisect_right(funcs, (addr, 0xFFFFFFFF))
            lo = funcs[i - 1][1] if i > 0 else text_lo
            hi = funcs[i][0] if i < len(funcs) else text_hi

        labels = []
        limit = count if count is not None else 1024
        failed = False
        for i in range(limit):
            try:
                regs = run(img, body, {idx_reg: i})
            except ValueError:
                regs = None
            tgt = regs.get(ctr_reg) if regs else None
            valid = tgt is not None and lo <= tgt < hi and not (tgt & 3)
            if not valid:
                if count is None and labels:
                    break  # reached end of an unbounded table
                failed = True
                break
            labels.append(tgt)
        if failed or not labels:
            unresolved.append((addr, "target outside function"))
            continue
        if count is None:
            unbounded += 1
        tables.append(dict(base=table_base, r=idx_reg, default=default, labels=labels))

        if not fn:
            # Give XenonRecomp an explicit boundary so it doesn't split the
            # dispatcher at each case or decode the inline table as code.
            def terminator(x):
                iw = img.word(x)
                return iw in (0x4E800020, 0x4E800420) or (iw >> 26 == 18 and (iw & 3) == 0)
            start = lo
            x = table_base - 4
            while x >= lo:
                if terminator(x):
                    start = x + 4
                    break
                x -= 4
            while start < table_base and img.word(start) in (0x00000000, 0x60000000):
                start += 4  # alignment padding / nop before the real entry
            end = max(labels)
            while end < hi and not terminator(end):
                end += 4
            end = min(end + 4, hi)
            explicit[start] = max(explicit.get(start, 0), end - start)

    with open(args[1], "w") as o:
        o.write("# Generated by tools/find_switch_tables.py\n")
        for t in tables:
            o.write("[[switch]]\n")
            o.write(f"base = 0x{t['base']:X}\n")
            o.write(f"r = {t['r']}\n")
            o.write(f"default = 0x{t['default']:X}\n")
            o.write("labels = [\n")
            for l in t["labels"]:
                o.write(f"    0x{l:X},\n")
            o.write("]\n\n")

    if len(args) > 2 and not args[2].startswith("--"):
        with open(args[2], "w") as o:
            o.write("# Generated by tools/find_switch_tables.py: frameless dispatchers\n")
            o.write("functions = [\n")
            merged = []
            for a in sorted(explicit):
                e = a + explicit[a]
                if merged and a < merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], e)  # interleaved cases
                else:
                    merged.append([a, e])
            for a, e in merged:
                o.write(f"    {{ address = 0x{a:X}, size = 0x{e - a:X} }},\n")
            o.write("]\n")
        print(f"explicit functions   : {len(explicit)} -> {args[2]}")
    print(f"jump tables resolved : {len(tables)} ({unbounded} sized from function bounds)")
    print(f"indirect calls       : {indirect_calls}")
    print(f"unresolved tables    : {len(unresolved)}")
    for u, why in unresolved:
        print(f"  unresolved 0x{u:08X} {why}")


if __name__ == "__main__":
    main()
