#!/usr/bin/env python3
"""Shows disassembly around branch targets and the .pdata function that contains them."""
import bisect, struct, sys, capstone
img = open(sys.argv[1], 'rb').read(); B = 0x82000000
md = capstone.Cs(capstone.CS_ARCH_PPC, capstone.CS_MODE_32 | capstone.CS_MODE_BIG_ENDIAN)
pd = []  # .pdata: (begin, length in bytes)
for o in range(0x821EF400 - B, 0x821EF400 - B + 0x33588, 8):
    b, w = struct.unpack('>II', img[o:o + 8])
    if b: pd.append((b, ((w >> 8) & 0x3FFFFF) * 4))
pd.sort(); starts = [p[0] for p in pd]
def pdata_of(a):
    i = bisect.bisect_right(starts, a) - 1
    return pd[i] if i >= 0 else None
def dis(a, before=3, after=5):
    for i in md.disasm(img[a - B - before * 4:a - B + after * 4], a - before * 4):
        print(f"   {'>' if i.address == a else ' '} {i.address:08X}  {i.mnemonic} {i.op_str}")
for pair in sys.argv[2:]:
    t, s = (int(x, 16) for x in pair.split(':'))
    pt, ps = pdata_of(t), pdata_of(s)
    print(f"target {t:08X}  pdata {pt[0]:08X}+{pt[1]:X}{'' if pt[0] <= t < pt[0]+pt[1] else ' (outside)'}   "
          f"source {s:08X}  pdata {ps[0]:08X}+{ps[1]:X}{'' if ps[0] <= s < ps[0]+ps[1] else ' (outside)'}")
    dis(t); print("   ..."); dis(s, 2, 2)
