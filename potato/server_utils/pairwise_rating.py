"""
Pairwise rating aggregation: Elo and Bradley-Terry.

Turns a set of pairwise outcomes (``winner beats loser``) into a global ranking
that accounts for *opponent strength* — unlike a raw win-rate, which treats a win
over a weak model the same as a win over a strong one. Used by the Model Arena
leaderboard and available to any feature that collects pairwise preferences
(human or judge).

Pure Python, no third-party dependencies:
- ``EloRating``: incremental/online ratings (update as each comparison arrives).
- ``bradley_terry``: batch maximum-likelihood ratings via the MM algorithm
  (Hunter 2004), returned on a 0–100 scale for display.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

Pair = Tuple[str, str]  # (winner_label, loser_label)


class EloRating:
    """Online Elo ratings. Default start 1000, K-factor 32 (chess-standard)."""

    def __init__(self, k: float = 32.0, base: float = 1000.0):
        self.k = k
        self.base = base
        self._r: Dict[str, float] = {}

    def rating(self, label: str) -> float:
        return self._r.get(label, self.base)

    def update(self, winner: str, loser: str) -> None:
        rw, rl = self.rating(winner), self.rating(loser)
        # Expected score for the winner under the logistic Elo model.
        ew = 1.0 / (1.0 + 10 ** ((rl - rw) / 400.0))
        self._r[winner] = rw + self.k * (1.0 - ew)
        self._r[loser] = rl + self.k * (0.0 - (1.0 - ew))

    def update_many(self, pairs: Iterable[Pair]) -> None:
        for w, l in pairs:
            if w and l and w != l:
                self.update(w, l)

    def ratings(self) -> Dict[str, float]:
        return dict(self._r)


def bradley_terry(pairs: List[Pair], labels: Iterable[str] = None,
                  max_iter: int = 200, tol: float = 1e-9) -> Dict[str, float]:
    """Fit Bradley-Terry strengths from pairwise outcomes via the MM algorithm.

    Returns a dict ``label -> score`` on a 0–100 scale (geometric mean anchored
    so the field averages ~50). Labels with no comparisons get 50.0. Robust to a
    label that never won or never lost (a tiny smoothing prior keeps it finite).
    """
    wins: Dict[str, int] = defaultdict(int)
    games: Dict[Tuple[str, str], int] = defaultdict(int)  # (a,b) count of a-vs-b games
    seen = set()
    for w, l in pairs:
        if not w or not l or w == l:
            continue
        wins[w] += 1
        games[(w, l)] += 1
        games[(l, w)] += 1
        seen.add(w)
        seen.add(l)

    universe = list(labels) if labels is not None else sorted(seen)
    universe = [x for x in universe if x] or sorted(seen)
    if not universe:
        return {}

    # Smoothing: a half-win prior vs a phantom average opponent keeps undefeated /
    # winless models from diverging to ±infinity.
    p: Dict[str, float] = {x: 1.0 for x in universe}
    n = len(universe)

    for _ in range(max_iter):
        new_p: Dict[str, float] = {}
        max_delta = 0.0
        for x in universe:
            # numerator: wins (+ 0.5 smoothing prior)
            w_x = wins.get(x, 0) + 0.5
            denom = 0.0
            for y in universe:
                if y == x:
                    continue
                n_xy = games.get((x, y), 0)
                if n_xy:
                    denom += n_xy / (p[x] + p[y])
            # smoothing game vs a phantom opponent at the mean strength
            mean_strength = sum(p.values()) / n
            denom += 1.0 / (p[x] + mean_strength)
            new_p[x] = w_x / denom if denom > 0 else p[x]
        # normalize (geometric mean -> 1) for identifiability
        log_mean = sum(math.log(max(v, 1e-12)) for v in new_p.values()) / n
        norm = math.exp(log_mean)
        for x in universe:
            new_p[x] = new_p[x] / norm
            max_delta = max(max_delta, abs(new_p[x] - p[x]))
        p = new_p
        if max_delta < tol:
            break

    # Map strengths to a 0–100 display scale: 50 * strength capped sensibly.
    # strength is multiplicative around 1.0; convert via logistic of log-strength.
    out: Dict[str, float] = {}
    for x in universe:
        s = math.log(max(p[x], 1e-12))
        out[x] = round(100.0 / (1.0 + math.exp(-s)), 1)  # 50 at strength 1.0
    return out


def pairs_from_ranking(ranking: List[str]) -> List[Pair]:
    """Expand a full ranking [best, ..., worst] into all pairwise (winner, loser)
    outcomes: every earlier entry beats every later entry."""
    out: List[Pair] = []
    for i in range(len(ranking)):
        for j in range(i + 1, len(ranking)):
            if ranking[i] and ranking[j] and ranking[i] != ranking[j]:
                out.append((ranking[i], ranking[j]))
    return out


def pairs_from_winner(winner: str, field: List[str]) -> List[Pair]:
    """A single winner beats every other model in the field for that comparison."""
    return [(winner, other) for other in field if other and other != winner]
