"""Tests for minimum-weight differential search."""
import random

import pytest

from sat_branch.branch import min_weight
from sat_branch.layer import LinearLayer


def _pysat_available() -> bool:
    try:
        from pysat.solvers import Solver  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _pysat_available(),
                                reason="python-sat not installed")


def _brute_min(layer: LinearLayer, objective: str) -> tuple[int, set[int]]:
    """Return (min weight, set of dx values achieving it)."""
    n = layer.n
    best = 10 ** 9
    witnesses: set[int] = set()
    for x in range(1, 1 << n):
        y = layer.apply(x)
        if objective == "input":
            w = x.bit_count()
        elif objective == "output":
            w = y.bit_count()
        else:
            w = x.bit_count() + y.bit_count()
        if w < best:
            best = w
            witnesses = {x}
        elif w == best:
            witnesses.add(x)
    return best, witnesses


def _dx_int(s: str) -> int:
    v = 0
    for i, ch in enumerate(s):
        if ch == "1":
            v |= 1 << i
    return v


@pytest.mark.parametrize("objective", ["sum", "input", "output"])
def test_random_small_matches_brute(objective):
    random.seed(objective.__hash__() & 0xFFFF)
    n = 5
    for _ in range(20):
        m = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
        if not all(any(row) for row in m):
            continue
        L = LinearLayer.from_matrix(m)
        expected_w, expected_dxs = _brute_min(L, objective)
        res = min_weight(L, objective=objective, solver="pysat")
        assert res.minimum_weight == expected_w
        dx = _dx_int(res.first.input_diff)
        assert dx in expected_dxs
        # Verify layer consistency.
        dy = _dx_int(res.first.output_diff)
        assert L.apply(dx) == dy


def test_enumerate_identity():
    n = 6
    m = [[1 if i == j else 0 for j in range(n)] for i in range(n)]
    L = LinearLayer.from_matrix(m)
    res = min_weight(L, objective="input", solver="pysat",
                     enumerate_all=True)
    assert res.minimum_weight == 1
    # n distinct single-bit inputs
    dxs = {_dx_int(d.input_diff) for d in res.differentials}
    assert dxs == {1 << i for i in range(n)}


def test_enumerate_sum_matches_brute():
    random.seed(7)
    n = 4
    m = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
    while not all(any(row) for row in m):
        m = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
    L = LinearLayer.from_matrix(m)
    expected_w, expected_dxs = _brute_min(L, "sum")
    res = min_weight(L, objective="sum", solver="pysat", enumerate_all=True)
    assert res.minimum_weight == expected_w
    dxs = {_dx_int(d.input_diff) for d in res.differentials}
    assert dxs == expected_dxs
