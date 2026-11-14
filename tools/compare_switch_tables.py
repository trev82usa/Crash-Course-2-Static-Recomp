#!/usr/bin/env python3
"""Compares the jump tables ReXGlue emitted (parsed from generated/*.cpp) with
cc2_switch_tables.toml (keyed at the bounds check), matching each old table to the
first bctr after its address. Prints a summary of agreements/differences.
Usage: compare_switch_tables.py image.bin cc2_switch_tables.toml generated/default"""
import glob, re, struct, sys, tomllib
img = open(sys.argv[1], 'rb').read(); B = 0x82000000
w = lambda a: struct.unpack('>I', img[a-B:a-B+4])[0]
old = {}
for s in tomllib.load(open(sys.argv[2], 'rb'))['switch_tables']:
    a = s['address']
    for k in range(40):
        if w(a + 4*k) == 0x4E800420: old[a + 4*k] = s['labels']; break
gen = {}
for f in glob.glob(sys.argv[3] + '/*recomp*.cpp'):
    addr = None; cur = None
    for line in open(f):
        m = re.match(r'(?:DEFINE_REX_FUNC\(sub_|loc_)([0-9A-F]{8})', line)
        if m: addr = int(m.group(1), 16); continue
        if line.startswith('\t// ') and addr is not None and re.match(r'\t// [a-z]', line):
            ia = addr; addr += 4
            if line.startswith('\t// bctr'): cur = (ia, [])
            continue
        if cur and line.startswith('\tswitch ('): continue
        if cur:
            m = re.match(r'\t\tgoto loc_([0-9A-F]+);|\t\t(sub_[0-9A-F]+)\(ctx', line)
            if m: cur[1].append(int(m.group(1), 16) if m.group(1) else int(m.group(2)[4:], 16)); continue
            if line.startswith('\tdefault:') or line.startswith('\tREX_CALL_INDIRECT'):
                if cur[1]: gen[cur[0]] = cur[1]
                cur = None
bad = [a for a in gen if w(a) != 0x4E800420]
print(f'generated switches: {len(gen)} (address check failed for {len(bad)})')
print(f'old tables matched to a bctr: {len(old)}')
same = [a for a in old if gen.get(a) == old[a]]
diff = [a for a in old if a in gen and gen[a] != old[a]]
missing = [a for a in old if a not in gen]
print(f'identical: {len(same)}, different: {len(diff)}, old-only: {len(missing)}, rexglue-only: {len(set(gen)-set(old))}')
for a in diff[:15]:
    print(f'  0x{a:08X}: old {len(old[a])} cases, rexglue {len(gen[a])}; first diff at case',
          next((i for i,(x,y) in enumerate(zip(old[a],gen[a])) if x!=y), min(len(old[a]),len(gen[a]))))
for a in missing[:5]: print(f'  old-only 0x{a:08X} ({len(old[a])} cases)')
