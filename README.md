# sat-branch

SAT-based cryptanalysis toolkit for bit-level linear diffusion layers and
SPN ciphers. Computes exact differential bounds that can be checked,
reproduced, and plugged into wide-trail arguments.

Given a bit-level linear layer `L: F2^n -> F2^n` and (optionally) an S-box
layer on top, `sat-branch` can compute:

1. **Branch number** of `L` — min `w(dx) + w(dy)` with `dy = L(dx)`, `dx ≠ 0`.
2. **Minimum-weight differentials** — min `w(dx)`, min `w(dy)`, min sum.
   Optionally enumerate all witnesses at the optimum.
3. **Byte/cell-level branch number** — the activity-counting variant used in
   wide-trail analysis.
4. **Active S-box counts over R rounds** (cell-level SPN model with
   non-zero-state preservation — no "teleport through zero" artefacts).
5. **Bit-exact multi-round differential trails** — XOR-exact propagation
   through `L` with bijective S-boxes, delivering true lower bounds on the
   active-S-box count.

## Install

```bash
pip install -e .[cms,dev]
```

- Primary backend: [pycryptosat](https://github.com/msoos/cryptominisat)
  (native XOR clauses — strongly preferred for XOR-heavy layers).
- Fallback: [python-sat](https://pysathq.github.io/) (Glucose3 by default).

## CLI

Three subcommands:

```bash
# 1) Single-layer min-weight / branch number
sat_branch layer --input examples/identity_8.json
sat_branch layer --input examples/rotxor_8.json --objective input --enumerate

# 2) Multi-round active S-box count (cell-level SPN, truncated model)
sat_branch spn --input examples/aes_spn.json --rounds 4

# 3) Bit-exact multi-round differential trail
sat_branch trail --input examples/rotxor_8.json --rounds 2 --cell-bits 4
```

If no subcommand is given, `layer` is assumed (backwards compatible).

### `layer` flags
| flag | meaning |
|---|---|
| `--input PATH` | layer JSON (matrix or operations) |
| `--objective {sum,input,output}` | minimise `w(dx)+w(dy)`, `w(dx)`, or `w(dy)` (default `sum` = branch number) |
| `--enumerate` | emit every differential at the optimum |
| `--solver {cms,pysat,pysat:<engine>}` | SAT backend |
| `--max-k N` | cap on weight search |
| `--fix-first` | assert `x_0 = 1` (symmetry break; only valid for rotation-invariant layers) |

### `spn` flags
| flag | meaning |
|---|---|
| `--input PATH` | SPN cipher JSON (type `"spn"`) |
| `--rounds R` | number of S-box layers |
| `--solver`, `--max-k` | as above |

### `trail` flags
| flag | meaning |
|---|---|
| `--input PATH` | linear-layer JSON (matrix or operations) |
| `--rounds R` | number of S-box layers |
| `--cell-bits B` | S-box width (default 8) |
| `--solver`, `--max-k` | as above |

## Input formats

### Linear layer — matrix

```json
{ "n": 4, "matrix": [[1,1,0,0],[0,1,1,0],[0,0,1,1],[1,0,0,1]] }
```

Entry `matrix[i][j] = 1` means `y_i` depends on `x_j`.

### Linear layer — operations

```json
{
  "n": 8,
  "operations": [
    "y0 = x0 XOR ROTL(x0, 1) XOR ROTL(x0, 3)",
    "..."
  ]
}
```

`ROTL(x_k, r)` is shorthand for `x_{(k+r) mod n}`; `ROTR(x_k, r)` for
`x_{(k-r) mod n}`. `^` may be used instead of `XOR`.

### SPN cipher

```json
{
  "type": "spn",
  "cell_bits": 8,
  "n_cells": 16,
  "columns": [
    {"input_cells": [0,5,10,15], "output_cells": [0,1,2,3], "branch_number": 5},
    ...
  ]
}
```

Each `column` is one parallel linear sub-block; `branch_number` is the
cell-level branch number of that sub-block. See
[examples/aes_spn.json](examples/aes_spn.json) for AES's
ShiftRows+MixColumns structure.

## Output

### `layer`
```json
{
  "objective": "sum",
  "minimum_weight": 6,
  "branch_number": 6,
  "input_diff": "bitstring",
  "output_diff": "bitstring"
}
```
Character index `i` of each bitstring is bit `i` (so `x_0` is leftmost).
With `--enumerate`: `{ "minimum_weight": k, "count": N, "differentials": [...] }`.

### `spn`
```json
{
  "rounds": 4,
  "min_active_sboxes": 25,
  "trail": [[0,5,10,15], [0,1,2,3], ...]
}
```

### `trail`
```json
{
  "rounds": 2,
  "min_active_sboxes": 6,
  "active_per_round": [3, 3],
  "active_bytes_x": [[...], [...], [...]],
  "x_states": ["bitstring", ...],
  "y_states": ["bitstring", ...]
}
```

## Modelling notes

**SPN cell-level model** enforces, per round *r* and per column:

> all cells in the column inactive, **or** at least *B* active.

The model also asserts a non-zero-state invariant via per-round indicators:
`nz[r] ↔ OR(a[r][*])` and `nz[r+1] = nz[r]`. This forbids
"teleport through zero" trails that would otherwise exploit the truncated
model — important for full-state linear layers like `lin344` that have only
one column.

**Bit-exact propagation** (`trail`) uses:
- XOR-exact `x[r+1] = L(y[r])` at bit level (no truncation).
- Bijective S-box: byte-activity preserved (`bx[r][i] ↔ by[r][i]`).

Values of individual bits of `y[r]` are otherwise unconstrained — any
bijective S-box is admissible. This gives a valid lower bound for any
specific S-box choice; plug a DDT in for the exact bound (future feature).

## Run everything

The script [examples/run_all_checks.py](examples/run_all_checks.py) runs
every analysis on a parametrised `lin344` variant:

```bash
python examples/run_all_checks.py                 # default c0 = 1 10 15
python examples/run_all_checks.py 1 17 14         # custom c0
python examples/run_all_checks.py 1 17 14 --rounds 4 --slow   # also R=3,4 bit-exact
```

Typical outputs for the two Qalqan `c0` choices:

| Check | `c0 = {1,10,15}` | `c0 = {1,17,14}` |
|---|---:|---:|
| Bit-level branch number | 6 | 6 |
| Byte-level branch number | **6** | **5** |
| SPN R=2 | 6 | 5 |
| SPN R=4 | 12 | 10 |
| Bit-exact R=2 | 6 | 5 |

The `{1,17,14}` variant is strictly weaker at the byte level — one fewer
guaranteed active S-box per 2 rounds.

## Tests

```bash
pytest                      # fast tests
SAT_BRANCH_RUN_SLOW=1 pytest   # also run slow multi-round bounds (lin344 R≥3, AES R=4)
```

## Modules

| path | what it does |
|---|---|
| [src/sat_branch/layer.py](src/sat_branch/layer.py) | `LinearLayer` — parse matrix / operations form |
| [src/sat_branch/encoder.py](src/sat_branch/encoder.py) | CNF/XOR encoding, sequential-counter cardinality |
| [src/sat_branch/solver.py](src/sat_branch/solver.py) | CMS + PySAT backend abstraction |
| [src/sat_branch/branch.py](src/sat_branch/branch.py) | `min_weight`, `branch_number` |
| [src/sat_branch/spn.py](src/sat_branch/spn.py) | `min_active_sboxes` — cell-level SPN model |
| [src/sat_branch/propagation.py](src/sat_branch/propagation.py) | `min_trail` — bit-exact multi-round |
| [src/sat_branch/io.py](src/sat_branch/io.py) | JSON loaders |
| [src/sat_branch/cli.py](src/sat_branch/cli.py) | command-line entry point |
