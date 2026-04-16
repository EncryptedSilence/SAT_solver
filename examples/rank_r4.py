"""Bit-exact R=4 evaluation on a pre-selected list of c0 triples.

Runs `min_trail` at R=4 for each triple, reusing the stage-2 cache written
by rank_best.py so nothing repeats. Prints a ranked table at the end.

Usage:
    python examples/rank_r4.py                       # uses the list below
    python examples/rank_r4.py 1 10 15 1 17 14       # ad-hoc triples (flat ints)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lin344_variants import build_layer  # noqa: E402
from sat_branch.propagation import CipherSpec, min_trail  # noqa: E402

CELL_BITS = 8
CACHE = Path(__file__).parent / "c0_rank_cache.json"

# Top 24 triples from R=3 bit-exact (all scored 12), plus two references.
DEFAULT_LIST: list[tuple[int, int, int]] = [
    (0, 8, 15), (0, 9, 15), (0, 23, 17), (0, 24, 17),
    (2, 21, 15), (6, 27, 9), (8, 7, 9), (8, 8, 9),
    (8, 24, 7), (8, 25, 7), (10, 5, 7), (14, 11, 1),
    (16, 8, 31), (16, 9, 31), (16, 23, 1), (16, 24, 1),
    (18, 21, 31), (22, 27, 25), (24, 7, 25), (24, 8, 25),
    (24, 24, 23), (24, 25, 23), (26, 5, 23), (30, 11, 17),
    # References
    (1, 10, 15), (1, 17, 14),
]


def _load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _fmt(c0: tuple[int, int, int]) -> str:
    return f"{{{c0[0]:>2}, {c0[1]:>2}, {c0[2]:>2}}}"


def main() -> int:
    if len(sys.argv) > 1:
        ints = [int(a) for a in sys.argv[1:]]
        if len(ints) % 3 != 0:
            print("error: argument count must be a multiple of 3",
                  file=sys.stderr)
            return 2
        triples = [tuple(ints[i:i + 3]) for i in range(0, len(ints), 3)]
    else:
        triples = list(DEFAULT_LIST)

    cache = _load_cache()
    stage2 = cache.setdefault("stage2", {})

    results: list[dict] = []
    print(f"Bit-exact R=4 on {len(triples)} triples "
          f"(~90s each on CMS, cached across runs)\n")
    t0 = time.time()
    for i, c0 in enumerate(triples, 1):
        key = f"{c0[0]},{c0[1]},{c0[2]}"
        entry = stage2.setdefault(key, {})
        cached = entry.get("R4")
        r3 = entry.get("R3", {}).get("min_active")
        if cached is not None:
            print(f"  [{i:>2}/{len(triples)}] {_fmt(c0):>14}  "
                  f"R4={cached['min_active']} per={cached['per_round']}  "
                  f"(cached)")
            results.append({"c0": c0, "R3": r3,
                            "R4": cached["min_active"],
                            "per4": cached["per_round"]})
            continue
        t = time.time()
        L = build_layer(c0)
        spec = CipherSpec(linear_layer=L, cell_bits=CELL_BITS)
        r = min_trail(spec, rounds=4, solver="cms")
        dt = time.time() - t
        entry["R4"] = {"min_active": r.min_active_sboxes,
                       "per_round": list(r.active_per_round)}
        _save_cache(cache)
        print(f"  [{i:>2}/{len(triples)}] {_fmt(c0):>14}  "
              f"R4={r.min_active_sboxes} per={r.active_per_round}  "
              f"({dt:.1f}s)")
        results.append({"c0": c0, "R3": r3,
                        "R4": r.min_active_sboxes,
                        "per4": list(r.active_per_round)})

    print(f"\ntotal: {time.time() - t0:.1f}s\n")

    best_r4 = max(r["R4"] for r in results)
    results_sorted = sorted(
        results,
        key=lambda r: (r["R4"], r["R3"] or 0),
        reverse=True,
    )
    print(f"{'c0':>14}  {'R3':>3}  {'R4':>3}  per-round       note")
    print("-" * 60)
    for r in results_sorted:
        mark = "  <-- BEST" if r["R4"] == best_r4 else ""
        r3s = f"{r['R3']}" if r["R3"] is not None else "-"
        print(f"{_fmt(r['c0']):>14}  {r3s:>3}  {r['R4']:>3}  "
              f"{str(r['per4']):<15}{mark}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
