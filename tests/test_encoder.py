"""Brute-force check the sequential-counter atmost encoding."""
from itertools import product

from sat_branch.encoder import Encoding, add_atmost


def _satisfies(clauses, assignment):
    for c in clauses:
        ok = False
        for lit in c:
            v = abs(lit)
            val = assignment.get(v, False)
            if (lit > 0 and val) or (lit < 0 and not val):
                ok = True
                break
        if not ok:
            return False
    return True


def test_atmost_small():
    for m in range(1, 6):
        for k in range(0, m + 1):
            enc = Encoding(n=0, top_var=m)  # reserve 1..m for inputs
            lits = list(range(1, m + 1))
            clauses = add_atmost(enc, lits, k)
            # Enumerate all 2^m assignments of inputs; for each, check
            # consistency: there MUST exist some aux assignment making clauses
            # true iff popcount(inputs) <= k.
            aux_vars = list(range(m + 1, enc.top_var + 1))
            for bits in product([False, True], repeat=m):
                popcount = sum(bits)
                allowed = popcount <= k
                # Search aux assignments
                found = False
                for aux in product([False, True], repeat=len(aux_vars)):
                    asn = {lits[i]: bits[i] for i in range(m)}
                    for i, v in enumerate(aux_vars):
                        asn[v] = aux[i]
                    if _satisfies(clauses, asn):
                        found = True
                        break
                assert found == allowed, (
                    f"m={m} k={k} bits={bits} allowed={allowed} "
                    f"found={found}"
                )
