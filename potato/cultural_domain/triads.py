"""
Triad designs for ``triad_test``.

A triad test shows three items of a domain and asks which one is most
different. Which triads are asked depends on ``n``, the number of items:

``complete``
    every one of the C(n, 3) triads. ``auto`` uses it while that is at most
    :data:`COMPLETE_MAX` triads (n <= 6).
``steiner``
    a balanced incomplete block design with lambda = 1 (a Steiner triple
    system): every pair of items appears together in exactly one triad, in
    n(n - 1)/6 triads. It exists only when n is 1 or 3 mod 6. Built with
    Bose's construction for n = 6t + 3 and Skolem's for n = 6t + 1.
``sample``
    for any other n: ``max_triads`` triads chosen greedily to keep pair
    counts close to even (each step takes the unused triad whose pairs have
    been shown least, then whose items have been shown least), with ties
    broken by a seeded shuffle. Greedy is not optimal: with a fixed size,
    pair counts can differ by two. Without ``max_triads`` it stops
    once every pair has appeared at least once (in tests over n = 4..30 no
    pair then appeared more than twice; that is observed, not proven).
    That is a few triads more than the Schoenheim bound
    ceil(n/3 * ceil((n - 1)/2)), the fewest that could contain every pair.

The design depends only on the domain and the scheme name (which seeds a
sample), so every participant answers the same
triads. The order of the triads and the position of the items within each
triad are shuffled per participant, item and scheme.

The browser builds the plan itself (``potato/static/triad-design.js``): the
schema HTML is generated once at startup, and for ``items_field`` domains the
items are only known on the page. This module is the reference
implementation; ``tests/unit/test_triad_design.py`` runs the JavaScript in
Node and checks that both give the same triads and the same order. Both use
the same 32-bit FNV-1a hash and mulberry32 generator, so a seed means the same
thing on either side.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Iterable, List, Optional, Sequence, Tuple

Triad = Tuple[int, int, int]

DESIGNS = ("auto", "complete", "steiner", "sample")
#: ``auto`` asks every triad while there are at most this many (n <= 6).
COMPLETE_MAX = 20
#: The most items a triad_test domain may have.
MAX_DOMAIN = 60

_MASK = 0xFFFFFFFF


# ----------------------------------------------------------------------
# Hash and random numbers (mirrored in triad-design.js)
# ----------------------------------------------------------------------

def fnv1a(text: str) -> int:
    """32-bit FNV-1a over the UTF-8 bytes of ``text``."""
    h = 0x811C9DC5
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & _MASK
    return h


def _imul(a: int, b: int) -> int:
    return (a * b) & _MASK


def mulberry32(seed: int):
    """The mulberry32 generator: a function returning floats in [0, 1)."""
    state = seed & _MASK

    def nxt() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _MASK
        t = state
        t = _imul(t ^ (t >> 15), t | 1)
        t = ((t + _imul(t ^ (t >> 7), t | 61)) & _MASK) ^ t
        return ((t ^ (t >> 14)) & _MASK) / 4294967296.0

    return nxt


def shuffle(values: list, rng) -> list:
    """Fisher-Yates, in place, with ``rng`` from :func:`mulberry32`."""
    for i in range(len(values) - 1, 0, -1):
        j = int(rng() * (i + 1))
        values[i], values[j] = values[j], values[i]
    return values


def design_seed(scheme_name: str, domain: Sequence[str]) -> int:
    return fnv1a("triad-design\x1f" + str(scheme_name) + "\x1f" + "\x1f".join(map(str, domain)))


def order_seed(user_id: str, instance_id: str, scheme_name: str) -> int:
    return fnv1a(f"{user_id}\x1f{instance_id}\x1f{scheme_name}")


# ----------------------------------------------------------------------
# Designs
# ----------------------------------------------------------------------

def complete_design(n: int) -> List[Triad]:
    return [tuple(t) for t in combinations(range(n), 3)]


def steiner_exists(n: int) -> bool:
    return n >= 3 and n % 6 in (1, 3)


def steiner_design(n: int) -> List[Triad]:
    """A Steiner triple system on ``range(n)``; n must be 1 or 3 mod 6."""
    if not steiner_exists(n):
        raise ValueError(f"no Steiner triple system on {n} items (n must be 1 or 3 mod 6)")
    blocks = []
    if n % 6 == 3:
        # Bose: points (x, i), x in Z_{2t+1}, i in Z_3, numbered x + v*i.
        v = n // 3
        half = (v + 1) // 2           # the inverse of 2 mod v
        def pt(x, i):
            return x + v * (i % 3)
        for x in range(v):
            blocks.append((pt(x, 0), pt(x, 1), pt(x, 2)))
        for x in range(v):
            for y in range(x + 1, v):
                z = ((x + y) * half) % v   # idempotent commutative quasigroup
                for i in range(3):
                    blocks.append((pt(x, i), pt(y, i), pt(z, i + 1)))
    else:
        # Skolem: infinity plus (x, i), x in Z_{2t}, i in Z_3.
        t = (n - 1) // 6
        m = 2 * t
        inf = n - 1
        def pt(x, i):
            return x + m * (i % 3)
        def op(x, y):                 # half-idempotent commutative quasigroup
            s = (x + y) % m
            return s // 2 if s % 2 == 0 else t + (s - 1) // 2
        for x in range(t):
            blocks.append((pt(x, 0), pt(x, 1), pt(x, 2)))
        for x in range(t):
            for i in range(3):
                blocks.append((inf, pt(x + t, i), pt(x, i + 1)))
        for x in range(m):
            for y in range(x + 1, m):
                for i in range(3):
                    blocks.append((pt(x, i), pt(y, i), pt(op(x, y), i + 1)))
    return sorted(tuple(sorted(b)) for b in blocks)


def schoenheim_bound(n: int) -> int:
    """The fewest triads that can contain every pair of n items."""
    return math.ceil(n / 3 * math.ceil((n - 1) / 2))


def sample_design(n: int, size: Optional[int], seed: int) -> List[Triad]:
    """``size`` triads with pair counts kept as even as possible.

    ``size=None`` keeps going until every pair has appeared once.
    """
    candidates = complete_design(n)
    shuffle(candidates, mulberry32(seed))
    limit = len(candidates) if size is None else min(size, len(candidates))
    pair = [[0] * n for _ in range(n)]
    item = [0] * n
    used = [False] * len(candidates)
    chosen: List[Triad] = []
    uncovered = n * (n - 1) // 2
    while len(chosen) < limit and (size is not None or uncovered > 0):
        best, best_score = -1, None
        for idx, (a, b, c) in enumerate(candidates):
            if used[idx]:
                continue
            ab, ac, bc = pair[a][b], pair[a][c], pair[b][c]
            score = max(ab, ac, bc) * 1000000 + (ab + ac + bc) * 1000 + item[a] + item[b] + item[c]
            if best_score is None or score < best_score:
                best, best_score = idx, score
        used[best] = True
        a, b, c = candidates[best]
        for x, y in ((a, b), (a, c), (b, c)):
            if pair[x][y] == 0:
                uncovered -= 1
            pair[x][y] += 1
            pair[y][x] += 1
        for x in (a, b, c):
            item[x] += 1
        chosen.append((a, b, c))
    return chosen


def resolve_design(n: int, design: str = "auto", max_triads: Optional[int] = None) -> str:
    """Which design ``design`` means for ``n`` items."""
    if design not in DESIGNS:
        raise ValueError(f"design must be one of {', '.join(DESIGNS)}")
    if design == "steiner" and not steiner_exists(n):
        return "sample"
    if design != "auto":
        return design
    total = math.comb(n, 3)
    if total <= COMPLETE_MAX and (max_triads is None or total <= max_triads):
        return "complete"
    if steiner_exists(n) and (max_triads is None or n * (n - 1) // 6 <= max_triads):
        return "steiner"
    return "sample"


def build_design(domain: Sequence[str], scheme_name: str, design: str = "auto",
                 max_triads: Optional[int] = None) -> Tuple[str, List[Triad]]:
    """``(design used, triads as index triples into domain)``."""
    n = len(domain)
    if n < 3:
        raise ValueError("a triad test needs at least three items")
    kind = resolve_design(n, design, max_triads)
    if kind == "complete":
        return kind, complete_design(n)
    if kind == "steiner":
        return kind, steiner_design(n)
    return kind, sample_design(n, max_triads, design_seed(scheme_name, domain))


def shown_plan(domain: Sequence[str], scheme_name: str, user_id: str, instance_id: str,
               design: str = "auto", max_triads: Optional[int] = None) -> Tuple[str, List[List[str]]]:
    """The triads one participant sees, in order, each in shown position order."""
    kind, triads = build_design(domain, scheme_name, design, max_triads)
    rng = mulberry32(order_seed(user_id, instance_id, scheme_name))
    order = shuffle(list(range(len(triads))), rng)
    plan = []
    for idx in order:
        positions = shuffle([0, 1, 2], rng)
        triad = triads[idx]
        plan.append([domain[triad[p]] for p in positions])
    return kind, plan


def pair_counts(triads: Iterable[Sequence[int]], n: int) -> List[List[int]]:
    counts = [[0] * n for _ in range(n)]
    for a, b, c in triads:
        for x, y in ((a, b), (a, c), (b, c)):
            counts[x][y] += 1
            counts[y][x] += 1
    return counts


def domain_items(raw) -> List[str]:
    """Item names from a list of strings or ``{name: ...}`` dicts, duplicates dropped."""
    out: List[str] = []
    for entry in raw or []:
        if isinstance(entry, dict):
            entry = entry.get("name", entry.get("text"))
        if entry is None:
            continue
        text = str(entry).strip()
        if text and text not in out:
            out.append(text)
    return out
