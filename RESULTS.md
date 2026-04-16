# Qalqan `lin344` — SAT-based Differential Analysis Report

Comprehensive SAT-based cryptanalysis of the `lin344` linear diffusion layer
used in the Qalqan block cipher, with a search over candidate rotation
constants `c0 = {c0[0], c0[1], c0[2]}` to identify choices that maximise
diffusion strength.

## 1. What was built

A Python toolkit (`sat_branch`) that turns differential questions about
bit-level linear layers and SPN ciphers into SAT instances, encodes them
using CryptoMiniSat's native XOR clauses, and solves them.

### Modules
| path | capability |
|---|---|
| [src/sat_branch/layer.py](src/sat_branch/layer.py) | parse `y_i = x_j XOR ROTL(x_k, r) ...` into a 128-bit `LinearLayer` |
| [src/sat_branch/encoder.py](src/sat_branch/encoder.py) | XOR/CNF construction, Sinz sequential-counter cardinality |
| [src/sat_branch/solver.py](src/sat_branch/solver.py) | CryptoMiniSat (native XOR) + PySAT backends |
| [src/sat_branch/branch.py](src/sat_branch/branch.py) | single-layer branch number & minimum-weight differentials |
| [src/sat_branch/spn.py](src/sat_branch/spn.py) | multi-round cell-level SPN (wide-trail) with nz-fix |
| [src/sat_branch/propagation.py](src/sat_branch/propagation.py) | bit-exact multi-round differential trails |
| [src/sat_branch/cli.py](src/sat_branch/cli.py) | `sat_branch {layer,spn,trail}` subcommands |

### Analyses implemented
1. **Bit-level branch number** `B = min w(dx)+w(dy)` over `dx ≠ 0`, `dy = L(dx)`.
2. **Minimum-weight differentials** — min `w(dx)`, min `w(dy)`, min sum;
   optional enumeration of all witnesses at the optimum.
3. **Byte-level branch number** — cell-activity version of (1), used to feed
   the wide-trail argument.
4. **SPN active S-box count over R rounds** (cell-level truncated model).
   Includes the `nz[r]` non-zero-state invariant that forbids non-physical
   "teleport through zero" trails — otherwise the truncated model is loose
   for full-state linear layers such as `lin344`.
5. **Bit-exact multi-round differential trails** — XOR-exact propagation of
   bit-level differences, byte-activity preservation at S-box boundaries.
   Delivers tight lower bounds on active S-boxes under any bijective S-box.

### Candidate search
- [examples/lin344_variants.py](examples/lin344_variants.py) — parametrised
  `lin344(c0)` builder.
- [examples/sweep_c0.py](examples/sweep_c0.py) — stage-1 cell-level sweep
  over a list of candidate triples.
- [examples/rank_best.py](examples/rank_best.py) — stage-1 + stage-2
  (bit-exact R=3) with incremental JSON cache.
- [examples/rank_r4.py](examples/rank_r4.py) — stage-3 bit-exact R=4 on a
  pre-selected list.

## 2. Validation of the toolkit

Classical wide-trail bounds reproduced exactly on AES
([tests/test_spn.py](tests/test_spn.py)):

| rounds | AES min active S-boxes |
|-------:|-----------------------:|
| 1      | 1                      |
| 2      | 5                      |
| 3      | 9                      |
| 4      | 25                     |

All 24 fast tests pass; 3 slow tests (AES R=4, `lin344` R≥2) pass under
`SAT_BRANCH_RUN_SLOW=1`.

## 3. Experiments on `lin344` with rotation-constant search

### Input
936 candidate `c0` triples (from `examples/c0.txt`) to evaluate as
replacements for the original `c0 = {1, 17, 14}`.

### Stage 1 — cell-level SPN sweep
Tool: [examples/sweep_c0.py](examples/sweep_c0.py). Ran the cell-level SPN
model on all 936 triples for R = 2, 3, 4. Output file:
[examples/c0_sweep_results.txt](examples/c0_sweep_results.txt).

Wall time: **290 s**.

Result — only two tiers appeared:

| tier | count | `B_bytes` | cR=2 | cR=3 | cR=4 |
|---|---:|---:|---:|---:|---:|
| **best** | 242 | 6 | 6 | 7 | 12 |
| weak | 694 | 5 | 5 | 6 | 10 |

The cell-level model cannot discriminate inside the 242-triple top tier
(all score identically). The original `{1, 17, 14}` falls in the **weak**
tier; `{1, 10, 15}` is in the **best** tier.

### Stage 2 — bit-exact R=3
Tool: [examples/rank_best.py](examples/rank_best.py). Applied the bit-exact
propagation model at R=3 to all 242 stage-1 winners. Output file:
[examples/c0_rank_R3_results.txt](examples/c0_rank_R3_results.txt).

Wall time: **5 h 39 min (≈20 340 s)**, cached incrementally.

Result — four distinct tiers appeared:

| bit-exact R=3 | count |
|---:|---:|
| **12** (best) | 24 |
| 11 | 151 |
| 10 | 46 |
| 9 | 21 |

The original `{1, 10, 15}` scores **R=3 = 9** (weakest bit-exact bucket).
The 24 top triples all score 12.

### Stage 3 — bit-exact R=4
Tool: [examples/rank_r4.py](examples/rank_r4.py). Applied bit-exact R=4 to
the 24 stage-2 winners plus the two reference triples `{1, 10, 15}` and
`{1, 17, 14}`. Output file:
[examples/c0_rank_R4_results.txt](examples/c0_rank_R4_results.txt).

Wall time: **3 h 39 min (≈13 150 s)**, cached.

Final result:

| c0 | R=3 | R=4 | per-round (R=4) |
|:---|---:|---:|:---|
| `{ 0,  8, 15}` | 12 | **16** | `[4, 3, 6, 3]` |
| `{ 0, 24, 17}` | 12 | **16** | `[4, 3, 6, 3]` |
| `{ 8,  8,  9}` | 12 | **16** | `[4, 3, 6, 3]` |
| `{ 8, 24,  7}` | 12 | **16** | `[4, 3, 6, 3]` |
| `{16,  8, 31}` | 12 | **16** | `[4, 3, 6, 3]` |
| `{16, 24,  1}` | 12 | **16** | `[4, 3, 6, 3]` |
| `{24,  8, 25}` | 12 | **16** | `[4, 3, 6, 3]` |
| `{24, 24, 23}` | 12 | **16** | `[4, 3, 6, 3]` |
| next 16 triples | 12 | 15 | varies |
| `{ 1, 10, 15}` |  9 | 12 | `[3, 3, 3, 3]` |
| `{ 1, 17, 14}` |  — | 12 | `[1, 6, 3, 2]` |

All 8 top triples share the exact same trail profile `[4, 3, 6, 3]` — a
strong hint that they are one **rotational-equivalence class** under the
8-bit cell boundary (each entry differs from another by a multiple of 8 in
specific slots, which permutes the bit rows of the 128-bit state by a byte
rotation but does not change the SPN's security profile against byte-level
S-boxes).

## 4. Key findings

1. **Byte-level branch number caps the 2-round bound.** On `lin344`,
   `B_bytes` is either 5 or 6 depending on `c0`. The original `{1, 17, 14}`
   gives 5; good choices give 6. This 5 vs 6 gap propagates into every
   multi-round bound.

2. **Truncated SPN teleport artefact was real and significant.** Before the
   `nz[r] ↔ OR(a[r])`, `nz[r+1] = nz[r]` fix, the truncated SPN model gave
   the flat bound 6 for any R ≥ 2 — meaningless. After the fix, meaningful
   linear growth appears (7 at R=3, 12 at R=4 for `c0 = {1, 10, 15}`).

3. **The truncated SPN model is a strict lower bound; the bit-exact model
   reveals it is loose.** For the 242 cell-level-BEST triples that all
   score `cR3 = 7`, bit-exact R=3 yields values spanning **9 to 12**.
   Ignoring the actual XOR equations of `lin344` costs ≥ 2 active S-boxes
   at R=3 in the best case, up to 5 in the worst.

4. **Switching from the original `c0 = {1, 17, 14}` to any of the 8 top
   triples raises the guaranteed 4-round active S-box count from 12 to 16,
   a +33% improvement**, holding `lin344`'s algebraic structure otherwise
   identical. Over a full cipher of ~10 rounds this compounds to a
   meaningful security margin against differential cryptanalysis.

5. **`{1, 10, 15}` is a cell-level BEST but bit-exact WEAK.** It ties with
   top triples on cell-level metrics (`B_bytes=6`, `cR4=12`) but scores
   only 9 at bit-exact R=3 — 3 active S-boxes less than the top class. A
   pure cell-level analysis would have missed this.

## 5. Open directions

1. **Confirm rotational equivalence of the 8 winners.** Check if each pair
   differs by a byte-rotation of the input state. If so the real answer is
   one equivalence class, so any representative can be picked on other
   criteria (hardware cost, implementation simplicity).

2. **Tie-break the 8 winners at R=5 bit-exact.** At current solve speeds
   R=5 is roughly 20 min per triple × 8 ≈ 2.5 h; feasible if the
   rotational-equivalence check does not already collapse them.

3. **Plug in the real Qalqan S-box DDT.** The current bit-exact model is
   oblivious to which non-zero difference maps to which (any bijection is
   admissible). Adding DDT tables would weight trails by differential
   probability and yield the exact differential bound `max_pr ≤ 2^{-k}`.

4. **Linear trails.** Same scaffolding, swap "differential branch number"
   for the linear branch number. Also of interest: integral / structural
   distinguishers.

5. **Qalqan-specific extensions.** The present tool analyses SubBytes +
   `lin344`. A full Qalqan round includes key schedule and potentially
   other layers; modelling those would sharpen the bound further.

6. **Broader candidate space.** The 936 triples in `c0.txt` were pre-
   filtered; a more exhaustive sweep (e.g. all `0 ≤ a < b < c ≤ 31`
   with some shift diversity constraint) is feasible overnight with the
   existing infrastructure.

## 6. Reproduction

```bash
pip install -e .[cms,dev]
pytest                                              # sanity
python examples/run_all_checks.py 1 17 14           # one-shot diagnostic
python examples/sweep_c0.py --rounds 2 3 4          # stage 1
python examples/rank_best.py --rounds-bit 3         # stages 1 + 2
python examples/rank_r4.py                          # stage 3
```

The JSON cache at [examples/c0_rank_cache.json](examples/c0_rank_cache.json)
holds every solve from the study; re-running any of the above skips
already-cached entries.

## 7. Timing summary

| stage | work | wall time |
|---|---|---:|
| 1 | cell-level SPN × 936 triples (R=2..4) | 290 s |
| 2 | bit-exact R=3 × 242 top-tier triples | 5 h 39 min |
| 3 | bit-exact R=4 × 26 triples (24 + 2 refs) | 3 h 39 min |
| — | **total SAT work** | **≈ 9 h 23 min** |

Hardware: CryptoMiniSat native build on the development machine.
