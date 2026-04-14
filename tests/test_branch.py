"""End-to-end branch number tests against brute force."""
import random

import pytest

from sat_branch.branch import branch_number
from sat_branch.layer import LinearLayer


def _brute(layer: LinearLayer) -> int:
    n = layer.n
    best = 2 * n + 1
    for x in range(1, 1 << n):
        y = layer.apply(x)
        w = x.bit_count() + y.bit_count()
        if w < best:
            best = w
    return best


def _pysat_available() -> bool:
    try:
        from pysat.solvers import Solver  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _pysat_available(),
                                reason="python-sat not installed")


def test_identity():
    n = 8
    m = [[1 if i == j else 0 for j in range(n)] for i in range(n)]
    L = LinearLayer.from_matrix(m)
    res = branch_number(L, solver="pysat")
    assert res.branch_number == 2
    assert res.input_diff == res.output_diff
    assert res.input_diff.count("1") == 1


def test_random_small_matches_brute():
    random.seed(42)
    for trial in range(3):
        n = 5
        # guarantee non-singular-ish by retry
        for _ in range(10):
            m = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
            L = LinearLayer.from_matrix(m)
            # Skip if a row is all zero (trivial UNSAT on that output)
            if all(any(row) for row in m):
                break
        expected = _brute(L)
        res = branch_number(L, solver="pysat")
        assert res.branch_number == expected
        # Verify witness
        x = int(res.input_diff[::-1], 2)  # bit 0 is leftmost char
        # Actually input_diff[i] corresponds to x_vars[i] which is x_i.
        x = 0
        for i, ch in enumerate(res.input_diff):
            if ch == "1":
                x |= 1 << i
        y = 0
        for i, ch in enumerate(res.output_diff):
            if ch == "1":
                y |= 1 << i
        assert x != 0
        assert L.apply(x) == y
        assert x.bit_count() + y.bit_count() == res.branch_number


def test_rotxor_example():
    # y_i = x_i XOR x_{i+1} XOR x_{i+3} (indices mod 8)
    n = 8
    ops = [
        f"y{i} = x{i} XOR ROTL(x{i}, 1) XOR ROTL(x{i}, 3)"
        for i in range(n)
    ]
    L = LinearLayer.from_operations(ops, n)
    res = branch_number(L, solver="pysat")
    assert res.branch_number == _brute(L)
