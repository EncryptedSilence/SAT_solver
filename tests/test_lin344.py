"""Tests for the Qalqan lin344 linear layer."""
from __future__ import annotations

import os
import random

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from lin344_ref import build_layer, lin344_bits, unpack  # noqa: E402


def test_linearity_random():
    random.seed(0)
    for _ in range(50):
        a = random.getrandbits(128)
        b = random.getrandbits(128)
        assert lin344_bits(a ^ b) == lin344_bits(a) ^ lin344_bits(b)


def test_zero_fixed_point():
    assert lin344_bits(0) == 0


def test_matrix_matches_direct():
    """The 128x128 matrix we build must reproduce lin344 on random inputs."""
    random.seed(1)
    L = build_layer()
    for _ in range(20):
        x = random.getrandbits(128)
        assert L.apply(x) == lin344_bits(x), hex(x)


def test_single_bit_propagation():
    """Probing bit j of input: output must equal applying lin344 to 1<<j."""
    L = build_layer()
    for j in (0, 1, 31, 32, 63, 64, 95, 96, 127):
        x = 1 << j
        assert L.apply(x) == lin344_bits(x)


def _cms_available() -> bool:
    try:
        import pycryptosat  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    os.environ.get("SAT_BRANCH_RUN_SLOW") != "1" or not _cms_available(),
    reason="slow SAT solve; set SAT_BRANCH_RUN_SLOW=1 and install pycryptosat",
)
def test_branch_number_solve():
    """Compute the branch number via SAT. Opt-in (slow)."""
    from sat_branch.branch import branch_number

    L = build_layer()
    res = branch_number(L, solver="cms")
    # Sanity: must be at least 2 (non-trivial) and we check the witness.
    assert res.branch_number >= 2
    x = 0
    for i, ch in enumerate(res.input_diff):
        if ch == "1":
            x |= 1 << i
    y = 0
    for i, ch in enumerate(res.output_diff):
        if ch == "1":
            y |= 1 << i
    assert x != 0
    assert lin344_bits(x) == y
    assert x.bit_count() + y.bit_count() == res.branch_number
    print(f"lin344 branch number = {res.branch_number}")
    print(f"  dx = {[hex(w) for w in unpack(x)]}")
    print(f"  dy = {[hex(w) for w in unpack(y)]}")
