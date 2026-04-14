from sat_branch.layer import LinearLayer


def test_identity_matrix():
    m = [[1 if i == j else 0 for j in range(4)] for i in range(4)]
    L = LinearLayer.from_matrix(m)
    assert L.n == 4
    for x in range(16):
        assert L.apply(x) == x


def test_roundtrip_matrix():
    m = [
        [1, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 1, 1],
        [1, 0, 0, 1],
    ]
    L = LinearLayer.from_matrix(m)
    assert L.to_matrix() == m


def test_operations_parse():
    ops = [
        "y0 = x0 XOR x1",
        "y1 = x1 XOR ROTL(x0, 1)",  # x_{(0+1) mod 3} = x1, XOR x1 cancels
        "y2 = ROTR(x0, 1) XOR x2",  # x_{(0-1) mod 3} = x2
    ]
    L = LinearLayer.from_operations(ops, 3)
    # y0 = x0 XOR x1 -> row mask 0b011 = 3
    assert L.rows[0] == 0b011
    # y1 = x1 XOR x1 = 0
    assert L.rows[1] == 0
    # y2 = x2 XOR x2 = 0
    assert L.rows[2] == 0


def test_apply_matches_matrix():
    import random
    random.seed(0)
    n = 6
    m = [[random.randint(0, 1) for _ in range(n)] for _ in range(n)]
    L = LinearLayer.from_matrix(m)
    # brute-force multiply
    for x in range(1 << n):
        y_ref = 0
        for i in range(n):
            bit = 0
            for j in range(n):
                if m[i][j]:
                    bit ^= (x >> j) & 1
            y_ref |= bit << i
        assert L.apply(x) == y_ref
