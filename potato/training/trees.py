"""Maximum spanning arborescence (Chu-Liu-Edmonds), for dependency decoding.

A dependency parser scores every possible head for every word; picking each
word's best head independently can leave a word with no path to the root,
or two words heading each other. The tree that maximizes the total score
under the constraint that it is a tree is a maximum spanning arborescence,
which Chu-Liu-Edmonds finds by contracting cycles.

Standard library only. Node 0 is the root; ``scores[h][d]`` is the score of
``h`` heading ``d``. Sentences are short, so the simple recursive form is
fast enough.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

__all__ = ["max_spanning_tree"]

NEG = float("-inf")


def max_spanning_tree(scores: Sequence[Sequence[float]],
                      single_root: bool = True) -> List[Optional[int]]:
    """Each node's head, ``heads[0]`` is None.

    With *single_root*, exactly one node is attached to the root, as in a
    dependency tree: the best tree is found once per possible root child and
    the highest-scoring one kept.
    """
    n = len(scores)
    if n <= 1:
        return [None] * n
    if not single_root:
        return _cle([list(row) for row in scores])
    best, best_heads = NEG, None
    for child in range(1, n):
        if scores[0][child] == NEG:
            continue
        matrix = [list(row) for row in scores]
        for other in range(1, n):
            if other != child:
                matrix[0][other] = NEG
        heads = _cle(matrix)
        total = sum(scores[h][d] for d, h in enumerate(heads) if h is not None)
        if total > best:
            best, best_heads = total, heads
    return best_heads if best_heads is not None else _cle([list(r) for r in scores])


def _cle(scores: List[List[float]]) -> List[Optional[int]]:
    n = len(scores)
    heads: List[Optional[int]] = [None] * n
    for d in range(1, n):
        candidates = [(scores[h][d], h) for h in range(n) if h != d]
        heads[d] = max(candidates)[1]
    cycle = _find_cycle(heads)
    if cycle is None:
        return heads

    # Contract the cycle into one node, c, and solve the smaller problem.
    in_cycle = set(cycle)
    cycle_score = sum(scores[heads[v]][v] for v in cycle)
    outside = [v for v in range(n) if v not in in_cycle]
    index = {v: i for i, v in enumerate(outside)}
    c = len(outside)
    size = c + 1
    small = [[NEG] * size for _ in range(size)]
    enter_from = {}          # outside head -> (cycle node it enters)
    leave_to = {}            # outside dependent -> (cycle node that heads it)
    for u in outside:
        for v in outside:
            if u != v:
                small[index[u]][index[v]] = scores[u][v]
        # An arc into the cycle replaces the cycle arc into its target.
        best, best_v = NEG, None
        for v in cycle:
            value = scores[u][v] - scores[heads[v]][v] + cycle_score
            if value > best:
                best, best_v = value, v
        small[index[u]][c] = best
        enter_from[u] = best_v
        # An arc out of the cycle comes from its best cycle node.
        best, best_v = NEG, None
        for v in cycle:
            if scores[v][u] > best:
                best, best_v = scores[v][u], v
        small[c][index[u]] = best
        leave_to[u] = best_v

    small_heads = _cle(small)
    out: List[Optional[int]] = [None] * n
    for u in outside:
        if u == 0:
            continue
        h = small_heads[index[u]]
        out[u] = outside[h] if h != c else leave_to[u]
    entering = outside[small_heads[c]]
    broken = enter_from[entering]
    for v in cycle:
        out[v] = heads[v]
    out[broken] = entering
    return out


def _find_cycle(heads: List[Optional[int]]) -> Optional[List[int]]:
    n = len(heads)
    colour = [0] * n
    for start in range(1, n):
        path, v = [], start
        while v is not None and colour[v] == 0:
            colour[v] = 1
            path.append(v)
            v = heads[v]
        if v is not None and colour[v] == 1 and v in path:
            return path[path.index(v):]
        for p in path:
            colour[p] = 2
    return None
