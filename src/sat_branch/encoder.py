"""CNF/XOR encoding of `y = L(x)`, non-zero input, and weight bounds."""
from __future__ import annotations

from dataclasses import dataclass, field

from .layer import LinearLayer


@dataclass
class Encoding:
    n: int
    x_vars: list[int] = field(default_factory=list)
    y_vars: list[int] = field(default_factory=list)
    # XOR clauses: list of (lits, rhs) with lits positive SAT var ids.
    xor_clauses: list[tuple[list[int], bool]] = field(default_factory=list)
    # Plain CNF clauses (DIMACS-style signed ints).
    clauses: list[list[int]] = field(default_factory=list)
    top_var: int = 0

    def fresh(self) -> int:
        self.top_var += 1
        return self.top_var

    def fresh_many(self, k: int) -> list[int]:
        out = list(range(self.top_var + 1, self.top_var + 1 + k))
        self.top_var += k
        return out


def build_base(layer: LinearLayer) -> Encoding:
    """Build encoding for y = L(x) and x != 0.

    Variable layout (1-indexed SAT vars):
      x_j -> 1 + j           for j = 0..n-1
      y_i -> 1 + n + i       for i = 0..n-1
    """
    n = layer.n
    enc = Encoding(n=n)
    enc.x_vars = [1 + j for j in range(n)]
    enc.y_vars = [1 + n + i for i in range(n)]
    enc.top_var = 2 * n

    # Linear layer: for each row i, XOR of its x dependencies equals y_i.
    #   y_i XOR (XOR_{j in deps_i} x_j) = 0
    for i in range(n):
        deps = layer.dependencies(i)
        lits = [enc.y_vars[i]] + [enc.x_vars[j] for j in deps]
        enc.xor_clauses.append((lits, False))

    # Non-zero input: at least one x bit is 1.
    enc.clauses.append(list(enc.x_vars))
    return enc


def add_atmost(enc: Encoding, lits: list[int], k: int) -> list[list[int]]:
    """Return CNF clauses enforcing sum(lits) <= k using a sequential counter.

    Sinz (2005). Introduces (m-1) * k fresh auxiliary vars where m = len(lits).
    Mutates `enc.top_var` but does NOT append clauses to `enc` — the caller
    decides whether to bake them in or add them per-iteration.
    """
    m = len(lits)
    if k < 0:
        return [[]]  # trivially UNSAT
    if k >= m:
        return []
    if k == 0:
        # All literals must be false.
        return [[-l] for l in lits]
    clauses: list[list[int]] = []

    # s[i][j] = 1 iff sum(lits[0..i]) >= j+1, for i=0..m-1, j=0..k-1.
    s: list[list[int]] = []
    for i in range(m - 1):  # last row of s not needed
        s.append(enc.fresh_many(k))

    # i = 0
    # lits[0] -> s[0][0]
    clauses.append([-lits[0], s[0][0]])
    # not s[0][j] for j >= 1  (only one bit can be set after one input)
    for j in range(1, k):
        clauses.append([-s[0][j]])

    # i = 1 .. m-2 (inclusive)
    for i in range(1, m - 1):
        # propagate: s[i-1][j] -> s[i][j]
        for j in range(k):
            clauses.append([-s[i - 1][j], s[i][j]])
        # lits[i] -> s[i][0]
        clauses.append([-lits[i], s[i][0]])
        # lits[i] AND s[i-1][j-1] -> s[i][j]
        for j in range(1, k):
            clauses.append([-lits[i], -s[i - 1][j - 1], s[i][j]])
        # forbid carry-out: lits[i] AND s[i-1][k-1] is forbidden
        clauses.append([-lits[i], -s[i - 1][k - 1]])

    # i = m - 1: only forbid exceeding k.
    # lits[m-1] must not co-occur with s[m-2][k-1] (would make total k+1).
    if m >= 2:
        clauses.append([-lits[m - 1], -s[m - 2][k - 1]])
    # If m == 1 and k >= 1, nothing to add; if k == 0, caller handled via
    # negating every literal below.

    return clauses
