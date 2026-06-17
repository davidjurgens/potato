"""
Local γ (Gamma) inter-annotator agreement for spans — EXPERIMENTAL.

This is a self-contained, dependency-light reimplementation of the *core ideas*
of the γ measure (Mathet, Widlöcher & Métivier, 2015, "The Unified and
Holistic Method Gamma (γ) for Inter-Annotator Agreement Measure and
Alignment"). It is NOT a bit-exact reproduction of the canonical
``pygamma-agreement`` package — notably it computes γ **pairwise** (then
averages over annotator pairs) rather than solving the full multi-annotator
continuum alignment, and its chance model is a simpler positional shuffle.

What it keeps faithfully:
  γ = 1 − (observed disorder) / (expected disorder)
where *disorder* is the average dissimilarity of the best alignment between two
annotators' unit sets, and *expected disorder* is that same quantity computed
over random ("chance") annotators obtained by relocating each unit to a random
position in the continuum (keeping its length and category).

Dissimilarity of two units u, v (Mathet positional + categorical):
    d_pos(u,v) = ((|start_u−start_v| + |end_u−end_v|) / (len_u + len_v))²
    d_cat(u,v) = 0 if same label else 1
    d(u,v)     = α·d_pos + β·d_cat
A unit left unaligned costs ``delta_empty`` (so two units align only when
d(u,v) < 2·delta_empty).

For the canonical, peer-reviewed implementation use ``pygamma-agreement``; this
module exists so Potato can report a γ-style number with no extra dependency.
"""

import logging
from itertools import combinations
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

logger = logging.getLogger(__name__)

# A "unit" is (start, end, label).
Unit = Tuple[int, int, str]


def unit_dissimilarity(u: Unit, v: Unit, alpha: float = 1.0, beta: float = 1.0) -> float:
    """Mathet positional + categorical dissimilarity between two units."""
    su, eu, lu = u
    sv, ev, lv = v
    len_u, len_v = (eu - su), (ev - sv)
    denom = len_u + len_v
    d_pos = (((abs(su - sv) + abs(eu - ev)) / denom) ** 2) if denom > 0 else 0.0
    d_cat = 0.0 if lu == lv else 1.0
    return alpha * d_pos + beta * d_cat


def _alignment_cost(
    units_a: List[Unit], units_b: List[Unit],
    delta_empty: float, alpha: float, beta: float,
) -> Tuple[float, int]:
    """Optimal alignment cost between two unit sets (Hungarian, with empties).

    Returns (total_cost, n_alignments) where n_alignments counts every aligned
    pair that involves at least one real unit (real↔real and real↔empty).
    """
    na, nb = len(units_a), len(units_b)
    if na == 0 and nb == 0:
        return 0.0, 0
    if na == 0:
        return delta_empty * nb, nb
    if nb == 0:
        return delta_empty * na, na

    # Square cost matrix with empty slots:
    #   rows: [real A] + [empty-for-B]   cols: [real B] + [empty-for-A]
    big = delta_empty * 1e6
    n = na + nb
    cost = np.full((n, n), 0.0)
    for i in range(na):
        for j in range(nb):
            cost[i, j] = unit_dissimilarity(units_a[i], units_b[j], alpha, beta)
    # A_i -> its own empty (col nb + i); other A-empties are forbidden
    for i in range(na):
        for j in range(na):
            cost[i, nb + j] = delta_empty if i == j else big
    # empty-for-B (row na + j) -> B_j; others forbidden
    for j in range(nb):
        for i in range(nb):
            cost[na + j, i] = delta_empty if i == j else big
    # empty-empty quadrant already 0

    rows, cols = linear_sum_assignment(cost)
    total = 0.0
    n_align = 0
    for r, c in zip(rows, cols):
        is_real_r = r < na
        is_real_c = c < nb
        if not is_real_r and not is_real_c:
            continue  # empty-empty, ignore
        total += cost[r, c]
        n_align += 1
    return total, n_align


def _pair_disorder(
    a_by_iid: Dict[str, List[Unit]], b_by_iid: Dict[str, List[Unit]],
    delta_empty: float, alpha: float, beta: float,
) -> Optional[float]:
    """Average alignment dissimilarity between two annotators over shared items."""
    shared = set(a_by_iid) & set(b_by_iid)
    total, n = 0.0, 0
    for iid in shared:
        c, k = _alignment_cost(a_by_iid[iid], b_by_iid[iid], delta_empty, alpha, beta)
        total += c
        n += k
    if n == 0:
        return None
    return total / n


def _random_annotator(
    by_iid: Dict[str, List[Unit]], lengths: Dict[str, int], rng: np.random.RandomState,
) -> Dict[str, List[Unit]]:
    """Relocate each unit to a random position in its continuum (keep len+label)."""
    out: Dict[str, List[Unit]] = {}
    for iid, units in by_iid.items():
        L = lengths.get(iid, 0)
        new_units = []
        for (s, e, lab) in units:
            ln = e - s
            if L <= ln:
                new_units.append((0, max(ln, 1), lab))
            else:
                ns = int(rng.randint(0, L - ln + 1))
                new_units.append((ns, ns + ln, lab))
        out[iid] = new_units
    return out


def _expected_pair_disorder(
    a_by_iid, b_by_iid, lengths, delta_empty, alpha, beta, n_samples, rng,
) -> Optional[float]:
    vals = []
    for _ in range(n_samples):
        ra = _random_annotator(a_by_iid, lengths, rng)
        rb = _random_annotator(b_by_iid, lengths, rng)
        d = _pair_disorder(ra, rb, delta_empty, alpha, beta)
        if d is not None:
            vals.append(d)
    if not vals:
        return None
    return float(np.mean(vals))


def gamma_agreement(
    raters: Dict[str, Dict[str, List[Unit]]],
    lengths: Dict[str, int],
    is_llm: Callable[[str], bool],
    delta_empty: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    n_samples: int = 30,
    seed: int = 0,
) -> Dict[str, Any]:
    """Pairwise γ averaged over annotator pairs, partitioned by rater kind.

    Args:
        raters: {rater_name: {instance_id: [(start, end, label), ...]}}
        lengths: {instance_id: continuum length (chars)}; missing -> max end seen.
        is_llm: predicate marking a rater name as an LLM (vs human).
    """
    names = sorted(raters)
    if len(names) < 2:
        return {"gamma": None, "n_pairs": 0}

    rng = np.random.RandomState(seed)
    partitioned = {"human_llm": [], "llm_llm": [], "human_human": []}
    all_g = []

    for a, b in combinations(names, 2):
        obs = _pair_disorder(raters[a], raters[b], delta_empty, alpha, beta)
        if obs is None:
            continue
        exp = _expected_pair_disorder(
            raters[a], raters[b], lengths, delta_empty, alpha, beta, n_samples, rng)
        if not exp:  # None or 0 -> γ undefined
            continue
        g = 1.0 - obs / exp
        all_g.append(g)
        kind = ("llm_llm" if is_llm(a) and is_llm(b)
                else "human_human" if not is_llm(a) and not is_llm(b)
                else "human_llm")
        partitioned[kind].append(g)

    def _mean(xs):
        return round(float(np.mean(xs)), 4) if xs else None

    return {
        "gamma": _mean(all_g),
        "mean_human_llm": _mean(partitioned["human_llm"]),
        "mean_llm_llm": _mean(partitioned["llm_llm"]),
        "mean_human_human": _mean(partitioned["human_human"]),
        "n_pairs": len(all_g),
        "n_samples": n_samples,
        "approximate": True,
    }
