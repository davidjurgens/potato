"""
Span-specific IAA metrics.

Span annotations are unusual: annotators can disagree on (a) **where** spans
go (unitization / boundary detection) and (b) **what label** each span carries
(categorization). Token-level kappa and exact-match F1 only capture part of
this picture, which is why dedicated metrics exist:

- **Token-level Cohen / Fleiss kappa** via BIO conversion — simple,
  intuitive, but penalizes near-misses harshly and ignores spans of differing
  lengths.
- **Span F1 (exact, partial)** — IR-style; classic in NER literature
  (MUC, CoNLL, SemEval).
- **Krippendorff's alpha_U (unitizing alpha)** — Krippendorff 2018; treats
  each character/token as a unit and accounts for both boundary and
  categorical disagreement.
- **Gamma (Mathet et al. 2015)** — state-of-the-art unified measure that
  jointly handles unit alignment + categorization via the Hungarian algorithm.

All inputs are ``SpanAnnotation``-like objects with ``start``, ``end``, and
``name`` (label) attributes — or plain dicts/tuples with the same fields.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import logging

from potato.server_utils.iaa.nominal import cohen_kappa, fleiss_kappa

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Span representation helpers
# ---------------------------------------------------------------------------

def _span_tuple(span) -> Tuple[int, int, str]:
    """Normalise a span object to (start, end, label)."""
    if isinstance(span, dict):
        return int(span["start"]), int(span["end"]), str(span.get("name") or span.get("label", ""))
    if isinstance(span, tuple) and len(span) == 3:
        return int(span[0]), int(span[1]), str(span[2])
    return int(span.start), int(span.end), str(span.name)


def _normalize(spans: Iterable) -> List[Tuple[int, int, str]]:
    return [_span_tuple(s) for s in spans]


# ---------------------------------------------------------------------------
# Token-level kappa via BIO conversion
# ---------------------------------------------------------------------------

def spans_to_bio(spans: Iterable, length: int) -> List[str]:
    """
    Convert spans to BIO tags over a unit sequence of length ``length``.

    ``length`` can be in characters or tokens depending on the unit; the
    representation is the same. Overlapping spans are resolved with the rule
    "longest span wins" — sufficient for IAA where overlap is rare.
    """
    tags = ["O"] * length
    span_list = sorted(_normalize(spans), key=lambda s: -(s[1] - s[0]))
    for start, end, label in span_list:
        start = max(0, start)
        end = min(length, end)
        if end <= start:
            continue
        if tags[start] != "O":
            continue  # respect longest-wins
        tags[start] = f"B-{label}"
        for i in range(start + 1, end):
            if tags[i] != "O":
                continue
            tags[i] = f"I-{label}"
    return tags


def token_level_kappa(
    spans_by_user: Dict[str, Iterable],
    length: int,
) -> float:
    """
    Cohen's / Fleiss' kappa over the BIO tag sequence.

    For 2 annotators, returns Cohen's kappa; for >=3, returns Fleiss' kappa.
    """
    users = list(spans_by_user)
    if len(users) < 2 or length <= 0:
        return float("nan")
    tag_seqs = {u: spans_to_bio(spans_by_user[u], length) for u in users}

    if len(users) == 2:
        return cohen_kappa(tag_seqs[users[0]], tag_seqs[users[1]])

    counts_per_position = []
    for i in range(length):
        c: Counter = Counter()
        for u in users:
            c[tag_seqs[u][i]] += 1
        counts_per_position.append(dict(c))
    return fleiss_kappa(counts_per_position)


# ---------------------------------------------------------------------------
# Span F1 (exact and partial match)
# ---------------------------------------------------------------------------

def _overlap_len(a: Tuple[int, int, str], b: Tuple[int, int, str]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def span_f1_exact(spans_a: Iterable, spans_b: Iterable) -> Tuple[float, float, float]:
    """
    Strict exact-match F1: (start, end, label) must match exactly.

    Returns (precision, recall, F1) treating spans_b as gold.
    """
    a = set(_normalize(spans_a))
    b = set(_normalize(spans_b))
    if not a and not b:
        return 1.0, 1.0, 1.0
    tp = len(a & b)
    p = tp / len(a) if a else 0.0
    r = tp / len(b) if b else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def _max_matching(ok: List[List[bool]]) -> int:
    """Size of a maximum one-to-one matching on an eligibility matrix.

    Greedy first-fit let an early span claim the only partner a later span
    had: (0,10) took (0,4), leaving (0,4) unmatched though (0,10)-(5,10) and
    (0,4)-(0,4) were both available. F1 0.5 where it is 1.0.
    """
    if not ok or not ok[0]:
        return 0
    try:
        from scipy.optimize import linear_sum_assignment
        rows, cols = linear_sum_assignment(
            [[0 if cell else 1 for cell in row] for row in ok])
        return sum(1 for i, j in zip(rows.tolist(), cols.tolist()) if ok[i][j])
    except ImportError:  # pragma: no cover
        used, count = set(), 0
        for row in ok:
            j = next((j for j, cell in enumerate(row) if cell and j not in used), None)
            if j is not None:
                used.add(j)
                count += 1
        return count


def span_f1_partial(
    spans_a: Iterable,
    spans_b: Iterable,
    label_must_match: bool = True,
    threshold: float = 0.5,
) -> Tuple[float, float, float]:
    """
    Partial-match F1: a span counts as TP if it overlaps a gold span by at
    least ``threshold`` of either span's length (Dice-overlap convention).

    label_must_match: when True (default) overlapping spans must share the
    same label to count; False allows boundary-only agreement.
    """
    a = _normalize(spans_a)
    b = _normalize(spans_b)
    if not a and not b:
        return 1.0, 1.0, 1.0
    def eligible(sa, sb) -> bool:
        if label_must_match and sa[2] != sb[2]:
            return False
        ov = _overlap_len(sa, sb)
        la, lb = sa[1] - sa[0], sb[1] - sb[0]
        if ov <= 0 or la <= 0 or lb <= 0:
            return False
        return (ov / la) >= threshold or (ov / lb) >= threshold

    tp = _max_matching([[eligible(sa, sb) for sb in b] for sa in a])
    p = tp / len(a) if a else 0.0
    r = tp / len(b) if b else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def pairwise_span_f1(
    spans_by_user: Dict[str, Iterable],
    partial: bool = False,
    threshold: float = 0.5,
) -> float:
    """Mean pairwise span-F1 across users."""
    users = list(spans_by_user)
    if len(users) < 2:
        return float("nan")
    scores = []
    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            if partial:
                _, _, f1 = span_f1_partial(
                    spans_by_user[users[i]], spans_by_user[users[j]], threshold=threshold,
                )
            else:
                _, _, f1 = span_f1_exact(spans_by_user[users[i]], spans_by_user[users[j]])
            scores.append(f1)
    if not scores:
        return float("nan")
    return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# Krippendorff's alpha_U (unitizing alpha)
# ---------------------------------------------------------------------------

def krippendorff_alpha_u(
    spans_by_user: Dict[str, Iterable],
    length: int,
) -> float:
    """
    Krippendorff's unitizing alpha for span annotation.

    Implementation: assign each character/token position a categorical label
    (one of the span labels or "O") per annotator, then compute Krippendorff's
    alpha (nominal) over the (annotator, position) pairs. This is the
    operational form recommended in Krippendorff (2018) when the unit is
    fixed (per-character) rather than continuous.

    For continuous-domain alpha_U (where annotators may disagree on the unit
    boundary in a fundamentally continuous space such as audio), prefer gamma.
    """
    users = list(spans_by_user)
    if len(users) < 2 or length <= 0:
        return float("nan")

    rows = []
    for u in users:
        tags = spans_to_bio(spans_by_user[u], length)
        # Map BIO -> base label (strip B-/I- prefix) so boundary placement
        # within a contiguous span doesn't count as disagreement.
        for pos, tag in enumerate(tags):
            label = "O" if tag == "O" else tag.split("-", 1)[1]
            rows.append((u, pos, label))

    from potato.server_utils.iaa.alpha import krippendorff_alpha
    return krippendorff_alpha(rows, level="nominal")


# ---------------------------------------------------------------------------
# Gamma (Mathet et al. 2015)
# ---------------------------------------------------------------------------

def _positional_dissimilarity(a: Tuple[int, int, str],
                               b: Tuple[int, int, str]) -> float:
    """Mathet's positional dissimilarity: squared, normalised boundary shift.

    ``((|s_a - s_b| + |e_a - e_b|) / (len_a + len_b)) ** 2``. Unsquared, a far
    misplacement cost only linearly, and the alignment could not prefer
    leaving a unit unpaired.
    """
    total = (a[1] - a[0]) + (b[1] - b[0])
    if total <= 0:
        return 0.0 if (a[0], a[1]) == (b[0], b[1]) else float("inf")
    return ((abs(a[0] - b[0]) + abs(a[1] - b[1])) / total) ** 2


def _categorical_dissimilarity(a: Tuple[int, int, str],
                               b: Tuple[int, int, str]) -> float:
    return 0.0 if a[2] == b[2] else 1.0


def _pairwise_disorder(
    spans_a: List[Tuple[int, int, str]],
    spans_b: List[Tuple[int, int, str]],
    alpha: float,
    beta: float,
    delta_empty: float,
) -> float:
    """
    Disorder of the best alignment of two annotators' units (Mathet 2015).

    Every unit is either paired with one of the other annotator's units, at
    ``alpha * d_pos + beta * d_cat``, or aligned with the empty unit at
    ``delta_empty``. The total is divided by the mean number of units per
    annotator. A padded square assignment used to force every unit onto a
    real partner when the counts were equal, so one misplaced span cost
    without bound: two annotators matching on two of three spans read gamma
    0.06, chance level. This matches pygamma-agreement's best alignment
    (0.667 on that example).
    """
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
    except ImportError:  # pragma: no cover
        logger.warning("scipy unavailable; gamma falling back to NaN")
        return float("nan")

    na, nb = len(spans_a), len(spans_b)
    if na + nb == 0:
        return 0.0
    blocked = 1e9
    size = na + nb
    cost = np.zeros((size, size), dtype=float)
    # a_i with b_j
    for i, ua in enumerate(spans_a):
        for j, ub in enumerate(spans_b):
            d = alpha * _positional_dissimilarity(ua, ub) \
                + beta * _categorical_dissimilarity(ua, ub)
            cost[i, j] = min(d, blocked)
    # a_i with the empty unit (its own column only), and b_j likewise
    cost[:na, nb:] = blocked
    cost[na:, :nb] = blocked
    for i in range(na):
        cost[i, nb + i] = delta_empty
    for j in range(nb):
        cost[na + j, j] = delta_empty
    # empty with empty: free

    rows, cols = linear_sum_assignment(cost)
    total = float(cost[rows, cols].sum())
    return total / ((na + nb) / 2.0)


def gamma(
    spans_by_user: Dict[str, Iterable],
    length: Optional[int] = None,
    alpha: float = 1.0,
    beta: float = 1.0,
    n_samples: int = 30,
    seed: int = 1234,
) -> float:
    """
    Mathet et al. (2015) gamma agreement.

    Args:
        spans_by_user: annotator_id -> iterable of spans
        length: total length of the unit space (characters or tokens). If
            omitted, inferred from the maximum span end across annotators.
        alpha: weight on positional dissimilarity.
        beta: weight on categorical dissimilarity.
        n_samples: number of random pairings used to estimate the
            expected-by-chance disorder.
        seed: RNG seed for reproducibility.

    Returns:
        gamma in [-1, 1] approximately, where 1 = perfect agreement, 0 =
        chance-level. NaN if scipy is unavailable.

    Notes:
        The observed disorder is Mathet's best alignment (squared positional
        dissimilarity, units may align with the empty unit), and matches
        pygamma-agreement for two annotators; with more it is the mean over
        annotator pairs. The chance baseline is simpler than pygamma's
        sampler: ``n_samples`` times, every unit is dealt to a random
        annotator (keeping each annotator's count) and placed at a random
        position in ``[0, length]`` (keeping its length and label). Gamma
        therefore agrees with pygamma in direction and rough size, not to
        the digit.
    """
    import random as _random

    # Sorted: the seeded shuffle below deals spans back out by position, so an
    # input order that follows set iteration (per-process string hashing)
    # gave a different gamma for the same data after a restart.
    users = sorted(spans_by_user, key=str)
    if len(users) < 2:
        return float("nan")
    normed = {u: sorted(_normalize(spans_by_user[u])) for u in users}

    # Empty-unit dissimilarity follows Mathet: a moderate constant ~ 1
    delta_empty = 1.0

    # Observed disorder: mean pairwise disorder across all annotator pairs
    pair_disorders = []
    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            pair_disorders.append(
                _pairwise_disorder(normed[users[i]], normed[users[j]], alpha, beta, delta_empty)
            )
    if not pair_disorders:
        return float("nan")
    if any(d != d for d in pair_disorders):  # NaN -> bail
        return float("nan")
    observed = sum(pair_disorders) / len(pair_disorders)

    # Expected-by-chance disorder via shuffled, relocated units
    all_spans = [s for u in users for s in normed[u]]
    if len(all_spans) < 2:
        # Nothing (or one unit) to agree about: undefined, not perfect.
        return float("nan")
    extent = float(length) if length else float(max(e for _s, e, _l in all_spans))

    rng = _random.Random(seed)
    chance_disorders = []
    sizes = [len(normed[u]) for u in users]
    for _ in range(n_samples):
        shuffled = []
        for start, end, label in all_spans:
            width = end - start
            new_start = rng.uniform(0.0, max(0.0, extent - width))
            shuffled.append((new_start, new_start + width, label))
        rng.shuffle(shuffled)
        # Re-distribute back to annotators preserving original counts
        idx = 0
        shuffled_per_user = []
        for sz in sizes:
            shuffled_per_user.append(shuffled[idx:idx + sz])
            idx += sz
        sample_pair_disorders = []
        for i in range(len(users)):
            for j in range(i + 1, len(users)):
                sample_pair_disorders.append(
                    _pairwise_disorder(
                        shuffled_per_user[i],
                        shuffled_per_user[j],
                        alpha, beta, delta_empty,
                    )
                )
        if sample_pair_disorders:
            chance_disorders.append(sum(sample_pair_disorders) / len(sample_pair_disorders))

    if not chance_disorders:
        return float("nan")
    expected = sum(chance_disorders) / len(chance_disorders)
    if expected <= 0:
        return float("nan")
    return 1.0 - (observed / expected)
