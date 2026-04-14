"""Minimum-weight differential search (branch number is the `sum` variant)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .encoder import Encoding, add_atmost, build_base
from .layer import LinearLayer
from .solver import PySATBackend, SolverBackend, make_backend

Objective = Literal["input", "output", "sum"]


@dataclass
class Differential:
    weight: int
    input_diff: str
    output_diff: str


@dataclass
class MinWeightResult:
    objective: Objective
    minimum_weight: int
    differentials: list[Differential]

    @property
    def first(self) -> Differential:
        return self.differentials[0]


# Back-compat alias for the n=sum case.
@dataclass
class BranchResult:
    branch_number: int
    input_diff: str
    output_diff: str


def _load_into_backend(enc: Encoding, backend: SolverBackend) -> None:
    if isinstance(backend, PySATBackend):
        backend.set_top_var(enc.top_var)
    for lits, rhs in enc.xor_clauses:
        backend.add_xor(lits, rhs)
    for c in enc.clauses:
        backend.add_clause(c)


def _extract_bits(model: list[int], vars_: list[int]) -> str:
    val = {abs(l): l > 0 for l in model}
    return "".join("1" if val.get(v, False) else "0" for v in vars_)


def _diff_to_int(bits: str) -> int:
    x = 0
    for i, ch in enumerate(bits):
        if ch == "1":
            x |= 1 << i
    return x


def _select_lits(enc: Encoding, objective: Objective) -> list[int]:
    if objective == "input":
        return list(enc.x_vars)
    if objective == "output":
        return list(enc.y_vars)
    if objective == "sum":
        return list(enc.x_vars) + list(enc.y_vars)
    raise ValueError(f"unknown objective: {objective}")


def _default_upper(objective: Objective, n: int) -> int:
    return 2 * n if objective == "sum" else n


def min_weight(
    layer: LinearLayer,
    *,
    objective: Objective = "sum",
    solver: str = "cms",
    max_k: Optional[int] = None,
    fix_first: bool = False,
    enumerate_all: bool = False,
) -> MinWeightResult:
    """Minimise weight of (dx, dy, or dx+dy) over non-zero dx with dy = L(dx).

    If `enumerate_all=True`, return every differential attaining the optimum.
    """
    base = build_base(layer)
    if fix_first:
        base.clauses.append([base.x_vars[0]])

    lits = _select_lits(base, objective)
    upper = max_k if max_k is not None else _default_upper(objective, layer.n)

    for k in range(0 if objective != "sum" else 1, upper + 1):
        # Special-case: sum must be >= 1 (dx != 0 forces w(dx) >= 1); for
        # input objective same holds; for output objective 0 is possible only
        # if L is singular, which we still want to report.
        if objective == "input" and k == 0:
            continue

        enc = Encoding(
            n=base.n,
            x_vars=list(base.x_vars),
            y_vars=list(base.y_vars),
            xor_clauses=list(base.xor_clauses),
            clauses=list(base.clauses),
            top_var=base.top_var,
        )
        enc.clauses += add_atmost(enc, lits, k)

        backend = make_backend(solver)
        _load_into_backend(enc, backend)
        if not backend.solve():
            continue

        # Found optimum at weight k.
        found: list[Differential] = []
        while True:
            m = backend.model()
            dx = _extract_bits(m, base.x_vars)
            dy = _extract_bits(m, base.y_vars)
            w = dx.count("1") + dy.count("1") if objective == "sum" else (
                dx.count("1") if objective == "input" else dy.count("1")
            )
            found.append(Differential(weight=w, input_diff=dx, output_diff=dy))
            if not enumerate_all:
                break
            # Block this x assignment and resolve at same k.
            block = []
            for i, ch in enumerate(dx):
                v = base.x_vars[i]
                block.append(-v if ch == "1" else v)
            backend.add_clause(block)
            if not backend.solve():
                break

        return MinWeightResult(
            objective=objective,
            minimum_weight=k,
            differentials=found,
        )

    raise RuntimeError(
        f"no differential found within weight <= {upper} "
        f"for objective {objective!r}"
    )


def branch_number(
    layer: LinearLayer,
    solver: str = "cms",
    max_k: Optional[int] = None,
    fix_first: bool = False,
) -> BranchResult:
    """Compute the branch number B = min w(dx) + w(L(dx)) over dx != 0."""
    r = min_weight(
        layer,
        objective="sum",
        solver=solver,
        max_k=max_k,
        fix_first=fix_first,
    )
    d = r.first
    return BranchResult(
        branch_number=r.minimum_weight,
        input_diff=d.input_diff,
        output_diff=d.output_diff,
    )
