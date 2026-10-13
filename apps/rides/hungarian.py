"""Minimum-cost assignment (Hungarian / Kuhn–Munkres algorithm with potentials), O(n²·m).

Batched dispatch collects the open requests and free drivers of the last few seconds and
assigns them all at once, minimising the *total* pickup time instead of greedily giving each
request its nearest driver (which can strand the next rider far from any car).
"""

import math

INF = math.inf


def solve(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Return ``(row, column)`` pairs minimising total cost.

    Works for rectangular matrices: each row is matched to at most one column and vice versa,
    and ``min(rows, columns)`` pairs are produced. Pairs whose cost is ``inf`` (forbidden) are
    left out of the result.
    """
    if not cost or not cost[0]:
        return []
    rows, cols = len(cost), len(cost[0])
    transposed = rows > cols
    if transposed:
        cost = [list(column) for column in zip(*cost, strict=True)]
        rows, cols = cols, rows

    # Replace inf with a large finite penalty so the algorithm stays numeric.
    finite = [c for row in cost for c in row if c != INF]
    big = (max(finite) if finite else 0) * (rows + 1) + 1e9
    a = [[big if c == INF else c for c in row] for row in cost]

    u = [0.0] * (rows + 1)
    v = [0.0] * (cols + 1)
    match_col = [0] * (cols + 1)  # match_col[j] = row (1-based) matched to column j
    way = [0] * (cols + 1)
    for i in range(1, rows + 1):
        match_col[0] = i
        j0 = 0
        min_v = [INF] * (cols + 1)
        used = [False] * (cols + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = match_col[j0], INF, 0
            for j in range(1, cols + 1):
                if not used[j]:
                    current = a[i0 - 1][j - 1] - u[i0] - v[j]
                    if current < min_v[j]:
                        min_v[j], way[j] = current, j0
                    if min_v[j] < delta:
                        delta, j1 = min_v[j], j
            for j in range(cols + 1):
                if used[j]:
                    u[match_col[j]] += delta
                    v[j] -= delta
                else:
                    min_v[j] -= delta
            j0 = j1
            if match_col[j0] == 0:
                break
        while True:
            j1 = way[j0]
            match_col[j0] = match_col[j1]
            j0 = j1
            if j0 == 0:
                break

    pairs = []
    for j in range(1, cols + 1):
        i = match_col[j]
        if i and cost[i - 1][j - 1] != INF:
            pairs.append((j - 1, i - 1) if transposed else (i - 1, j - 1))
    return sorted(pairs)


def total_cost(cost: list[list[float]], pairs: list[tuple[int, int]]) -> float:
    return sum(cost[i][j] for i, j in pairs)
