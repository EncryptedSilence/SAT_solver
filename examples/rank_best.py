"""Two-stage c0 ranking for lin344.

Stage 1 (fast, cell-level SPN): identify the top tier of c0 triples —
those sharing the maximum SPN active-S-box count at the chosen R.

Stage 2 (slow, bit-exact propagation): for each top-tier triple, run
`min_trail` at a higher bit-exact R. The bit-exact model respects the
actual XOR equations of the linear layer and typically discriminates
among triples that the cell-level SPN model cannot.

A JSON cache (`--cache`) is written after every solve, so partial runs
are not lost. Re-running with the same cache skips already-solved triples.

Usage:
    python examples/rank_best.py                                   # full run, R_bit=3
    python examples/rank_best.py --rounds-bit 2                    # fast sanity
    python examples/rank_best.py --file my_c0.txt --rounds-bit 3
    python examples/rank_best.py --top-n 20 --rounds-bit 4         # first 20 only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lin344_variants import build_layer  # noqa: E402
from sat_branch.propagation import CipherSpec, min_trail  # noqa: E402
from sat_branch.spn import Column, SPNSpec, min_active_sboxes  # noqa: E402
from sweep_c0 import (  # noqa: E402
    byte_branch_number,
    parse_c0_file,
    _format_c0,
)

CELL_BITS = 8
N_CELLS = 16


def stage1_cell(c0_list: list[tuple[int, int, int]], rounds_cell: list[int],
                solver: str, cache: dict) -> list[dict]:
    """Run cell-level SPN sweep; use cache when possible."""
    rows: list[dict] = []
    for i, c0 in enumerate(c0_list, 1):
        key = f"{c0[0]},{c0[1]},{c0[2]}"
        cached = cache.get("stage1", {}).get(key)
        if cached and all(str(R) in cached["rounds"] for R in rounds_cell):
            rows.append({
                "c0": list(c0),
                "B_bytes": cached["B_bytes"],
                "rounds": {int(k): v for k, v in cached["rounds"].items()},
            })
            continue
        t = time.time()
        L = build_layer(c0)
        B = byte_branch_number(L, solver)
        spec = SPNSpec(
            n_cells=N_CELLS, cell_bits=CELL_BITS,
            columns=[Column(input_cells=list(range(N_CELLS)),
                            output_cells=list(range(N_CELLS)),
                            branch_number=B)],
        )
        r_by = {}
        for R in rounds_cell:
            res = min_active_sboxes(spec, rounds=R, solver=solver)
            r_by[R] = res.min_active_sboxes
        row = {"c0": list(c0), "B_bytes": B, "rounds": r_by}
        rows.append(row)
        cache.setdefault("stage1", {})[key] = {
            "B_bytes": B,
            "rounds": {str(k): v for k, v in r_by.items()},
        }
        _write_cache(cache)
        dt = time.time() - t
        rn = " ".join(f"R{R}={r_by[R]}" for R in rounds_cell)
        print(f"  [S1 {i:>4}/{len(c0_list)}] {_format_c0(c0)}  "
              f"B={B} {rn}  ({dt:.2f}s)")
    return rows


def select_top(rows: list[dict], round_key: int) -> list[dict]:
    best = max(r["rounds"][round_key] for r in rows)
    tier_b = max(r["B_bytes"] for r in rows if r["rounds"][round_key] == best)
    return [r for r in rows
            if r["rounds"][round_key] == best and r["B_bytes"] == tier_b]


def stage2_bit(top_rows: list[dict], rounds_bit: int, solver: str,
               cache: dict) -> list[dict]:
    """Run bit-exact propagation at R = rounds_bit for each top-tier triple."""
    results: list[dict] = []
    for i, row in enumerate(top_rows, 1):
        c0 = tuple(row["c0"])
        key = f"{c0[0]},{c0[1]},{c0[2]}"
        ckey = f"R{rounds_bit}"
        cached = cache.get("stage2", {}).get(key, {}).get(ckey)
        if cached is not None:
            print(f"  [S2 {i:>3}/{len(top_rows)}] {_format_c0(c0)}  "
                  f"R{rounds_bit}={cached['min_active']}  per={cached['per_round']}  "
                  f"(cached)")
            results.append({
                "c0": list(c0),
                "B_bytes": row["B_bytes"],
                "cell_rounds": row["rounds"],
                "bit_min_active": cached["min_active"],
                "bit_per_round": cached["per_round"],
            })
            continue
        t = time.time()
        L = build_layer(c0)
        spec = CipherSpec(linear_layer=L, cell_bits=CELL_BITS)
        r = min_trail(spec, rounds=rounds_bit, solver=solver)
        dt = time.time() - t
        print(f"  [S2 {i:>3}/{len(top_rows)}] {_format_c0(c0)}  "
              f"R{rounds_bit}={r.min_active_sboxes}  per={r.active_per_round}  "
              f"({dt:.1f}s)")
        cache.setdefault("stage2", {}).setdefault(key, {})[ckey] = {
            "min_active": r.min_active_sboxes,
            "per_round": list(r.active_per_round),
        }
        _write_cache(cache)
        results.append({
            "c0": list(c0),
            "B_bytes": row["B_bytes"],
            "cell_rounds": row["rounds"],
            "bit_min_active": r.min_active_sboxes,
            "bit_per_round": list(r.active_per_round),
        })
    return results


_cache_path: Path | None = None


def _write_cache(cache: dict) -> None:
    if _cache_path is not None:
        _cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _read_cache(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def print_final(results: list[dict], rounds_bit: int,
                rounds_cell: list[int]) -> None:
    # Sort descending by bit-exact (primary), then cell-level R_max (tiebreak).
    rc_max = max(rounds_cell)
    results_sorted = sorted(
        results,
        key=lambda r: (r["bit_min_active"],
                       r["cell_rounds"][rc_max],
                       r["B_bytes"]),
        reverse=True,
    )
    best = results_sorted[0]["bit_min_active"]

    header = (f"{'c0':>14}  {'B':>2}  "
              + "  ".join(f"cR{R}" for R in rounds_cell)
              + f"  bR{rounds_bit}  per-round     note")
    print()
    print(header)
    print("-" * len(header))
    for r in results_sorted:
        cells = "  ".join(f"{r['cell_rounds'][R]:>3}" for R in rounds_cell)
        mark = "  <-- BEST" if r["bit_min_active"] == best else ""
        print(f"{_format_c0(tuple(r['c0'])):>14}  {r['B_bytes']:>2}  "
              f"{cells}  {r['bit_min_active']:>3}  {str(r['bit_per_round']):<15}"
              f"{mark}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--file", default=str(Path(__file__).parent / "c0.txt"))
    p.add_argument("--rounds-cell", type=int, nargs="+", default=[2, 3, 4],
                   help="cell-level rounds (stage 1)")
    p.add_argument("--rounds-bit", type=int, default=3,
                   help="bit-exact rounds (stage 2)")
    p.add_argument("--sort-key", type=int, default=None,
                   help="cell R used to pick top tier (default: max of --rounds-cell)")
    p.add_argument("--top-n", type=int, default=None,
                   help="limit stage-2 to the first N top-tier triples")
    p.add_argument("--solver", default="cms")
    p.add_argument("--cache",
                   default=str(Path(__file__).parent / "c0_rank_cache.json"))
    args = p.parse_args()

    global _cache_path
    _cache_path = Path(args.cache)
    cache = _read_cache(_cache_path)

    c0_list = parse_c0_file(Path(args.file))
    sort_key = args.sort_key or max(args.rounds_cell)
    if sort_key not in args.rounds_cell:
        raise SystemExit(
            f"--sort-key {sort_key} not in --rounds-cell {args.rounds_cell}; "
            f"pick a round that will actually be computed."
        )
    print(f"Stage 1: cell-level SPN for {len(c0_list)} triples, "
          f"rounds={args.rounds_cell}")
    t0 = time.time()
    rows = stage1_cell(c0_list, args.rounds_cell, args.solver, cache)
    print(f"  stage 1 total: {time.time() - t0:.1f}s\n")

    top = select_top(rows, sort_key)
    if args.top_n is not None:
        top = top[:args.top_n]
    tier_score = top[0]["rounds"][sort_key] if top else "-"
    print(f"Stage 2: bit-exact R={args.rounds_bit} for "
          f"{len(top)} top-tier triples (cell R={sort_key} "
          f"= {tier_score} among best)\n")

    t0 = time.time()
    results = stage2_bit(top, args.rounds_bit, args.solver, cache)
    print(f"  stage 2 total: {time.time() - t0:.1f}s")

    print_final(results, args.rounds_bit, args.rounds_cell)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
