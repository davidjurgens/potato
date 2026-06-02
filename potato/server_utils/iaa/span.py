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
    matched_b = set()
    tp = 0
    for sa in a:
        for idx, sb in enumerate(b):
            if idx in matched_b:
                continue
            if label_must_match and sa[2] != sb[2]:
                continue
            ov = _overlap_len(sa, sb)
            if ov <= 0:
                continue
            la, lb = sa[1] - sa[0], sb[1] - sb[0]
            if la <= 0 or lb <= 0:
                continue
            if (ov / la) >= threshold or (ov / lb) >= threshold:
                tp += 1
                matched_b.add(idx)
                break
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

def _positional_dissimilarity(
    a: Tuple[int, int, str],
    b: Tuple[int, int, str],
    delta_empty: float,
) -> float:
    """Positional component of the Mathet dissimilarity (normalized)."""
    if a is None or b is None:
        return delta_empty
    # Sum of |starts diff| + |ends diff|, normalized by total span lengths.
    diff = abs(a[0] - b[0]) + abs(a[1] - b[1])
    total = (a[1] - a[0]) + (b[1] - b[0])
    if total <= 0:
        return delta_empty
    return diff / total


def _categorical_dissimilarity(
    a: Tuple[int, int, str],
    b: Tuple[int, int, str],
    delta_empty: float,
) -> float:
    if a is None or b is None:
        return delta_empty
    return 0.0 if a[2] == b[2] else 1.0


def _pairwise_disorder(
    spans_a: List[Tuple[int, int, str]],
    spans_b: List[Tuple[int, int, str]],
    alpha: float,
    beta: float,
    delta_empty: float,
) -> float:
    """
    Optimal-alignment disorder between two annotators' span sets.

    Uses the Hungarian algorithm (``scipy.optimize.linear_sum_assignment``)
    with padded empty units so that |spans_a| != |spans_b| is handled.
    """
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
    except ImportError:  # pragma: no cover
        logger.warning("scipy unavailable; gamma falling back to NaN")
        return float("nan")

    n = max(len(spans_a), len(spans_b))
    if n == 0:
        return 0.0
    # Pad shorter side with None (= empty unit)
    a_padded: List[Optional[Tuple[int, int, str]]] = list(spans_a) + [None] * (n - len(spans_a))
    b_padded: List[Optional[Tuple[int, int, str]]] = list(spans_b) + [None] * (n - len(spans_b))

    cost = np.zeros((n, n), dtype=float)
    for i in range(n):
        for j in range(n):
            pos = _positional_dissimilarity(a_padded[i], b_padded[j], delta_empty)
            cat = _categorical_dissimilarity(a_padded[i], b_padded[j], delta_empty)
            cost[i, j] = alpha * pos + beta * cat

    row_ind, col_ind = linear_sum_assignment(cost)
    total = float(cost[row_ind, col_ind].sum())
    return total / n


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
        This implementation is a faithful but simplified rendition: positional
        dissimilarity is normalized by combined span length, and the chance
        baseline is estimated by re-pairing spans across all annotators
        ``n_samples`` times. Full pygamma-agreement uses a more sophisticated
        baseline (continuum-of-shuffles); the simplification is sufficient for
        the relative IAA comparisons that drive routing decisions.
    """
    import random as _random

    users = list(spans_by_user)
    if len(users) < 2:
        return float("nan")
    normed = {u: _normalize(spans_by_user[u]) for u in users}

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

    # Expected-by-chance disorder via shuffled pairings
    all_spans = [s for u in users for s in normed[u]]
    if len(all_spans) < 2:
        return 1.0 if observed == 0 else float("nan")

    rng = _random.Random(seed)
    chance_disorders = []
    sizes = [len(normed[u]) for u in users]
    for _ in range(n_samples):
        shuffled = list(all_spans)
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
        return 1.0 if observed == 0 else float("nan")
    return 1.0 - (observed / expected)
