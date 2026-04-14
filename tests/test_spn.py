"""Active S-box (wide-trail) SAT tests."""
import os

import pytest

from sat_branch.spn import (
    Column,
    SPNSpec,
    aes_spn,
    min_active_sboxes,
)


def _pysat_available() -> bool:
    try:
        from pysat.solvers import Solver  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _pysat_available(),
                                reason="python-sat not installed")


def _column_ok(cells_active_in: list[int], cells_active_out: list[int],
               B: int) -> bool:
    total = len(cells_active_in) + len(cells_active_out)
    return total == 0 or total >= B


def _validate_trail(spec: SPNSpec, rounds: int, trail: list[list[int]]) -> None:
    # Every per-round column must satisfy "all zero or >= B".
    for r in range(rounds):
        state_in = set(trail[r])
        state_out = set(trail[r + 1])
        for col in spec.columns:
            ai = [c for c in col.input_cells if c in state_in]
            ao = [c for c in col.output_cells if c in state_out]
            assert _column_ok(ai, ao, col.branch_number), \
                f"round {r} column violated: in={ai} out={ao} B={col.branch_number}"
    # Round 0 must be non-zero.
    assert trail[0], "round 0 has no active cells"


def test_aes_1_round():
    spec = aes_spn()
    r = min_active_sboxes(spec, rounds=1, solver="pysat")
    assert r.min_active_sboxes == 1
    _validate_trail(spec, 1, r.trail)


def test_aes_2_rounds():
    spec = aes_spn()
    r = min_active_sboxes(spec, rounds=2, solver="pysat")
    assert r.min_active_sboxes == 5
    _validate_trail(spec, 2, r.trail)


def test_aes_3_rounds():
    spec = aes_spn()
    r = min_active_sboxes(spec, rounds=3, solver="pysat")
    assert r.min_active_sboxes == 9
    _validate_trail(spec, 3, r.trail)


@pytest.mark.skipif(
    os.environ.get("SAT_BRANCH_RUN_SLOW") != "1",
    reason="slow SAT solve; set SAT_BRANCH_RUN_SLOW=1",
)
def test_aes_4_rounds():
    spec = aes_spn()
    r = min_active_sboxes(spec, rounds=4, solver="pysat")
    assert r.min_active_sboxes == 25
    _validate_trail(spec, 4, r.trail)


def test_trivial_two_cell_b2_no_teleport():
    # Single column with 2 cells, B=2. With nz-preservation forbidding
    # zero-state teleport, every round must have >= 1 active cell, so
    # the minimum grows linearly: R active S-boxes over R rounds.
    spec = SPNSpec(
        n_cells=2,
        cell_bits=1,
        columns=[Column(input_cells=[0, 1], output_cells=[0, 1],
                        branch_number=2)],
    )
    for R in (1, 2, 3):
        r = min_active_sboxes(spec, rounds=R, solver="pysat")
        assert r.min_active_sboxes == R, (R, r)
        _validate_trail(spec, R, r.trail)
        # No round may be empty.
        for rnd_state in r.trail[:R]:
            assert rnd_state, f"empty active set in round of R={R}"
