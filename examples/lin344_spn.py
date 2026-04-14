"""Wide-trail analysis of an SPN that uses lin344 as its linear layer.

Pipeline:
  1. Build the bit-level LinearLayer for lin344 (128 bits).
  2. Compute its byte-level branch number B_bytes by adding byte-activity
     indicator variables on top of the existing XOR encoding and minimising
     the sum of indicators.
  3. Feed B_bytes into SPNSpec (one full-state column) and run
     min_active_sboxes for a range of round counts.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lin344_ref import build_layer  # noqa: E402
from sat_branch.encoder import Encoding, add_atmost, build_base  # noqa: E402
from sat_branch.solver import make_backend, PySATBackend  # noqa: E402
from sat_branch.spn import (  # noqa: E402
    Column, SPNSpec, min_active_sboxes,
)

CELL_BITS = 8
N_CELLS = 16


def byte_branch_number(layer, solver="cms") -> tuple[int, list[int], list[int]]:
    """Return (B_bytes, active_input_bytes, active_output_bytes).

    Encodes: y = L(x), x != 0, byte-activity indicators, minimise
    sum of byte indicators over input+output.
    """
    base = build_base(layer)

    # Allocate byte indicators for x and y.
    bx = base.fresh_many(N_CELLS)
    by = base.fresh_many(N_CELLS)

    # bx[i] iff any of the 8 bits of input byte i is active.
    for i in range(N_CELLS):
        bits = [base.x_vars[8 * i + j] for j in range(CELL_BITS)]
        # bit -> bx[i]
        for b in bits:
            base.clauses.append([-b, bx[i]])
        # bx[i] -> OR(bits)
        base.clauses.append([-bx[i]] + bits)

    for i in range(N_CELLS):
        bits = [base.y_vars[8 * i + j] for j in range(CELL_BITS)]
        for b in bits:
            base.clauses.append([-b, by[i]])
        base.clauses.append([-by[i]] + bits)

    obj = bx + by

    for k in range(2, 2 * N_CELLS + 1):
        enc_iter = Encoding(
            n=base.n,
            x_vars=list(base.x_vars),
            y_vars=list(base.y_vars),
            xor_clauses=list(base.xor_clauses),
            clauses=list(base.clauses),
            top_var=base.top_var,
        )
        enc_iter.clauses += add_atmost(enc_iter, obj, k)

        backend = make_backend(solver)
        if isinstance(backend, PySATBackend):
            backend.set_top_var(enc_iter.top_var)
        for lits, rhs in enc_iter.xor_clauses:
            backend.add_xor(lits, rhs)
        for c in enc_iter.clauses:
            backend.add_clause(c)

        if backend.solve():
            model = backend.model()
            val = {abs(l): l > 0 for l in model}
            ain = [i for i in range(N_CELLS) if val.get(bx[i], False)]
            aout = [i for i in range(N_CELLS) if val.get(by[i], False)]
            return k, ain, aout

    raise RuntimeError("no byte-level differential found")


def main() -> int:
    L = build_layer()
    print("Computing byte-level branch number of lin344...")
    B, ain, aout = byte_branch_number(L, solver="cms")
    print(f"  B_bytes = {B}")
    print(f"  active input bytes  = {ain}")
    print(f"  active output bytes = {aout}")

    spec = SPNSpec(
        n_cells=N_CELLS,
        cell_bits=CELL_BITS,
        columns=[Column(input_cells=list(range(N_CELLS)),
                        output_cells=list(range(N_CELLS)),
                        branch_number=B)],
    )

    print()
    print("Wide-trail minimum active S-boxes for SPN(lin344, SBox8x8):")
    for R in (1, 2, 3, 4, 5, 8):
        res = min_active_sboxes(spec, rounds=R, solver="cms")
        print(f"  R={R:>2}  min_active_sboxes = {res.min_active_sboxes:>3}"
              f"   trail sizes = {[len(s) for s in res.trail]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
