"""Multi-round active S-box analysis for SPN ciphers (wide-trail)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .encoder import Encoding, add_atmost
from .solver import PySATBackend, SolverBackend, make_backend


@dataclass
class Column:
    """One parallel linear sub-block of a cipher's linear layer.

    `input_cells` are indices read from the pre-layer state; `output_cells`
    are indices written into the post-layer state. `branch_number` is the
    cell-level branch number (min hw_in + hw_out over non-zero dx).
    """
    input_cells: list[int]
    output_cells: list[int]
    branch_number: int


@dataclass
class SPNSpec:
    n_cells: int
    cell_bits: int = 8
    columns: list[Column] = field(default_factory=list)


@dataclass
class SPNResult:
    rounds: int
    min_active_sboxes: int
    # trail[r] is the list of active cell indices at round r (0..rounds).
    # Active S-boxes are counted over trail[0..rounds-1].
    trail: list[list[int]]


def _column_constraint(enc: Encoding, cells: list[int], B: int
                       ) -> list[list[int]]:
    """CNF for 'all cells zero OR at least B cells active'.

    Uses pysat's sequential-counter atleast encoding gated by a fresh
    indicator z.
    """
    m = len(cells)
    if B <= 1 or m == 0:
        return []
    if B > m:
        return [[-c] for c in cells]

    from pysat.card import CardEnc, EncType  # type: ignore

    before_top = enc.top_var
    cnf = CardEnc.atleast(
        lits=cells, bound=B, top_id=before_top,
        encoding=EncType.seqcounter,
    )
    # Update top_var from any fresh aux vars pysat allocated.
    for cl in cnf.clauses:
        for lit in cl:
            if abs(lit) > enc.top_var:
                enc.top_var = abs(lit)

    z = enc.fresh()
    clauses: list[list[int]] = [[-c, z] for c in cells]
    for cl in cnf.clauses:
        clauses.append([-z] + list(cl))
    return clauses


def _load_into_backend(enc: Encoding, backend: SolverBackend) -> None:
    if isinstance(backend, PySATBackend):
        backend.set_top_var(enc.top_var)
    for lits, rhs in enc.xor_clauses:
        backend.add_xor(lits, rhs)
    for c in enc.clauses:
        backend.add_clause(c)


def _build_base(spec: SPNSpec, rounds: int
                ) -> tuple[Encoding, list[list[int]], list[int]]:
    """Return (base encoding, per-round var lists, objective literals)."""
    enc = Encoding(n=0)
    a: list[list[int]] = [enc.fresh_many(spec.n_cells)
                          for _ in range(rounds + 1)]

    # nz[r] = state at round r is non-zero. Enforce:
    #   nz[r] <-> OR(a[r][*])
    #   nz[r+1] = nz[r]         (bijective S-box + bijective linear layer
    #                            preserve non-zero-ness)
    #   nz[0]   = True          (non-zero input)
    # Together these forbid the "teleport through zero" trail family that
    # the truncated cell-level model otherwise admits.
    nz = [enc.fresh() for _ in range(rounds + 1)]
    for r in range(rounds + 1):
        # Any active cell implies nz[r].
        for c in a[r]:
            enc.clauses.append([-c, nz[r]])
        # nz[r] implies at least one cell is active.
        enc.clauses.append([-nz[r]] + list(a[r]))
    for r in range(rounds):
        enc.clauses.append([-nz[r], nz[r + 1]])
        enc.clauses.append([nz[r], -nz[r + 1]])
    enc.clauses.append([nz[0]])  # non-zero input

    for r in range(rounds):
        for col in spec.columns:
            cells = ([a[r][i] for i in col.input_cells]
                     + [a[r + 1][i] for i in col.output_cells])
            enc.clauses += _column_constraint(enc, cells, col.branch_number)

    obj_lits: list[int] = []
    for r in range(rounds):
        obj_lits.extend(a[r])
    return enc, a, obj_lits


def min_active_sboxes(
    spec: SPNSpec,
    rounds: int,
    solver: str = "cms",
    max_k: Optional[int] = None,
) -> SPNResult:
    """Minimum active S-boxes over `rounds` rounds (differential trail)."""
    if rounds < 1:
        raise ValueError("rounds must be >= 1")
    base, a_vars, obj_lits = _build_base(spec, rounds)
    upper = max_k if max_k is not None else len(obj_lits)

    for k in range(1, upper + 1):
        enc_iter = Encoding(
            n=base.n,
            xor_clauses=list(base.xor_clauses),
            clauses=list(base.clauses),
            top_var=base.top_var,
        )
        enc_iter.clauses += add_atmost(enc_iter, obj_lits, k)

        backend = make_backend(solver)
        _load_into_backend(enc_iter, backend)
        if not backend.solve():
            continue

        m = backend.model()
        val = {abs(l): l > 0 for l in m}
        trail = []
        for r in range(rounds + 1):
            trail.append([i for i in range(spec.n_cells)
                          if val.get(a_vars[r][i], False)])
        return SPNResult(rounds=rounds, min_active_sboxes=k, trail=trail)

    raise RuntimeError(
        f"no trail found with <= {upper} active S-boxes over "
        f"{rounds} rounds"
    )


def aes_spn() -> SPNSpec:
    """AES ShiftRows+MixColumns column structure with B = 5.

    State indexing: cell(row, col) = 4*col + row.
    ShiftRows shifts row i left by i cells, so MC column j reads cells
    {(i, (j+i) mod 4) : i = 0..3} of the pre-ShiftRows state.
    """
    cols = []
    for j in range(4):
        inp = [4 * ((j + i) % 4) + i for i in range(4)]
        out = [4 * j + i for i in range(4)]
        cols.append(Column(input_cells=inp, output_cells=out,
                           branch_number=5))
    return SPNSpec(n_cells=16, cell_bits=8, columns=cols)
