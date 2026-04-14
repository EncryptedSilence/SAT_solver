"""SAT solver backend abstraction."""
from __future__ import annotations

from typing import Optional


class SolverBackend:
    """Protocol-style base class."""

    name: str = "base"

    def add_clause(self, clause: list[int]) -> None: ...
    def add_xor(self, lits: list[int], rhs: bool) -> None: ...
    def solve(self, assumptions: Optional[list[int]] = None) -> bool: ...
    def model(self) -> list[int]: ...


class CMSBackend(SolverBackend):
    """CryptoMiniSat backend via pycryptosat. Native XOR clauses."""

    name = "cms"

    def __init__(self) -> None:
        import pycryptosat  # type: ignore
        self._s = pycryptosat.Solver()
        self._model: Optional[tuple] = None
        self._nvars = 0

    def _bump(self, v: int) -> None:
        self._nvars = max(self._nvars, v)

    def add_clause(self, clause: list[int]) -> None:
        for l in clause:
            self._bump(abs(l))
        self._s.add_clause(clause)

    def add_xor(self, lits: list[int], rhs: bool) -> None:
        # pycryptosat: add_xor_clause(lits, rhs) — lits must be positive,
        # rhs is True/False meaning XOR == rhs.
        for l in lits:
            if l <= 0:
                raise ValueError("CMS add_xor requires positive var ids")
            self._bump(l)
        self._s.add_xor_clause(lits, rhs)

    def solve(self, assumptions: Optional[list[int]] = None) -> bool:
        sat, sol = self._s.solve(assumptions or [])
        if sat:
            self._model = sol
        else:
            self._model = None
        return bool(sat)

    def model(self) -> list[int]:
        if self._model is None:
            raise RuntimeError("no model")
        # pycryptosat returns tuple where index v holds bool (index 0 unused).
        out = []
        for v in range(1, self._nvars + 1):
            val = self._model[v]
            out.append(v if val else -v)
        return out


class PySATBackend(SolverBackend):
    """Fallback using python-sat; XORs expanded via Tseitin."""

    name = "pysat"

    def __init__(self, engine: str = "cms") -> None:
        from pysat.solvers import Solver  # type: ignore
        self._s = Solver(name=engine)
        self._model: Optional[list[int]] = None
        self._nvars = 0
        # Tseitin aux var counter — caller must avoid colliding. We track and
        # return fresh vars via allocate_aux().
        self._aux_next: Optional[int] = None

    def set_top_var(self, top: int) -> None:
        """Tell backend current highest in-use var so aux allocation is safe."""
        self._aux_next = top + 1
        self._nvars = max(self._nvars, top)

    def _alloc(self) -> int:
        if self._aux_next is None:
            raise RuntimeError("call set_top_var() before add_xor")
        v = self._aux_next
        self._aux_next += 1
        self._nvars = max(self._nvars, v)
        return v

    def _bump(self, v: int) -> None:
        self._nvars = max(self._nvars, v)

    def add_clause(self, clause: list[int]) -> None:
        for l in clause:
            self._bump(abs(l))
        self._s.add_clause(clause)

    def add_xor(self, lits: list[int], rhs: bool) -> None:
        # Build chained 2-input XOR gates.
        for l in lits:
            self._bump(abs(l))
        if not lits:
            if rhs:
                self._s.add_clause([])  # UNSAT
            return
        if len(lits) == 1:
            v = lits[0]
            self._s.add_clause([v if rhs else -v])
            return
        acc = lits[0]
        for nxt in lits[1:-1]:
            new = self._alloc()
            # new = acc XOR nxt
            self._emit_xor_eq(new, acc, nxt)
            acc = new
        last = lits[-1]
        # acc XOR last = rhs   =>   acc = rhs XOR last
        # encode: (acc XOR last) == rhs
        if rhs:
            # acc != last: (acc v last) & (-acc v -last)
            self._s.add_clause([acc, last])
            self._s.add_clause([-acc, -last])
        else:
            # acc == last
            self._s.add_clause([-acc, last])
            self._s.add_clause([acc, -last])

    def _emit_xor_eq(self, z: int, a: int, b: int) -> None:
        # z = a XOR b
        self._s.add_clause([-z, a, b])
        self._s.add_clause([-z, -a, -b])
        self._s.add_clause([z, -a, b])
        self._s.add_clause([z, a, -b])

    def solve(self, assumptions: Optional[list[int]] = None) -> bool:
        ok = self._s.solve(assumptions=assumptions or [])
        self._model = self._s.get_model() if ok else None
        return bool(ok)

    def model(self) -> list[int]:
        if self._model is None:
            raise RuntimeError("no model")
        return list(self._model)


def make_backend(name: str) -> SolverBackend:
    name = name.lower()
    if name == "cms":
        try:
            return CMSBackend()
        except ImportError:
            import warnings
            warnings.warn("pycryptosat not available; falling back to pysat")
            return PySATBackend(engine="glucose3")
    if name == "pysat":
        return PySATBackend(engine="glucose3")
    if name.startswith("pysat:"):
        return PySATBackend(engine=name.split(":", 1)[1])
    raise ValueError(f"unknown backend: {name}")
