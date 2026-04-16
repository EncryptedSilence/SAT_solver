"""DDT-aware minimum-weight differential trail for lin344, c0=(1,17,14), R=4.

Self-contained script with INCREMENTAL solving:

  * The CNF encoding — byte activity, S-box bijection, XOR-exact linear
    layer, iv/ov indicators, Qalqan DDT pair clauses — is built ONCE.
  * A sequential-counter threshold structure exposes, for every W in
    [0, w_hi], a literal `tvars[W]` that is True iff the weighted sum
    strictly exceeds W.
  * Binary search over W then drives the solver by ASSUMPTIONS only:
    to enforce "sum <= W", pass `-tvars[W]` to solve(). CMS retains its
    learned clauses across calls, so each later solve starts warm.

This avoids the O(rounds × 1M) CNF-emission cost per W iteration and
lets the solver amortise learned clauses across the whole binary search.
"""
from __future__ import annotations

import sys

# --- Preflight checks (run before any 3.10+ syntax is evaluated) ----------
if sys.version_info < (3, 10):
    sys.stderr.write(
        f"ERROR: this script requires Python >= 3.10 "
        f"(found {sys.version.split()[0]}). "
        f"The encoding uses PEP 604 union syntax (X | None).\n")
    sys.exit(1)

try:
    import pycryptosat  # noqa: F401
except ImportError:
    sys.stderr.write(
        "ERROR: pycryptosat not installed — this script needs the\n"
        "CryptoMiniSat Python bindings.\n"
        "  Install:  pip install pycryptosat\n"
        "  On Windows, a prebuilt wheel is usually available; if pip\n"
        "  tries to build from source you will need MSVC build tools\n"
        "  or use a conda environment (conda install -c conda-forge "
        "pycryptosat).\n")
    sys.exit(1)

# Force UTF-8 stdout/stderr so the pretty-printer's Greek/math glyphs
# don't crash on Windows' default cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    _reconf = getattr(_stream, "reconfigure", None)
    if _reconf is not None:
        try:
            _reconf(encoding="utf-8", errors="replace")
        except Exception:
            pass
# --------------------------------------------------------------------------

import gc
import time
from pathlib import Path
from typing import Callable, Iterable

# Allow running directly via `python examples/best_trail_c0_1_17_14_R4.py`.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))
if str(_ROOT / "examples") not in sys.path:
    sys.path.insert(0, str(_ROOT / "examples"))

try:
    from sat_branch.layer import LinearLayer  # noqa: E402
    from sat_branch.solver import CMSBackend  # noqa: E402
except ImportError as e:
    sys.stderr.write(
        f"ERROR: cannot import sat_branch package ({e}).\n"
        f"This script expects to live in <repo>/examples/ with the\n"
        f"sat_branch package in <repo>/src/. Either run it from a\n"
        f"full checkout of the SAT_solver repo, or install the\n"
        f"package with `pip install -e .` from the repo root.\n")
    sys.exit(1)

# --------------------------------------------------------------------------
# Hardcoded constants
# --------------------------------------------------------------------------

C0 = (1, 17, 14)
ROUNDS = 4
N = 128
CELL_BITS = 8
NB = N // CELL_BITS  # 16

# Encoding selector:
#   "iv_only"  — original: iv[di] only; forbidden/weight clauses are
#                9/10-literal wide (dense).
#   "iv_ov"    — adds ov[do] indicators; forbidden becomes 2-lit, weight
#                becomes 3-lit. ~3x smaller CMS memory footprint, faster
#                BCP (CMS has a dedicated fast path for binary clauses).
ENCODING = "iv_ov"

# Qalqan S-box (from Qalqan.cpp; differential uniformity = 4, so DDT
# values for di != 0 are in {0, 2, 4}).
QALQAN_SBOX: tuple[int, ...] = (
    0xd1, 0xb5, 0xa6, 0x74, 0x2f, 0xb2, 0x03, 0x77, 0xae, 0xb3, 0x60, 0x95, 0xfd, 0xf8, 0xc7, 0xf0,
    0x2b, 0xce, 0xa5, 0x91, 0x4c, 0x6f, 0xf3, 0x4f, 0x82, 0x01, 0x45, 0x76, 0x9f, 0xed, 0x41, 0xfb,
    0xac, 0x4e, 0x5e, 0x04, 0xeb, 0xf9, 0xf1, 0x3a, 0x1f, 0xe2, 0x8e, 0xe7, 0x85, 0x35, 0xdb, 0x52,
    0x78, 0xa1, 0xfc, 0xa2, 0xde, 0x68, 0x02, 0x4d, 0xf6, 0xdd, 0xcf, 0xa3, 0xdc, 0x6b, 0x81, 0x44,
    0x2a, 0x5d, 0x1e, 0xe0, 0x53, 0x71, 0x3b, 0xc1, 0xcc, 0x9d, 0x80, 0xd5, 0x84, 0x00, 0x24, 0x4b,
    0xb6, 0x83, 0x0d, 0x87, 0x7e, 0x86, 0xca, 0x96, 0xbe, 0x5a, 0xe6, 0xd0, 0xd4, 0xd8, 0x55, 0xc0,
    0x05, 0xe5, 0xe9, 0x5b, 0x47, 0xe4, 0x2d, 0x34, 0x13, 0x88, 0x48, 0x32, 0x38, 0xb9, 0xda, 0xc9,
    0x42, 0x29, 0xd7, 0xf2, 0x9b, 0x6d, 0xe8, 0x8d, 0x12, 0x7c, 0x8c, 0x3f, 0xbc, 0x3c, 0x1b, 0xc5,
    0x69, 0x22, 0x97, 0xaa, 0x73, 0x0a, 0x0c, 0x8a, 0x90, 0x31, 0xc4, 0x33, 0xe1, 0x8b, 0x9c, 0x63,
    0x5f, 0xf5, 0xf7, 0xff, 0x79, 0x49, 0xd3, 0xc6, 0x7b, 0x1a, 0x39, 0xc8, 0x6e, 0x72, 0xd9, 0xc3,
    0x62, 0x28, 0xbd, 0xbb, 0xfa, 0x2e, 0xbf, 0x43, 0x06, 0x0b, 0x7a, 0x64, 0x5c, 0x92, 0x37, 0x3d,
    0x66, 0x26, 0x51, 0xef, 0x0f, 0xa9, 0x14, 0x70, 0x16, 0x17, 0x10, 0x19, 0x93, 0x09, 0x59, 0x15,
    0xfe, 0x4a, 0xcb, 0x2c, 0xcd, 0xb8, 0x94, 0xab, 0xdf, 0xa7, 0x0e, 0x30, 0xaf, 0x56, 0x23, 0xb1,
    0xb0, 0x58, 0x7d, 0xc2, 0x1d, 0x50, 0x20, 0x61, 0x25, 0x89, 0xa0, 0x6c, 0x11, 0x54, 0x98, 0xb7,
    0x18, 0x21, 0xad, 0x3e, 0xd2, 0xea, 0x40, 0xd6, 0xf4, 0xa4, 0x8f, 0xa8, 0x08, 0x57, 0xba, 0xee,
    0x75, 0x6a, 0x07, 0x99, 0x7f, 0x1c, 0xe3, 0x46, 0x67, 0xec, 0x27, 0x36, 0xb4, 0x65, 0x9e, 0x9a,
)

SBOX = QALQAN_SBOX
SBOX_NAME = "Qalqan"

assert len(SBOX) == 256 and len(set(SBOX)) == 256

MASK32 = 0xFFFFFFFF


# --------------------------------------------------------------------------
# lin344 linear layer (inline, copy of examples/lin344_variants.py)
# --------------------------------------------------------------------------

def _rotl32(x: int, s: int) -> int:
    x &= MASK32
    s %= 32
    return ((x << s) | (x >> (32 - s))) & MASK32 if s else x


def _lin344_apply(din: list[int], c0) -> list[int]:
    d0 = (din[0] ^ _rotl32(din[1], c0[0]) ^ _rotl32(din[2], c0[1])
          ^ _rotl32(din[3], c0[2])) & MASK32
    d1 = (din[1] ^ _rotl32(din[2], c0[0]) ^ _rotl32(din[3], c0[1])
          ^ _rotl32(d0, c0[2])) & MASK32
    d2 = (din[2] ^ _rotl32(din[3], c0[0]) ^ _rotl32(d0, c0[1])
          ^ _rotl32(d1, c0[2])) & MASK32
    d3 = (din[3] ^ _rotl32(d0, c0[0]) ^ _rotl32(d1, c0[1])
          ^ _rotl32(d2, c0[2])) & MASK32
    return [d0, d1, d2, d3]


def _pack(words: list[int]) -> int:
    v = 0
    for i, w in enumerate(words):
        v |= (w & MASK32) << (32 * i)
    return v


def _unpack(v: int) -> list[int]:
    return [(v >> (32 * i)) & MASK32 for i in range(4)]


def build_lin344(c0) -> LinearLayer:
    rows = [0] * N
    for j in range(N):
        y = _pack(_lin344_apply(_unpack(1 << j), c0))
        for i in range(N):
            if (y >> i) & 1:
                rows[i] |= 1 << j
    return LinearLayer(n=N, rows=rows)


# --------------------------------------------------------------------------
# DDT
# --------------------------------------------------------------------------

def build_ddt(sbox: Iterable[int]) -> list[list[int]]:
    sbox = list(sbox)
    ddt = [[0] * 256 for _ in range(256)]
    for x in range(256):
        sx = sbox[x]
        for di in range(256):
            ddt[di][sx ^ sbox[x ^ di]] += 1
    return ddt


# --------------------------------------------------------------------------
# Sequential-counter threshold encoding (incremental-friendly).
# --------------------------------------------------------------------------
#
# Builds s[i][j] for i in 0..m-1, j in 0..k_max-1 with the forward-only
# invariant:
#       sum(lits[0..i]) >= j + 1     =>     s[i][j] = True.
#
# Contrapositive: s[m-1][W] = False  =>  sum <= W.
# To enforce "sum <= W" at solve time, pass `-s[m-1][W]` as an assumption
# literal. No further clauses are added after the encoding is built, so
# the base CNF is shared across all binary-search queries and CMS's
# learned clauses carry over.
#
# Only the forward direction is encoded. That is sufficient for
# correctness of assumption-based at-most-W queries — a solution with
# sum = k must set s[m-1][k-1] = True (forced by forward chain), so
# assuming -s[m-1][W] forbids all sums > W. The solver may set higher
# threshold bits "for free" on valid solutions, which costs nothing.

def build_threshold_counter(lits: list[int], k_max: int,
                            fresh: Callable[[int], list[int]],
                            add_clause: Callable[[list[int]], None]
                            ) -> list[int]:
    """Return threshold literals t[0..k_max-1] on the last row.

    t[j] is True if sum(lits) >= j + 1 (only the implication; no reverse).
    """
    m = len(lits)
    if k_max <= 0 or m == 0:
        return []

    s: list[list[int]] = [fresh(k_max) for _ in range(m)]

    # i = 0:  lits[0] -> s[0][0]  (higher thresholds impossible after one input
    # but we do NOT need to forbid s[0][j>=1] explicitly because forward-only
    # propagation leaves them optional; the solver may set them true without
    # affecting the constraint we impose via assumption).
    add_clause([-lits[0], s[0][0]])

    # i >= 1:  s[i-1][j] -> s[i][j]  (carry)
    #          lits[i] -> s[i][0]
    #          lits[i] AND s[i-1][j-1] -> s[i][j]  (carry + 1)
    for i in range(1, m):
        for j in range(k_max):
            add_clause([-s[i - 1][j], s[i][j]])
        add_clause([-lits[i], s[i][0]])
        for j in range(1, k_max):
            add_clause([-lits[i], -s[i - 1][j - 1], s[i][j]])

    return s[m - 1]


# --------------------------------------------------------------------------
# Incremental encoding: build once, query many.
# --------------------------------------------------------------------------

def build_encoding(layer: LinearLayer, ddt: list[list[int]], rounds: int,
                   w_hi: int):
    """Emit the full CNF/XOR encoding plus a threshold counter into CMS.

    Returns a dict containing:
      backend      — CMSBackend with all base clauses loaded.
      tvars        — list of length w_hi+1; tvars[W] is the threshold lit
                     "weighted sum strictly > W". Assume -tvars[W] to
                     enforce "sum <= W".
      x, y, bx, by, w6, w7 — SAT var ids, used by decode().
      top, nclauses, nxors — stats.
    """
    top = 0

    def fresh(k: int = 1) -> list[int]:
        nonlocal top
        out = list(range(top + 1, top + 1 + k))
        top += k
        return out

    def fresh1() -> int:
        return fresh(1)[0]

    # --- Variables ----------------------------------------------------------
    x = [[fresh1() for _ in range(N)] for _ in range(rounds + 1)]
    y = [[fresh1() for _ in range(N)] for _ in range(rounds)]
    bx = [[fresh1() for _ in range(NB)] for _ in range(rounds + 1)]
    by = [[fresh1() for _ in range(NB)] for _ in range(rounds)]
    w6 = [[fresh1() for _ in range(NB)] for _ in range(rounds)]
    w7 = [[fresh1() for _ in range(NB)] for _ in range(rounds)]
    iv = [[[fresh1() for _ in range(256)] for _ in range(NB)]
          for _ in range(rounds)]
    ov: list[list[list[int]]] | None
    if ENCODING == "iv_ov":
        ov = [[[fresh1() for _ in range(256)] for _ in range(NB)]
              for _ in range(rounds)]
    else:
        ov = None

    backend = CMSBackend()
    nclauses = 0
    nxors = 0

    def add_clause(c: list[int]) -> None:
        nonlocal nclauses
        backend.add_clause(c)
        nclauses += 1

    def add_xor(lits: list[int], rhs: bool) -> None:
        nonlocal nxors
        backend.add_xor(lits, rhs)
        nxors += 1

    # --- Byte activity ------------------------------------------------------
    def bind_byte_activity(bits: list[int], ind: list[int]) -> None:
        for i, b in enumerate(ind):
            byte_bits = bits[CELL_BITS * i: CELL_BITS * (i + 1)]
            for bit in byte_bits:
                add_clause([-bit, b])
            add_clause([-b] + byte_bits)

    for r in range(rounds + 1):
        bind_byte_activity(x[r], bx[r])
    for r in range(rounds):
        bind_byte_activity(y[r], by[r])

    # --- S-box byte-activity bijection --------------------------------------
    for r in range(rounds):
        for i in range(NB):
            add_clause([-bx[r][i], by[r][i]])
            add_clause([-by[r][i], bx[r][i]])

    # --- Linear layer: x[r+1] = L(y[r]) -------------------------------------
    for r in range(rounds):
        for i in range(N):
            deps = layer.dependencies(i)
            lits = [x[r + 1][i]] + [y[r][j] for j in deps]
            add_xor(lits, False)

    # --- Non-zero input -----------------------------------------------------
    add_clause(list(x[0]))

    # --- DDT constraints per (r, i) -----------------------------------------
    for r in range(rounds):
        for i in range(NB):
            add_clause([-w6[r][i], bx[r][i]])
            add_clause([-w7[r][i], bx[r][i]])
            add_clause([-bx[r][i], w6[r][i], w7[r][i]])
            add_clause([-w6[r][i], -w7[r][i]])

            xb = x[r][CELL_BITS * i: CELL_BITS * (i + 1)]
            yb = y[r][CELL_BITS * i: CELL_BITS * (i + 1)]

            for di in range(1, 256):
                lit_iv = iv[r][i][di]
                pattern = [xb[b] if ((di >> b) & 1) else -xb[b]
                           for b in range(CELL_BITS)]
                for lit in pattern:
                    add_clause([-lit_iv, lit])
                add_clause([-p for p in pattern] + [lit_iv])

            if ENCODING == "iv_ov":
                for do in range(256):
                    lit_ov = ov[r][i][do]
                    pattern = [yb[b] if ((do >> b) & 1) else -yb[b]
                               for b in range(CELL_BITS)]
                    for lit in pattern:
                        add_clause([-lit_ov, lit])
                    add_clause([-p for p in pattern] + [lit_ov])

                for di in range(1, 256):
                    lit_iv = iv[r][i][di]
                    row = ddt[di]
                    w6_lit = w6[r][i]
                    w7_lit = w7[r][i]
                    for do in range(256):
                        v = row[do]
                        lit_ov = ov[r][i][do]
                        if v == 0:
                            add_clause([-lit_iv, -lit_ov])
                        elif v == 4:
                            add_clause([-lit_iv, -lit_ov, w6_lit])
                        elif v == 2:
                            add_clause([-lit_iv, -lit_ov, w7_lit])
            else:
                for di in range(1, 256):
                    lit_iv = iv[r][i][di]
                    row = ddt[di]
                    for do in range(256):
                        v = row[do]
                        if v == 0 or v == 2 or v == 4:
                            yneg = [-yb[b] if ((do >> b) & 1) else yb[b]
                                    for b in range(CELL_BITS)]
                            base = [-lit_iv] + yneg
                            if v == 0:
                                add_clause(base)
                            elif v == 4:
                                base.append(w6[r][i])
                                add_clause(base)
                            else:
                                base.append(w7[r][i])
                                add_clause(base)

    # --- Threshold counter over Σ (6·w6 + 7·w7) -----------------------------
    # Counter width = w_hi + 1 so thresholds for W in [0, w_hi] are exposed.
    obj: list[int] = []
    for r in range(rounds):
        for i in range(NB):
            obj += [w6[r][i]] * 6 + [w7[r][i]] * 7
    last_row = build_threshold_counter(obj, w_hi + 1, fresh, add_clause)
    # tvars[W] = "sum >= W+1" = "sum > W". Assume -tvars[W] => "sum <= W".
    # last_row index j corresponds to threshold W = j.
    tvars = last_row  # length w_hi+1

    # Drop temporaries we don't need during the solve loop.
    del obj, iv, ov
    gc.collect()

    return {
        "backend": backend,
        "tvars": tvars,
        "x": x, "y": y, "bx": bx, "by": by, "w6": w6, "w7": w7,
        "top": top, "nclauses": nclauses, "nxors": nxors,
    }


def solve_weighted(enc: dict, w_lo: int, w_hi: int):
    """Binary-search the minimum W with a single shared encoding.

    Each iteration calls CMS with a single-element assumption list
    [-tvars[W]], enforcing "weighted sum <= W". Learned clauses persist.
    """
    backend: CMSBackend = enc["backend"]
    tvars: list[int] = enc["tvars"]

    lo, hi = w_lo, w_hi
    best_sat: int | None = None
    best_model: list[int] | None = None
    total_solve = 0.0
    calls = 0

    while lo <= hi:
        mid = (lo + hi) // 2
        calls += 1
        print(f"[bsearch] trying W = {mid}  (range [{lo}, {hi}])",
              flush=True)
        t0 = time.time()
        sat = backend.solve(assumptions=[-tvars[mid]])
        dt = time.time() - t0
        total_solve += dt
        tag = "SAT" if sat else "UNSAT"
        print(f"  {tag:<5}  ({dt:.2f}s)", flush=True)
        if sat:
            best_sat = mid
            best_model = backend.model()
            hi = mid - 1
        else:
            lo = mid + 1

    if best_sat is None or best_model is None:
        raise RuntimeError(f"no trail with W in [{w_lo}, {w_hi}]")

    print(f"[bsearch] done: {calls} solver calls, "
          f"cumulative solve time {total_solve:.2f}s")

    val = {abs(l): l > 0 for l in best_model}
    # Retain only decoding vars; drop the rest.
    keep_vars: set[int] = set()
    rounds = len(enc["y"])
    for r in range(rounds + 1):
        keep_vars.update(enc["x"][r])
        keep_vars.update(enc["bx"][r])
    for r in range(rounds):
        keep_vars.update(enc["y"][r])
        keep_vars.update(enc["by"][r])
        keep_vars.update(enc["w6"][r])
        keep_vars.update(enc["w7"][r])
    val = {v: val.get(v, False) for v in keep_vars}
    result = (val, enc["x"], enc["y"], enc["bx"],
              enc["by"], enc["w6"], enc["w7"])
    return best_sat, result


# --------------------------------------------------------------------------
# Decoding / pretty-print
# --------------------------------------------------------------------------

def _bits_to_hex_bytes(val: dict, bits: list[int]) -> list[int]:
    # Returns list of NB byte values; byte i is bits[8i..8i+8), bit b = 2^b.
    out = []
    for i in range(NB):
        v = 0
        for b in range(CELL_BITS):
            if val.get(bits[CELL_BITS * i + b], False):
                v |= 1 << b
        out.append(v)
    return out


def _hex_state(val: dict, bits: list[int]) -> str:
    return "".join(f"{b:02x}" for b in _bits_to_hex_bytes(val, bits))


def decode(result, rounds: int, ddt: list[list[int]], layer: LinearLayer,
           W_target: int):
    val, x, y, bx, by, w6, w7 = result

    x_bytes = [_bits_to_hex_bytes(val, x[r]) for r in range(rounds + 1)]
    y_bytes = [_bits_to_hex_bytes(val, y[r]) for r in range(rounds)]
    x_hex = ["".join(f"{b:02x}" for b in bs) for bs in x_bytes]
    y_hex = ["".join(f"{b:02x}" for b in bs) for bs in y_bytes]

    trail_rows: list[tuple[int, int, int, int, int]] = []
    total_w = 0
    for r in range(rounds):
        for i in range(NB):
            di = x_bytes[r][i]
            do = y_bytes[r][i]
            if di == 0 and do == 0:
                continue
            v = ddt[di][do]
            if v not in (2, 4):
                raise RuntimeError(
                    f"decoded (di={di:#04x}, do={do:#04x}) has DDT={v} "
                    f"at round {r} byte {i}")
            w = 7 if v == 2 else 6
            trail_rows.append((r, i, di, do, w))
            total_w += w

    if total_w != W_target:
        raise RuntimeError(
            f"decoded weight {total_w} != target {W_target}")

    # Sanity-check linear layer: x[r+1] = L(y[r]).
    for r in range(rounds):
        y_bits = 0
        for j in range(N):
            if val.get(y[r][j], False):
                y_bits |= 1 << j
        x_next_actual = layer.apply(y_bits)
        x_next_model = 0
        for j in range(N):
            if val.get(x[r + 1][j], False):
                x_next_model |= 1 << j
        if x_next_actual != x_next_model:
            raise RuntimeError(
                f"linear-layer mismatch at round {r}: "
                f"L(y[{r}])={x_next_actual:032x}, "
                f"x[{r + 1}]={x_next_model:032x}")

    return x_hex, y_hex, trail_rows, total_w


def _fmt_state_hex_spaced(hexstr: str) -> str:
    # Group every 2 hex chars (one byte) with spaces for readability.
    return " ".join(hexstr[2 * i: 2 * i + 2] for i in range(NB))


def pretty_print_trail(x_hex: list[str], y_hex: list[str],
                       trail_rows: list[tuple[int, int, int, int, int]],
                       rounds: int, W: int) -> None:
    """Layered per-round trail with explicit probability factors.

    Probability layout:
      P(Δ_in → Δ_out) = Π_r  ( Π_{active byte i}  DDT[δi][δo] / 256 )
    The linear layer L is deterministic (factor 1), so all probability
    comes from the S-box layers. Per-S-box factor:
       weight 6  <=>  DDT=4  <=>  4/256 = 2⁻⁶
       weight 7  <=>  DDT=2  <=>  2/256 = 2⁻⁷
    """
    print()
    print("=" * 72)
    print("FULL TRAIL  (probabilities at every step)")
    print("=" * 72)
    print()
    print("INPUT DIFFERENCE  Δ_in = x[0]")
    print(f"  x[0] = {_fmt_state_hex_spaced(x_hex[0])}")
    print()

    by_round: dict[int, list[tuple[int, int, int, int]]] = {
        r: [] for r in range(rounds)}
    for r, i, di, do, w in trail_rows:
        by_round[r].append((i, di, do, w))

    for r in range(rounds):
        print("-" * 72)
        print(f"ROUND {r}  —  S-box layer  (probabilistic)")
        print(f"  {'byte':>4}  {'δi':>5}  {'δo':>5}  {'DDT':>4}  "
              f"{'prob':>10}")
        round_w = 0
        for i, di, do, w in by_round[r]:
            ddt_val = 4 if w == 6 else 2
            prob_str = f"2^-{w}"
            print(f"  {i:>4}   0x{di:02x}   0x{do:02x}  {ddt_val:>4}  "
                  f"{prob_str:>10}")
            round_w += w
        if round_w == 0:
            print("  (no active S-boxes this round)")
        print(f"  {'round factor:':>27}  2^-{round_w}")
        print()
        print(f"  y[{r}] = {_fmt_state_hex_spaced(y_hex[r])}")
        print()
        print(f"ROUND {r}  —  Linear layer L  (deterministic, factor 1)")
        print(f"  L maps  y[{r}]  →  x[{r + 1}]")
        print(f"  x[{r + 1}] = {_fmt_state_hex_spaced(x_hex[r + 1])}")
        print()

    print("=" * 72)
    print(f"OUTPUT DIFFERENCE  Δ_out = x[{rounds}]")
    print(f"  x[{rounds}] = {_fmt_state_hex_spaced(x_hex[rounds])}")
    print()
    print(f"TOTAL PROBABILITY")
    per_round_w = [sum(w for _, _, _, w in by_round[r])
                   for r in range(rounds)]
    chain = " · ".join(f"2^-{w}" for w in per_round_w)
    print(f"  P(Δ_in → Δ_out) = {chain} = 2^-{W}")
    print("=" * 72)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> None:
    print(f"Target: lin344, c0={C0}, R={ROUNDS}, {SBOX_NAME} S-box")
    print(f"State: {N} bits, {NB} bytes of {CELL_BITS} bits each")
    print(f"Encoding: {ENCODING}")
    print()

    # DDT smoke tests.
    ddt = build_ddt(SBOX)
    assert ddt[0][0] == 256
    assert all(sum(row) == 256 for row in ddt)
    vals = set(v for row in ddt for v in row)
    assert vals == {0, 2, 4, 256}, f"unexpected DDT values: {vals}"
    print(f"DDT OK — value set = {sorted(vals)}")

    layer = build_lin344(C0)
    print(f"Linear layer built: n={layer.n}")

    # Compute minimum active-S-box count A for this (c0, rounds) via the
    # package's bit-exact active-count model. Weight bounds: [6A, 7A] since
    # per-S-box weight is 6 (DDT=4) or 7 (DDT=2) since Qalqan has
    # differential uniformity 4 (DDT values in {0, 2, 4, 256}).
    from sat_branch.propagation import CipherSpec, min_trail
    spec = CipherSpec(linear_layer=layer, cell_bits=CELL_BITS)
    print("Computing min active-S-box count ...", flush=True)
    t0 = time.time()
    active = min_trail(spec, ROUNDS)
    print(f"  A = {active.min_active_sboxes}  "
          f"(per-round {active.active_per_round}, {time.time() - t0:.2f}s)")
    print()

    A = active.min_active_sboxes
    w_lo = 6 * A
    w_hi = 7 * A

    print(f"Building incremental encoding (one-shot, w_hi={w_hi}) ...",
          flush=True)
    t_build = time.time()
    enc = build_encoding(layer, ddt, ROUNDS, w_hi)
    print(f"  built in {time.time() - t_build:.2f}s: vars={enc['top']}, "
          f"clauses={enc['nclauses']}, xors={enc['nxors']}", flush=True)

    t_start = time.time()
    W, result = solve_weighted(enc, w_lo, w_hi)
    wall = time.time() - t_start

    x_hex, y_hex, trail_rows, total_w = decode(
        result, ROUNDS, ddt, layer, W_target=W)

    print()
    print("=" * 72)
    print(f"Minimum-weight trail found: W = {W}")
    print(f"Differential probability:   2^-{W}")
    print(f"Active S-boxes:             {len(trail_rows)}")
    print(f"Wall time:                  {wall:.2f} s")
    print("=" * 72)
    print()

    print("States (each byte in hex, byte 0 on the left):")
    for r in range(ROUNDS + 1):
        print(f"  x[{r}] = {_fmt_state_hex_spaced(x_hex[r])}")
        if r < ROUNDS:
            print(f"  y[{r}] = {_fmt_state_hex_spaced(y_hex[r])}")
    print()

    print("Active-byte transitions:")
    print(f"  {'round':>5}  {'byte':>4}  {'δi':>5}  {'δo':>5}  {'w':>3}")
    for r, i, di, do, w in trail_rows:
        print(f"  {r:>5}  {i:>4}   0x{di:02x}   0x{do:02x}  {w:>3}")
    print(f"  {'total weight:':>30} {total_w}")

    # Full layered per-round trail with explicit probability factors.
    pretty_print_trail(x_hex, y_hex, trail_rows, ROUNDS, W)


if __name__ == "__main__":
    main()
