#!/usr/bin/env python3
"""Dumps the decrypted, decompressed image of a retail XEX2 (normal/LZX compression).
Only for inspecting the code (disassembly); ReXGlue does its own loading.

Usage: xexdump.py default.xex image.bin [path/to/liblzxhelper.so]
"""
import ctypes
import math
import struct
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

RETAIL_KEY = bytes.fromhex("20B185A59D28FDC340583FBB0896BF91")


def aes(key, data, mode):
    d = Cipher(algorithms.AES(key), mode).decryptor()
    return d.update(data) + d.finalize()


def main(xex_path, out_path, helper="/tmp/liblzxhelper.so"):
    d = open(xex_path, "rb").read()
    _, _, pe_off, _, sec_off, nopt = struct.unpack(">4sIIIII", d[:24])
    opts = dict(struct.unpack(">II", d[24 + i * 8:32 + i * 8]) for i in range(nopt))
    ff = opts[0x3FF]
    enc, comp = struct.unpack(">HH", d[ff + 4:ff + 8])
    image_size = struct.unpack(">I", d[sec_off + 4:sec_off + 8])[0]
    session = aes(RETAIL_KEY, d[sec_off + 0x150:sec_off + 0x160], modes.ECB())
    payload = d[pe_off:]
    if enc == 1:
        payload = payload[:len(payload) & ~15]
        payload = aes(session, payload, modes.CBC(b"\0" * 16))
    if comp != 2:
        sys.exit(f"compression type {comp} not handled")

    window_size, block_size = struct.unpack(">II", d[ff + 8:ff + 16])
    chunks, p = bytearray(), 0
    while block_size:
        next_size = struct.unpack(">I", payload[p:p + 4])[0]
        q, end = p + 24, p + block_size
        while q < end:
            n = struct.unpack(">H", payload[q:q + 2])[0]
            q += 2
            if n == 0:
                break
            chunks += payload[q:q + n]
            q += n
        p, block_size = end, next_size

    lib = ctypes.CDLL(helper)
    out = ctypes.create_string_buffer(image_size)
    src = (ctypes.c_ubyte * len(chunks)).from_buffer(chunks)
    r = lib.lzx_decompress(src, ctypes.c_size_t(len(chunks)), out, ctypes.c_size_t(image_size),
                           int(math.log2(window_size)))
    if r != 0:
        sys.exit(f"LZX failed ({r})")
    open(out_path, "wb").write(out.raw)
    print(f"image 0x{image_size:X} bytes -> {out_path} (starts {out.raw[:2]!r})")


if __name__ == "__main__":
    main(*sys.argv[1:])
