"""Tests for bit-exact multi-round propagation."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from sat_branch.layer import LinearLayer
from sat_branch.propagation import CipherSpec, min_trail

sys.path.insert(0, str(Path(__file__).parent))


def _pysat_available() -> bool:
    try:
        from pysat.solvers import Solver  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _pysat_available(),
                                reason="python-sat not installed")


def _identity_layer(n: int) -> LinearLayer:
    m = [[1 if i == j else 0 for j in range(n)] for i in range(n)]
    return LinearLayer.from_matrix(m)


def test_identity_16bit_2cells_1round():
    # State = 16 bits, 2 bytes, identity linear layer.
    # R=1: min active = 1 (single byte differential).
    L = _identity_layer(16)
    spec = CipherSpec(linear_layer=L, cell_bits=8)
    r = min_trail(spec, rounds=1, solver="pysat")
    assert r.min_active_sboxes == 1
    assert r.active_per_round == [1]


def test_identity_16bit_no_teleport():
    # Identity linear layer has byte-branch-number 2 (per byte: 1+1),
    # so 2 rounds must have 2 active S-boxes (1 per round), not less.
    L = _identity_layer(16)
    spec = CipherSpec(linear_layer=L, cell_bits=8)
    r = min_trail(spec, rounds=3, solver="pysat")
    # Can't teleport: every round preserves non-zero byte count >= 1.
    assert r.min_active_sboxes == 3
    assert r.active_per_round == [1, 1, 1]


def test_linear_propagation_bit_exact():
    # Verify x[r+1] actually equals L(y[r]) for a small example.
    # Use a tiny 8-bit layer where y[r] is a single known pattern.
    import random
    random.seed(4)
    n = 8
    m = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
    while not all(any(row) for row in m):
        m = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
    L = LinearLayer.from_matrix(m)
    spec = CipherSpec(linear_layer=L, cell_bits=4)  # 2 cells
    r = min_trail(spec, rounds=2, solver="pysat")

    # Check consistency: for each round r, x[r+1] = L(y[r]).
    for rr in range(2):
        y_bits = r.y_states[rr]
        y_int = 0
        for i, c in enumerate(y_bits):
            if c == "1":
                y_int |= 1 << i
        expected = L.apply(y_int)
        x_next = r.x_states[rr + 1]
        actual = 0
        for i, c in enumerate(x_next):
            if c == "1":
                actual |= 1 << i
        assert actual == expected, (rr, hex(y_int), hex(expected),
                                     hex(actual))

    # Also: byte activity of x matches y (bijective S-box).
    for rr in range(2):
        for i in range(spec.n_cells):
            x_byte = r.x_states[rr][spec.cell_bits * i:
                                     spec.cell_bits * (i + 1)]
            y_byte = r.y_states[rr][spec.cell_bits * i:
                                     spec.cell_bits * (i + 1)]
            assert (x_byte.count("1") > 0) == (y_byte.count("1") > 0)


@pytest.mark.skipif(
    os.environ.get("SAT_BRANCH_RUN_SLOW") != "1",
    reason="slow SAT solve; set SAT_BRANCH_RUN_SLOW=1",
)
def test_lin344_r2_matches_byte_branch():
    from lin344_ref import build_layer
    L = build_layer()
    spec = CipherSpec(linear_layer=L, cell_bits=8)
    r = min_trail(spec, rounds=2, solver="cms")
    # Byte-level branch number of lin344 is 6; 2-round min must be >= 6
    # and a single-input-byte trail achieves 6 (1 active in round 0 + 5
    # active in round 1 whose bytes come from L applied to that 1-byte diff).
    assert r.min_active_sboxes == 6
