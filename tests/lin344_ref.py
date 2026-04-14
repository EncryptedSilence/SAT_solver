"""Reference Python implementation of the Qalqan lin344 linear layer.

Matches the C source:

    #define ROTL(x,s) ((x<<s)|(x>>(32-s)))
    const int c0[3] = { 1, 10, 15 };
    void lin344(uint32_t* din, uint32_t* dout) {
        dout[0] = din[0] ^ ROTL(din[1], c0[0]) ^ ROTL(din[2], c0[1]) ^ ROTL(din[3], c0[2]);
        dout[1] = din[1] ^ ROTL(din[2], c0[0]) ^ ROTL(din[3], c0[1]) ^ ROTL(dout[0], c0[2]);
        dout[2] = din[2] ^ ROTL(din[3], c0[0]) ^ ROTL(dout[0], c0[1]) ^ ROTL(dout[1], c0[2]);
        dout[3] = din[3] ^ ROTL(dout[0], c0[0]) ^ ROTL(dout[1], c0[1]) ^ ROTL(dout[2], c0[2]);
    }
"""
from __future__ import annotations

MASK32 = 0xFFFFFFFF
C0 = (1, 10, 15)


def rotl32(x: int, s: int) -> int:
    x &= MASK32
    s %= 32
    return ((x << s) | (x >> (32 - s))) & MASK32 if s else x


def lin344(din: list[int]) -> list[int]:
    d0 = (din[0] ^ rotl32(din[1], C0[0]) ^ rotl32(din[2], C0[1])
          ^ rotl32(din[3], C0[2])) & MASK32
    d1 = (din[1] ^ rotl32(din[2], C0[0]) ^ rotl32(din[3], C0[1])
          ^ rotl32(d0, C0[2])) & MASK32
    d2 = (din[2] ^ rotl32(din[3], C0[0]) ^ rotl32(d0, C0[1])
          ^ rotl32(d1, C0[2])) & MASK32
    d3 = (din[3] ^ rotl32(d0, C0[0]) ^ rotl32(d1, C0[1])
          ^ rotl32(d2, C0[2])) & MASK32
    return [d0, d1, d2, d3]


def pack(words: list[int]) -> int:
    """Pack 4 x 32-bit words into a single 128-bit int. Word 0 is in bits 0..31."""
    v = 0
    for i, w in enumerate(words):
        v |= (w & MASK32) << (32 * i)
    return v


def unpack(v: int) -> list[int]:
    return [(v >> (32 * i)) & MASK32 for i in range(4)]


def lin344_bits(x128: int) -> int:
    """Apply lin344 to a packed 128-bit integer."""
    return pack(lin344(unpack(x128)))


def build_layer():
    """Build the 128x128 LinearLayer for lin344 by probing unit vectors."""
    from sat_branch.layer import LinearLayer

    n = 128
    rows = [0] * n
    for j in range(n):
        y = lin344_bits(1 << j)
        # y has bit i set iff y_i depends on x_j
        for i in range(n):
            if (y >> i) & 1:
                rows[i] |= 1 << j
    return LinearLayer(n=n, rows=rows)
