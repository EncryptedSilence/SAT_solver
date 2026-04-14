"""Linear layer representation and parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass
class LinearLayer:
    n: int
    # rows[i] is a bitmask: bit j set means y_i depends on x_j
    rows: list[int]

    def __post_init__(self) -> None:
        if len(self.rows) != self.n:
            raise ValueError(f"expected {self.n} rows, got {len(self.rows)}")
        mask = (1 << self.n) - 1
        for i, r in enumerate(self.rows):
            if r & ~mask:
                raise ValueError(f"row {i} has bits outside range")

    def dependencies(self, i: int) -> list[int]:
        """Return sorted list of input-bit indices that y_i depends on."""
        r = self.rows[i]
        out = []
        j = 0
        while r:
            if r & 1:
                out.append(j)
            r >>= 1
            j += 1
        return out

    def apply(self, x: int) -> int:
        """Apply layer to a packed input bitvector (bit j is x_j)."""
        y = 0
        for i, r in enumerate(self.rows):
            bit = (x & r).bit_count() & 1
            y |= bit << i
        return y

    @classmethod
    def from_matrix(cls, matrix: list[list[int]]) -> "LinearLayer":
        n = len(matrix)
        rows: list[int] = []
        for i, row in enumerate(matrix):
            if len(row) != n:
                raise ValueError(f"row {i} length {len(row)} != n={n}")
            r = 0
            for j, v in enumerate(row):
                if v not in (0, 1):
                    raise ValueError(f"matrix[{i}][{j}] must be 0/1")
                if v:
                    r |= 1 << j
            rows.append(r)
        return cls(n=n, rows=rows)

    def to_matrix(self) -> list[list[int]]:
        out = []
        for r in self.rows:
            out.append([(r >> j) & 1 for j in range(self.n)])
        return out

    # --- operation-form parsing ---------------------------------------------
    _LHS = re.compile(r"^\s*y(\d+)\s*=\s*(.+?)\s*$", re.IGNORECASE)
    _XVAR = re.compile(r"^\s*x(\d+)\s*$", re.IGNORECASE)
    _ROT = re.compile(r"^\s*ROT([LR])\s*\(\s*x(\d+)\s*,\s*(-?\d+)\s*\)\s*$",
                      re.IGNORECASE)

    @classmethod
    def from_operations(cls, ops: Iterable[str], n: int) -> "LinearLayer":
        rows = [0] * n
        seen = [False] * n
        for raw in ops:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = cls._LHS.match(line)
            if not m:
                raise ValueError(f"cannot parse: {raw!r}")
            i = int(m.group(1))
            if not 0 <= i < n:
                raise ValueError(f"y{i} out of range")
            if seen[i]:
                raise ValueError(f"y{i} defined twice")
            seen[i] = True
            terms = [t.strip() for t in re.split(r"\bXOR\b|\^", m.group(2),
                                                  flags=re.IGNORECASE)]
            mask = 0
            for t in terms:
                if not t:
                    continue
                xm = cls._XVAR.match(t)
                if xm:
                    j = int(xm.group(1))
                else:
                    rm = cls._ROT.match(t)
                    if not rm:
                        raise ValueError(f"unrecognized term {t!r}")
                    direction = rm.group(1).upper()
                    j0 = int(rm.group(2))
                    r = int(rm.group(3))
                    if direction == "L":
                        j = (j0 + r) % n
                    else:
                        j = (j0 - r) % n
                if not 0 <= j < n:
                    raise ValueError(f"x{j} out of range")
                mask ^= 1 << j  # XOR so duplicates cancel
            rows[i] = mask
        for i, s in enumerate(seen):
            if not s:
                raise ValueError(f"y{i} not defined")
        return cls(n=n, rows=rows)
