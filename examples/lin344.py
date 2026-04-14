"""Compute the branch number of the Qalqan lin344 linear layer.

Usage:
    python examples/lin344.py [--solver cms]

Builds the 128-bit linear layer directly in memory (no JSON intermediary)
and invokes the SAT solver.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lin344_ref import build_layer, lin344_bits, unpack  # noqa: E402
from sat_branch.branch import branch_number  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--solver", default="cms")
    args = p.parse_args()

    L = build_layer()
    res = branch_number(L, solver=args.solver)

    dx = 0
    for i, ch in enumerate(res.input_diff):
        if ch == "1":
            dx |= 1 << i
    dy = 0
    for i, ch in enumerate(res.output_diff):
        if ch == "1":
            dy |= 1 << i
    assert lin344_bits(dx) == dy

    print(f"branch number    : {res.branch_number}")
    print(f"input  weight    : {bin(dx).count('1')}")
    print(f"output weight    : {bin(dy).count('1')}")
    print(f"input  words     : {[hex(w) for w in unpack(dx)]}")
    print(f"output words     : {[hex(w) for w in unpack(dy)]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
