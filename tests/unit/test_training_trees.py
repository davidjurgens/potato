"""Chu-Liu-Edmonds against brute force on small random graphs."""

import itertools
import random

from potato.training.trees import max_spanning_tree


def _is_tree(heads):
    n = len(heads)
    if sum(1 for h in heads[1:] if h == 0) != 1:
        return False
    for start in range(1, n):
        seen, v = set(), start
        while v != 0:
            if v in seen:
                return False
            seen.add(v)
            v = heads[v]
    return True


def _brute(scores):
    n = len(scores)
    best = None
    for choice in itertools.product(range(n), repeat=n - 1):
        heads = [None] + list(choice)
        if any(h == d for d, h in enumerate(heads) if h is not None):
            continue
        if not _is_tree(heads):
            continue
        total = sum(scores[h][d] for d, h in enumerate(heads) if h is not None)
        best = total if best is None or total > best else best
    return best


def test_matches_brute_force():
    rng = random.Random(0)
    for _ in range(300):
        n = rng.randint(2, 6)
        scores = [[rng.uniform(-5, 5) for _ in range(n)] for _ in range(n)]
        heads = max_spanning_tree(scores)
        assert _is_tree(heads), heads
        total = sum(scores[h][d] for d, h in enumerate(heads) if h is not None)
        assert abs(total - _brute(scores)) < 1e-9


def test_a_greedy_cycle_is_broken():
    # Words 1 and 2 each prefer the other as head; the root weakly prefers 1.
    scores = [[0, 1, 0], [0, 0, 9], [0, 9, 0]]
    heads = max_spanning_tree(scores)
    assert _is_tree(heads) and heads[1] == 0 and heads[2] == 1
