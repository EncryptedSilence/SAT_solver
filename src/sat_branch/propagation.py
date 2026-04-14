"""Bit-exact multi-round differential trail SAT model.

Variables (per round `r`):
  x[r]  — bit-level difference entering the S-box of round r (128 bits).
  y[r]  — bit-level difference leaving the S-box of round r.
  x[r+1] = L(y[r])  enforced exactly with XOR clauses.

S-box model: bijective. Byte-activity is preserved:
  byte_active(x[r][byte i]) iff byte_active(y[r][byte i]).
Individual bits of y[r] are otherwise unconstrained — any non-zero δ_in can
produce any non-zero δ_out under this model. (DDT-aware modelling is a
future extension.)

This rules out the "teleport through zero" artefact of the truncated cell-
level model because the linear layer is bit-exact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .encoder import Encoding, add_atmost
from .layer import LinearLayer
from .solver import PySATBackend, SolverBackend, make_backend


@dataclass
class CipherSpec:
    linear_layer: LinearLayer
    cell_bits: int = 8

    @property
    def n(self) -> int:
        return self.linear_layer.n

    @property
    def n_cells(self) -> int:
        if self.linear_layer.n % self.cell_bits != 0:
            raise ValueError("cell_bits does not divide state size")
        return self.linear_layer.n // self.cell_bits


@dataclass
class TrailResult:
    rounds: int
    min_active_sboxes: int
    # Bit-level states, LSB-index-0 on the left of each string.
    x_states: list[str]          # length rounds+1
    y_states: list[str]          # length rounds
    active_bytes_x: list[list[int]]  # per-round active-byte indices
    active_per_round: list[int]  # #active S-boxes per round (len rounds)


def _bind_byte_activity(enc: Encoding, bits: list[int],
                         indicators: list[int], cell_bits: int) -> None:
    for i, b in enumerate(indicators):
        byte_bits = bits[cell_bits * i: cell_bits * (i + 1)]
        for bit in byte_bits:
            enc.clauses.append([-bit, b])
        enc.clauses.append([-b] + byte_bits)


def _load(enc: Encoding, backend: SolverBackend) -> None:
    if isinstance(backend, PySATBackend):
        backend.set_top_var(enc.top_var)
    for lits, rhs in enc.xor_clauses:
        backend.add_xor(lits, rhs)
    for c in enc.clauses:
        backend.add_clause(c)


def _bits_to_string(model_val: dict[int, bool], vars_: list[int]) -> str:
    return "".join("1" if model_val.get(v, False) else "0" for v in vars_)


def min_trail(
    spec: CipherSpec,
    rounds: int,
    solver: str = "cms",
    max_k: Optional[int] = None,
) -> TrailResult:
    """Minimum active S-boxes with bit-exact linear propagation."""
    if rounds < 1:
        raise ValueError("rounds must be >= 1")
    n = spec.n
    nb = spec.n_cells
    L = spec.linear_layer

    base = Encoding(n=0)

    # Variables: x[0..R], y[0..R-1], bx[0..R], by[0..R-1].
    x = [base.fresh_many(n) for _ in range(rounds + 1)]
    y = [base.fresh_many(n) for _ in range(rounds)]
    bx = [base.fresh_many(nb) for _ in range(rounds + 1)]
    by = [base.fresh_many(nb) for _ in range(rounds)]

    for r in range(rounds + 1):
        _bind_byte_activity(base, x[r], bx[r], spec.cell_bits)
    for r in range(rounds):
        _bind_byte_activity(base, y[r], by[r], spec.cell_bits)

    # S-box: byte activity of x[r] matches byte activity of y[r].
    for r in range(rounds):
        for i in range(nb):
            base.clauses.append([-bx[r][i], by[r][i]])
            base.clauses.append([-by[r][i], bx[r][i]])

    # Linear layer: x[r+1] = L(y[r])  (XOR-exact).
    for r in range(rounds):
        for i in range(n):
            deps = L.dependencies(i)
            lits = [x[r + 1][i]] + [y[r][j] for j in deps]
            base.xor_clauses.append((lits, False))

    # Non-zero input.
    base.clauses.append(list(x[0]))

    # Objective: total active S-boxes across rounds 0..R-1.
    obj_lits: list[int] = []
    for r in range(rounds):
        obj_lits.extend(bx[r])

    upper = max_k if max_k is not None else rounds * nb

    for k in range(1, upper + 1):
        enc_iter = Encoding(
            n=0,
            xor_clauses=list(base.xor_clauses),
            clauses=list(base.clauses),
            top_var=base.top_var,
        )
        enc_iter.clauses += add_atmost(enc_iter, obj_lits, k)

        backend = make_backend(solver)
        _load(enc_iter, backend)
        if not backend.solve():
            continue

        m = backend.model()
        val = {abs(l): l > 0 for l in m}
        x_str = [_bits_to_string(val, x[r]) for r in range(rounds + 1)]
        y_str = [_bits_to_string(val, y[r]) for r in range(rounds)]
        active_bytes = [
            [i for i in range(nb) if val.get(bx[r][i], False)]
            for r in range(rounds + 1)
        ]
        per_round = [len(active_bytes[r]) for r in range(rounds)]
        return TrailResult(
            rounds=rounds,
            min_active_sboxes=k,
            x_states=x_str,
            y_states=y_str,
            active_bytes_x=active_bytes,
            active_per_round=per_round,
        )

    raise RuntimeError(
        f"no trail found with <= {upper} active S-boxes over {rounds} rounds"
    )
