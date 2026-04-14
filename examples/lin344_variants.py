"""Parametrised lin344 reference: build the 128-bit LinearLayer for any c0.

    dout[0] = din[0] ^ ROTL(din[1], c0[0]) ^ ROTL(din[2], c0[1]) ^ ROTL(din[3], c0[2])
    dout[1] = din[1] ^ ROTL(din[2], c0[0]) ^ ROTL(din[3], c0[1]) ^ ROTL(dout[0], c0[2])
    dout[2] = din[2] ^ ROTL(din[3], c0[0]) ^ ROTL(dout[0], c0[1]) ^ ROTL(dout[1], c0[2])
    dout[3] = din[3] ^ ROTL(dout[0], c0[0]) ^ ROTL(dout[1], c0[1]) ^ ROTL(dout[2], c0[2])
"""
from __future__ import annotations

from typing import Sequence

MASK32 = 0xFFFFFFFF


def rotl32(x: int, s: int) -> int:
    x &= MASK32
    s %= 32
    return ((x << s) | (x >> (32 - s))) & MASK32 if s else x


def lin344_apply(din: list[int], c0: Sequence[int]) -> list[int]:
    d0 = (din[0] ^ rotl32(din[1], c0[0]) ^ rotl32(din[2], c0[1])
          ^ rotl32(din[3], c0[2])) & MASK32
    d1 = (din[1] ^ rotl32(din[2], c0[0]) ^ rotl32(din[3], c0[1])
          ^ rotl32(d0, c0[2])) & MASK32
    d2 = (din[2] ^ rotl32(din[3], c0[0]) ^ rotl32(d0, c0[1])
          ^ rotl32(d1, c0[2])) & MASK32
    d3 = (din[3] ^ rotl32(d0, c0[0]) ^ rotl32(d1, c0[1])
          ^ rotl32(d2, c0[2])) & MASK32
    return [d0, d1, d2, d3]


def pack(words: list[int]) -> int:
    v = 0
    for i, w in enumerate(words):
        v |= (w & MASK32) << (32 * i)
    return v


def unpack(v: int) -> list[int]:
    return [(v >> (32 * i)) & MASK32 for i in range(4)]


def lin344_bits(x128: int, c0: Sequence[int]) -> int:
    return pack(lin344_apply(unpack(x128), c0))


def build_layer(c0: Sequence[int]):
    """Return a 128-bit LinearLayer for lin344 with the given c0."""
    from sat_branch.layer import LinearLayer
    n = 128
    rows = [0] * n
    for j in range(n):
        y = lin344_bits(1 << j, c0)
        for i in range(n):
            if (y >> i) & 1:
                rows[i] |= 1 << j
    return LinearLayer(n=n, rows=rows)
