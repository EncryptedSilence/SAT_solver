"""Command-line interface.

Subcommands:
  layer  -- single-layer branch / min-weight differential (default)
  spn    -- multi-round active S-box analysis
"""
from __future__ import annotations

import argparse
import json
import sys

from .branch import min_weight
from .io import load_layer, load_spn
from .propagation import CipherSpec, min_trail
from .spn import min_active_sboxes


def _run_layer(args: argparse.Namespace) -> int:
    layer = load_layer(args.input)
    res = min_weight(
        layer,
        objective=args.objective,
        solver=args.solver,
        max_k=args.max_k,
        fix_first=args.fix_first,
        enumerate_all=args.enumerate_all,
    )
    if args.enumerate_all:
        out = {
            "objective": res.objective,
            "minimum_weight": res.minimum_weight,
            "count": len(res.differentials),
            "differentials": [
                {"input_diff": d.input_diff, "output_diff": d.output_diff}
                for d in res.differentials
            ],
        }
    else:
        d = res.first
        out = {
            "objective": res.objective,
            "minimum_weight": res.minimum_weight,
            "input_diff": d.input_diff,
            "output_diff": d.output_diff,
        }
        if res.objective == "sum":
            out["branch_number"] = res.minimum_weight
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


def _run_spn(args: argparse.Namespace) -> int:
    spec = load_spn(args.input)
    res = min_active_sboxes(
        spec, rounds=args.rounds, solver=args.solver, max_k=args.max_k,
    )
    out = {
        "rounds": res.rounds,
        "min_active_sboxes": res.min_active_sboxes,
        "trail": res.trail,
    }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


def _add_layer_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input", required=True, help="path to layer JSON")
    p.add_argument("--solver", default="cms",
                   help="backend: cms | pysat | pysat:<engine>")
    p.add_argument("--objective", default="sum",
                   choices=["sum", "input", "output"],
                   help="sum = w(dx)+w(dy) (branch number); "
                        "input = w(dx); output = w(dy)")
    p.add_argument("--max-k", type=int, default=None)
    p.add_argument("--fix-first", action="store_true",
                   help="assert x_0 = 1 (symmetry break; unsafe in general)")
    p.add_argument("--enumerate", dest="enumerate_all", action="store_true",
                   help="return all differentials at the minimum weight")


def _run_trail(args: argparse.Namespace) -> int:
    layer = load_layer(args.input)
    spec = CipherSpec(linear_layer=layer, cell_bits=args.cell_bits)
    res = min_trail(spec, rounds=args.rounds, solver=args.solver,
                    max_k=args.max_k)
    out = {
        "rounds": res.rounds,
        "min_active_sboxes": res.min_active_sboxes,
        "active_per_round": res.active_per_round,
        "active_bytes_x": res.active_bytes_x,
        "x_states": res.x_states,
        "y_states": res.y_states,
    }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


def _add_trail_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input", required=True,
                   help="path to linear-layer JSON (matrix or operations)")
    p.add_argument("--rounds", type=int, required=True)
    p.add_argument("--cell-bits", type=int, default=8,
                   help="S-box width in bits (default 8)")
    p.add_argument("--solver", default="cms")
    p.add_argument("--max-k", type=int, default=None)


def _add_spn_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input", required=True, help="path to SPN JSON")
    p.add_argument("--rounds", type=int, required=True,
                   help="number of rounds")
    p.add_argument("--solver", default="cms",
                   help="backend: cms | pysat | pysat:<engine>")
    p.add_argument("--max-k", type=int, default=None)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="sat_branch")
    sub = p.add_subparsers(dest="cmd")

    p_layer = sub.add_parser("layer", help="single-layer analysis")
    _add_layer_args(p_layer)
    p_layer.set_defaults(func=_run_layer)

    p_spn = sub.add_parser("spn", help="multi-round active S-box count")
    _add_spn_args(p_spn)
    p_spn.set_defaults(func=_run_spn)

    p_trail = sub.add_parser(
        "trail",
        help="bit-exact multi-round differential trail (linear exact, "
             "S-box bijective)",
    )
    _add_trail_args(p_trail)
    p_trail.set_defaults(func=_run_trail)

    # Back-compat: if first arg is a flag (e.g. --input), assume `layer`.
    if argv and not argv[0].startswith("-") and argv[0] in {"layer", "spn", "trail"}:
        args = p.parse_args(argv)
    else:
        args = p.parse_args(["layer"] + argv)

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
