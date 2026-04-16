"""Sweep cell-level SPN wide-trail bounds over many lin344 c0 triples.

Usage:
    python examples/sweep_c0.py                              # uses examples/c0.txt
    python examples/sweep_c0.py --file my_c0.txt --rounds 2 3 4 5
    python examples/sweep_c0.py --solver pysat --sort R4
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lin344_variants import build_layer  # noqa: E402
from sat_branch.encoder import Encoding, add_atmost, build_base  # noqa: E402
from sat_branch.solver import PySATBackend, make_backend  # noqa: E402
from sat_branch.spn import Column, SPNSpec, min_active_sboxes  # noqa: E402

CELL_BITS = 8
N_CELLS = 16


def parse_c0_file(path: Path) -> list[tuple[int, int, int]]:
    """One triple per line ('a b c' or 'a, b, c'); comments start with '#'."""
    seen: set[tuple[int, int, int]] = set()
    out: list[tuple[int, int, int]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip().replace(",", " ")
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"bad line {raw!r}: expected 3 integers")
        t = (int(parts[0]), int(parts[1]), int(parts[2]))
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def byte_branch_number(layer, solver: str) -> int:
    """Cell-level (byte) branch number computed via SAT on the bit-level
    layer plus byte-activity indicators."""
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
            return k
    raise RuntimeError("no byte-level differential found")


def spn_sweep(c0: tuple[int, int, int], rounds_list: list[int],
              solver: str) -> dict:
    L = build_layer(c0)
    B = byte_branch_number(L, solver)
    spec = SPNSpec(
        n_cells=N_CELLS,
        cell_bits=CELL_BITS,
        columns=[Column(input_cells=list(range(N_CELLS)),
                        output_cells=list(range(N_CELLS)),
                        branch_number=B)],
    )
    by_round = {}
    for R in rounds_list:
        res = min_active_sboxes(spec, rounds=R, solver=solver)
        by_round[R] = res.min_active_sboxes
    return {"c0": c0, "B_bytes": B, "rounds": by_round}


def _format_c0(c0: tuple[int, int, int]) -> str:
    return f"{{{c0[0]:>2}, {c0[1]:>2}, {c0[2]:>2}}}"


def _sort_key(row: dict, primary: str, rounds_list: list[int]):
    """Highest is best. Primary key is chosen round; tiebreak by descending
    R=max, then B_bytes."""
    rounds_sorted = sorted(rounds_list, reverse=True)
    if primary.startswith("R"):
        primary_r = int(primary[1:])
    else:
        primary_r = rounds_sorted[0]
    keys = [row["rounds"].get(primary_r, 0)]
    for R in rounds_sorted:
        if R != primary_r:
            keys.append(row["rounds"].get(R, 0))
    keys.append(row["B_bytes"])
    return tuple(keys)


def print_table(rows: list[dict], rounds_list: list[int],
                primary_sort: str) -> None:
    if not rows:
        print("(no rows — nothing to print)")
        return
    rows_sorted = sorted(rows,
                         key=lambda r: _sort_key(r, primary_sort, rounds_list),
                         reverse=True)
    best_key = _sort_key(rows_sorted[0], primary_sort, rounds_list)

    header = f"{'c0':>14}  {'B_bytes':>7}"
    for R in rounds_list:
        header += f"  {'R=' + str(R):>5}"
    header += "   note"
    print(header)
    print("-" * len(header))

    for row in rows_sorted:
        line = f"{_format_c0(row['c0']):>14}  {row['B_bytes']:>7}"
        for R in rounds_list:
            line += f"  {row['rounds'].get(R, '-'):>5}"
        mark = ""
        if _sort_key(row, primary_sort, rounds_list) == best_key:
            mark = "  <-- BEST"
        line += mark
        print(line)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", default=str(Path(__file__).parent / "c0.txt"),
                   help="path to c0 list (one triple per line)")
    p.add_argument("--rounds", type=int, nargs="+", default=[2, 3, 4],
                   help="round counts to evaluate (default 2 3 4)")
    p.add_argument("--solver", default="cms",
                   help="SAT backend")
    p.add_argument("--sort", default=None,
                   help="primary sort key: 'R4', 'R3', ... (default: largest R)")
    args = p.parse_args()

    c0_list = parse_c0_file(Path(args.file))
    primary_sort = args.sort or f"R{max(args.rounds)}"

    print(f"Evaluating {len(c0_list)} c0 triples, rounds={args.rounds}, "
          f"sort by {primary_sort}...")
    t0 = time.time()
    rows: list[dict] = []
    for i, c0 in enumerate(c0_list, 1):
        t = time.time()
        try:
            row = spn_sweep(c0, args.rounds, solver=args.solver)
        except Exception as e:
            print(f"  [{i}/{len(c0_list)}] {_format_c0(c0)}: ERROR {e}",
                  file=sys.stderr)
            continue
        rows.append(row)
        dt = time.time() - t
        rn = " ".join(f"R{R}={row['rounds'][R]}" for R in args.rounds)
        print(f"  [{i:>3}/{len(c0_list)}] {_format_c0(c0)}  "
              f"B={row['B_bytes']} {rn}  ({dt:.2f}s)")

    print(f"\nTotal: {time.time() - t0:.1f}s\n")
    print_table(rows, args.rounds, primary_sort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
