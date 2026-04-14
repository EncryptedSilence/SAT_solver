"""Run every implemented analysis on a lin344 variant.

Usage:
    python examples/run_all_checks.py                       # c0 = {1,10,15}
    python examples/run_all_checks.py 1 17 14               # custom c0
    python examples/run_all_checks.py 1 17 14 --rounds 4    # set R ceiling
    python examples/run_all_checks.py 1 17 14 --fast        # skip slow checks
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lin344_variants import build_layer, lin344_bits, unpack  # noqa: E402
from sat_branch.branch import min_weight  # noqa: E402
from sat_branch.encoder import Encoding, add_atmost, build_base  # noqa: E402
from sat_branch.propagation import CipherSpec, min_trail  # noqa: E402
from sat_branch.solver import PySATBackend, make_backend  # noqa: E402
from sat_branch.spn import Column, SPNSpec, min_active_sboxes  # noqa: E402

CELL_BITS = 8
N_CELLS = 16


def _bits_to_int(s: str) -> int:
    v = 0
    for i, c in enumerate(s):
        if c == "1":
            v |= 1 << i
    return v


def _byte_branch(layer, solver: str) -> tuple[int, list[int], list[int]]:
    base = build_base(layer)
    bx = base.fresh_many(N_CELLS)
    by = base.fresh_many(N_CELLS)
    for i in range(N_CELLS):
        bits_x = [base.x_vars[8 * i + j] for j in range(CELL_BITS)]
        bits_y = [base.y_vars[8 * i + j] for j in range(CELL_BITS)]
        for b in bits_x:
            base.clauses.append([-b, bx[i]])
        base.clauses.append([-bx[i]] + bits_x)
        for b in bits_y:
            base.clauses.append([-b, by[i]])
        base.clauses.append([-by[i]] + bits_y)
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


def _timed(label: str, fn):
    t = time.time()
    out = fn()
    dt = time.time() - t
    print(f"  ({dt:.2f}s) {label}")
    return out


def run_all(c0: tuple[int, int, int], solver: str, rounds_max: int,
            include_slow_prop: bool) -> None:
    print(f"\n=== lin344 analysis for c0 = {{{c0[0]}, {c0[1]}, {c0[2]}}} ===\n")
    L = build_layer(c0)

    # 1. Bit-level branch number: min w(dx) + w(dy).
    print("[1] Bit-level branch number (min w(dx)+w(dy))")
    r = _timed("solved", lambda: min_weight(L, objective="sum",
                                             solver=solver))
    dx = _bits_to_int(r.first.input_diff)
    dy = _bits_to_int(r.first.output_diff)
    assert lin344_bits(dx, c0) == dy
    print(f"    B_bit = {r.minimum_weight}   "
          f"w(dx)={bin(dx).count('1')}  w(dy)={bin(dy).count('1')}")
    print(f"    dx_words = {[hex(w) for w in unpack(dx)]}")
    print(f"    dy_words = {[hex(w) for w in unpack(dy)]}")

    # 2. Min input weight (keeps dy free).
    print("\n[2] Minimum input-difference weight")
    r = _timed("solved", lambda: min_weight(L, objective="input",
                                             solver=solver))
    print(f"    min w(dx) = {r.minimum_weight}   "
          f"(for that dx, w(dy) = "
          f"{r.first.output_diff.count('1')})")

    # 3. Min output weight (keeps dx free).
    print("\n[3] Minimum output-difference weight")
    r = _timed("solved", lambda: min_weight(L, objective="output",
                                             solver=solver))
    print(f"    min w(dy) = {r.minimum_weight}   "
          f"(for that dy, w(dx) = "
          f"{r.first.input_diff.count('1')})")

    # 4. Byte-level branch number.
    print("\n[4] Byte-level branch number (min active_bytes(dx)+active_bytes(dy))")
    B_bytes, ain, aout = _timed("solved",
                                 lambda: _byte_branch(L, solver=solver))
    print(f"    B_bytes = {B_bytes}  active_in={ain}  active_out={aout}")

    # 5. Cell-level SPN wide-trail (with teleport fix).
    print("\n[5] Cell-level SPN wide-trail (SubBytes + lin344)")
    spec_spn = SPNSpec(
        n_cells=N_CELLS,
        cell_bits=CELL_BITS,
        columns=[Column(input_cells=list(range(N_CELLS)),
                        output_cells=list(range(N_CELLS)),
                        branch_number=B_bytes)],
    )
    print(f"    {'R':>3} | {'min_active_S':>12} | per-round sizes")
    print(f"    {'-'*3} + {'-'*12} + {'-'*40}")
    for R in range(1, rounds_max + 1):
        res = min_active_sboxes(spec_spn, rounds=R, solver=solver)
        sizes = [len(s) for s in res.trail]
        print(f"    {R:>3} | {res.min_active_sboxes:>12} | {sizes}")

    # 6. Bit-exact multi-round propagation.
    print("\n[6] Bit-exact multi-round propagation")
    spec_prop = CipherSpec(linear_layer=L, cell_bits=CELL_BITS)
    prop_max = rounds_max if include_slow_prop else min(rounds_max, 2)
    print(f"    {'R':>3} | {'min_active_S':>12} | per-round | time")
    print(f"    {'-'*3} + {'-'*12} + {'-'*20} + {'-'*6}")
    for R in range(1, prop_max + 1):
        t = time.time()
        res = min_trail(spec_prop, rounds=R, solver=solver)
        dt = time.time() - t
        print(f"    {R:>3} | {res.min_active_sboxes:>12} | "
              f"{res.active_per_round}  | {dt:.1f}s")
    if not include_slow_prop and rounds_max > prop_max:
        print(f"    (R > {prop_max} skipped; pass --slow to include)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("c0", nargs="*", type=int,
                   help="three rotation amounts (default: 1 10 15)")
    p.add_argument("--rounds", type=int, default=4,
                   help="max rounds for multi-round checks (default 4)")
    p.add_argument("--solver", default="cms",
                   help="SAT backend (cms | pysat | pysat:<engine>)")
    p.add_argument("--slow", action="store_true",
                   help="include slow bit-exact propagation for R>2")
    args = p.parse_args()

    c0 = tuple(args.c0) if args.c0 else (1, 10, 15)
    if len(c0) != 3:
        p.error("c0 must have exactly three integers")

    run_all(c0, solver=args.solver, rounds_max=args.rounds,
            include_slow_prop=args.slow)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
