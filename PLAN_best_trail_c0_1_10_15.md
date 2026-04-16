# DDT-aware minimum-weight differential trail for `lin344`, c0=(1,10,15), R=3

Single standalone script, hardcoded constants.

## Context

The toolkit at `d:\CPP\SAT_solver` already finds the minimum *active-S-box
count* per-round bit-exact (`min_trail` in
[src/sat_branch/propagation.py](src/sat_branch/propagation.py)).
For c0=(1,10,15) at R=3 that count is 9. What is missing is the actual
**probability** of the best differential — i.e. the minimum of the trail
weight `W = Σ -log2(DDT[δi][δo]/256)` over all valid 3-round trails with the
AES S-box.

Goal: obtain the exact minimum-weight trail for c0=(1,10,15), R=3, AES S-box.
DDT entries are `{0, 2, 4}`, so per-S-box weight ∈ `{6, 7}` and the total is
between `6·9 = 54` and `7·9 = 63`.

### Note on speed / "would C/C++ be faster"

No. The SAT solver itself is already native C++ (CryptoMiniSat via
`pycryptosat`). Python here only *emits* the CNF — a one-time cost dwarfed
by the solver's own search. Real speed levers are encoding-quality and
incremental solving, not language choice. Hardcoding c0=(1,10,15) is a
readability / ergonomics win, not a speed win — but it does let us keep
everything in one file and tune it without round-tripping through the
package API.

## Approach

One self-contained script. No changes to the `sat_branch` package. The
script imports only `LinearLayer` (and optionally `CMSBackend` directly)
from `sat_branch`; everything else — DDT, encoding, objective, decoding,
pretty-print — lives in the script.

### File — `examples/best_trail_c0_1_10_15.py` (new)

Contents, top to bottom:

1. **Hardcoded constants**
   - `C0 = (1, 10, 15)`
   - `ROUNDS = 3`
   - `N = 128`, `CELL_BITS = 8`, `NB = 16`
   - `AES_SBOX = (...)` — 256-byte tuple inline.

2. **Inline `build_lin344(c0)`** — reproduces `build_layer` from
   [examples/lin344_variants.py](examples/lin344_variants.py)
   (copy the ~15 lines; independence > DRY for a one-shot script).

3. **`build_ddt(sbox) -> list[list[int]]`** — classical 256×256 DDT.

4. **`partition(ddt) -> (w6_pairs, w7_pairs, forbidden)`** — three lists of
   `(δi, δo)` with δi ≠ 0, split by DDT value (4 / 2 / 0).

5. **Solver loop `solve_weighted(layer, ddt, rounds, w_lo, w_hi)`** — builds
   the encoding fresh per target W and calls CMS. Pseudocode:

   ```python
   for W in range(w_lo, w_hi + 1):
       top = 0
       def fresh(k=1): ...                        # allocates k vars, bumps top

       x  = [[fresh() for _ in range(N)] for _ in range(rounds + 1)]
       y  = [[fresh() for _ in range(N)] for _ in range(rounds)]
       bx = [[fresh() for _ in range(NB)] for _ in range(rounds + 1)]
       by = [[fresh() for _ in range(NB)] for _ in range(rounds)]
       w6 = [[fresh() for _ in range(NB)] for _ in range(rounds)]
       w7 = [[fresh() for _ in range(NB)] for _ in range(rounds)]
       # iv[r][i][δi] for δi in 1..255  (255 × NB × rounds = 12 240 aux vars)
       iv = [[[fresh() for _ in range(256)] for _ in range(NB)] for _ in range(rounds)]
       # (iv[...][0] is unused; kept for indexing clarity)

       clauses, xors = [], []

       # --- byte-activity for x/y ---
       # bx[r][i] == OR(bits of byte i of x[r]); ditto by.
       # --- s-box bijection: bx[r][i] <-> by[r][i] ---
       # --- linear layer: x[r+1] = L(y[r])  (XOR clauses) ---
       # --- non-zero input: OR(x[0]) ---
       #     these four blocks are ports of propagation.py:97-116

       # --- DDT constraints per (r, i) ---
       for r in range(rounds):
           for i in range(NB):
               # weight vars tied to activity:
               clauses += [[-w6[r][i], bx[r][i]],
                           [-w7[r][i], bx[r][i]],
                           [-bx[r][i], w6[r][i], w7[r][i]],
                           [-w6[r][i], -w7[r][i]]]

               xb = x[r][CELL_BITS*i : CELL_BITS*(i+1)]
               yb = y[r][CELL_BITS*i : CELL_BITS*(i+1)]

               # iv[δi] <-> (x-byte == δi)
               for di in range(1, 256):
                   lit_iv = iv[r][i][di]
                   # x-byte == di iff bit_b == ((di >> b) & 1) for all b
                   # one-way: (x-byte == di) -> iv ; reverse: iv -> x-byte == di
                   pattern = [xb[b] if ((di >> b) & 1) else -xb[b] for b in range(CELL_BITS)]
                   # iv -> each bit matches:   [-iv, pattern[b]]
                   for lit in pattern:
                       clauses.append([-lit_iv, lit])
                   # all bits match -> iv:     [-pattern..., iv]
                   clauses.append([-p for p in pattern] + [lit_iv])

               # for each (di, do): emit forbidden / w6 / w7 clause
               for di in range(1, 256):
                   lit_iv = iv[r][i][di]
                   for do in range(256):
                       yneg = [-yb[b] if ((do >> b) & 1) else yb[b] for b in range(CELL_BITS)]
                       # clause means: NOT (x-byte == di AND y-byte == do)  OR  extra
                       base = [-lit_iv] + yneg
                       v = ddt[di][do]
                       if v == 0:
                           clauses.append(base)                 # forbidden
                       elif v == 4:
                           clauses.append(base + [w6[r][i]])
                       elif v == 2:
                           clauses.append(base + [w7[r][i]])
                       # v == 256 impossible for di != 0
                       # other even values don't occur in AES DDT

       # --- objective: Σ (6·w6 + 7·w7) <= W  via duplicated-literal Sinz ---
       obj = []
       for r in range(rounds):
           for i in range(NB):
               obj += [w6[r][i]] * 6 + [w7[r][i]] * 7
       clauses += sinz_atmost(obj, W, fresh)

       backend = CMSBackend()
       load(backend, xors, clauses, top)
       if backend.solve():
           return W, decode(backend.model(), x, y, bx, rounds, ddt)
   raise RuntimeError("no trail within bounds")
   ```

6. **`sinz_atmost(lits, k, fresh)`** — inline Sinz sequential counter
   (port of [encoder.py:55](src/sat_branch/encoder.py#L55)).
   Handles duplicated literals correctly since it treats each position
   independently.

7. **`decode(model, x, y, bx, rounds, ddt)`** — builds per-round bit strings,
   assembles active-byte transitions `(r, i, δi, δo, weight)`, asserts
   `Σ weights == W`.

8. **`main()`**
   - `layer = build_lin344(C0)`
   - `ddt = build_ddt(AES_SBOX)`
   - `W, trail = solve_weighted(layer, ddt, ROUNDS, w_lo=54, w_hi=63)`
   - Pretty-print:
     - Per round: `x[r]` and `y[r]` as 32 hex chars (MSB-of-state on the left
       or LSB-first — pick one and document in header comment).
     - Active-byte table: `round | byte | δi (hex) | δo (hex) | weight`.
     - Total weight, probability `2^-W`, wall time.

### Optional second pass (leave TODOs in code, don't implement yet)

- **Valid-output-set aux** per `(r, i, δi)`: one extra literal
  `ok[r][i][δi]` that's true iff `y-byte ∈ {δo : DDT[δi][δo] > 0}`.
  Clause count drops from ~65k → ~1k per byte-position, ~3M → ~50k total.
- **Incremental CMS** via `pycryptosat.Solver(...).solve(assumptions=...)`
  with a single encoding and W driven by assumption literals on the Sinz
  output bits. Removes the rebuild-per-W cost.
- **Binary-search on W**: given the linear lower bound 54 and upper 63, a
  ≤4-call binary search beats linear scan if solve times are symmetric.

## Size / expected runtime

- Vars: ~12 500 (mostly `iv`).
- Clauses: ~3.1M (dominant: DDT forbidden + weight-assignment).
- CNF emission in Python: ~5-15 s.
- Per-W solve: unknown a priori. If UNSAT at W=54 comes back in minutes and
  SAT hits at W=60 or so, total wall time is under an hour. If much slower,
  fall back to the valid-output-set aux — quoted in a code comment.

## Verification

1. `python examples/best_trail_c0_1_10_15.py`
   - Prints `W ∈ [54, 63]` and 9 active S-boxes.
   - Every `(δi, δo)` satisfies `DDT[δi][δo] ∈ {2, 4}`.
   - Every `y[r]` propagates through `build_lin344((1,10,15))` to `x[r+1]`
     exactly (self-check emitted at the bottom of `main`).
2. Cross-check: re-run existing
   `python examples/rank_r4.py` or invoke `min_trail(spec, 3)` — should
   report `min_active_sboxes == 9`.
3. Smoke-test DDT: `ddt[0][0] == 256`, all rows sum to 256, value set is
   `{0, 2, 4, 256}`. Embed as two `assert` lines at start of `main`.

## Risks & fallbacks

- **Clause-count blowup** → swap DDT section for the valid-output-set aux
  encoding sketched above (one code edit, ~30 lines).
- **Sinz on duplicated literals** correct but not tight; if the boundary W
  is slow, bisect on W or add a totalizer.
- **Single-file script drifts from package conventions** — acceptable for
  one-off experiments; if results are worth keeping, port back to a proper
  `min_weight_trail` in `propagation.py` as a follow-up.

## Critical files

- `examples/best_trail_c0_1_10_15.py` — **new**, self-contained.
- [src/sat_branch/layer.py](src/sat_branch/layer.py) — reused for
  `LinearLayer` only.
- [src/sat_branch/solver.py](src/sat_branch/solver.py) — reused for
  `CMSBackend`.
- [src/sat_branch/encoder.py](src/sat_branch/encoder.py) — referenced for
  the Sinz port; not modified.
- [src/sat_branch/propagation.py](src/sat_branch/propagation.py) —
  referenced for byte-activity / bijection / XOR-layer blocks being ported;
  not modified.
