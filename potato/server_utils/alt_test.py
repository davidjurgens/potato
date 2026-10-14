"""
The Alternative Annotator Test (alt-test).

Calderon, Reichart & Dror, "The Alternative Annotator Test for LLM-as-a-Judge:
How to Statistically Justify Replacing Human Annotators with LLMs", ACL 2025
(https://aclanthology.org/2025.acl-long.782/, arXiv:2501.10970). Reference
implementation: https://github.com/nitaytech/AltTest (``alt_test`` in
``alt_test_example.ipynb``). This module follows that code; on the paper's
released datasets it reproduces the notebook's winning rates and advantage
probabilities exactly.

The procedure, for an LLM ``f`` and human annotators ``h_1..h_m``:

1. Leave one annotator out. For annotator ``j`` and each item ``i`` that
   ``j`` labelled, score how well ``f`` and ``h_j`` each align with the
   *remaining* annotators of that item, ``S(f, x_i, j)`` and
   ``S(h_j, x_i, j)``. ``accuracy`` is the mean exact-match rate against the
   remaining annotators (not a match against their majority); ``neg_rmse`` is
   the negative root-mean-square distance to them.
2. Win indicators: ``W^f_ij = 1[S(f) >= S(h_j)]`` and
   ``W^h_ij = 1[S(h_j) >= S(f)]``. A tie is a win for both.
3. ``rho^f_j = mean_i W^f_ij`` and ``rho^h_j = mean_i W^h_ij``.
4. Per annotator, test ``H0: rho^f_j <= rho^h_j - eps`` against
   ``H1: rho^f_j > rho^h_j - eps`` with a one-sample t-test of
   ``d_ij = W^h_ij - W^f_ij`` against ``eps``, alternative "less".
5. Control the FDR across the ``m`` annotators with Benjamini-Yekutieli at
   ``q`` (0.05 in the paper), because the ``m`` hypotheses share data and are
   dependent.
6. Winning rate ``omega`` = fraction of annotators whose H0 is rejected. The
   LLM passes when ``omega >= 0.5``.
7. Average advantage probability ``rho = mean_j rho^f_j``: the probability
   that the LLM is as good as or better than a randomly chosen annotator. The
   paper uses it to rank LLMs, independent of passing.

``eps`` is a cost-benefit allowance in the LLM's favour. The paper's rule of
thumb: 0.2 for experts, 0.15 for skilled annotators, 0.1 for crowd workers,
and smaller when inter-annotator agreement is low.

Minimum data, per the paper and its FAQ: at least 30 items per annotator for
the t-test's normality assumption (50-100 recommended; below 30 the paper says
to use a Wilcoxon signed-rank test instead, available here as
``test="wilcoxon"``), at least 3 annotators (2 work but are "less reliable",
since there is no consensus to represent), and at least 2 annotators on an item
for it to count at all. Where the data falls short, the result carries an
``insufficient`` reason and ``passed`` is None rather than a number.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Hashable, List, Mapping, Optional, Sequence, Union

logger = logging.getLogger(__name__)

# Paper defaults (Calderon et al. 2025, Sections 3-4 and the FAQ).
DEFAULT_EPSILON = 0.2
DEFAULT_Q = 0.05
PASS_THRESHOLD = 0.5
MIN_ITEMS_PER_ANNOTATOR = 30
MIN_ANNOTATORS = 3
MIN_HUMANS_PER_ITEM = 2

ScoringFn = Callable[[Any, Sequence[Any]], float]


# ---------------------------------------------------------------------------
# Alignment scoring functions S(pred, remaining_annotations)
# ---------------------------------------------------------------------------

def accuracy_alignment(pred: Any, annotations: Sequence[Any]) -> float:
    """Mean exact-match rate of ``pred`` against each remaining annotation."""
    if not annotations:
        raise ValueError("no remaining annotations to align with")
    return sum(1.0 for a in annotations if pred == a) / len(annotations)


def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"neg_rmse needs numeric labels; got {value!r}"
        ) from None
    if math.isnan(number):
        raise ValueError("neg_rmse got a NaN label")
    return number


def neg_rmse_alignment(pred: Any, annotations: Sequence[Any]) -> float:
    """Negative RMSE between ``pred`` and each remaining annotation."""
    if not annotations:
        raise ValueError("no remaining annotations to align with")
    p = _as_number(pred)
    sq = [(p - _as_number(a)) ** 2 for a in annotations]
    return -math.sqrt(sum(sq) / len(sq))


SCORING_FUNCTIONS: Dict[str, ScoringFn] = {
    "accuracy": accuracy_alignment,
    "neg_rmse": neg_rmse_alignment,
}


# ---------------------------------------------------------------------------
# Benjamini-Yekutieli
# ---------------------------------------------------------------------------

def benjamini_yekutieli(p_values: Sequence[float], q: float = DEFAULT_Q):
    """
    Benjamini-Yekutieli step-up FDR control under arbitrary dependence.

    With ``m`` p-values sorted ascending, ``c(m) = sum_{k=1..m} 1/k``, reject
    the hypotheses ranked ``1..k*`` where ``k*`` is the largest ``k`` with
    ``p_(k) <= k / (m * c(m)) * q``.

    Returns ``(adjusted, rejected)`` in the input order. ``adjusted[i]`` is the
    BY-adjusted p-value ``min_{k >= rank(i)} min(1, m * c(m) / k * p_(k))``,
    so ``rejected[i]`` is exactly ``adjusted[i] <= q``. NaN p-values are
    never rejected and get a NaN adjustment; they do not count toward ``m``.
    """
    ps = [float(p) for p in p_values]
    adjusted = [float("nan")] * len(ps)
    rejected = [False] * len(ps)
    valid = [i for i, p in enumerate(ps) if not math.isnan(p)]
    m = len(valid)
    if m == 0:
        return adjusted, rejected
    c_m = sum(1.0 / k for k in range(1, m + 1))
    order = sorted(valid, key=lambda i: ps[i])
    running = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        running = min(running, ps[idx] * m * c_m / rank)
        adjusted[idx] = min(1.0, running)
    # Step-up rejection, computed from the thresholds rather than from the
    # adjusted values, so the two can be checked against each other.
    k_star = 0
    for rank in range(1, m + 1):
        if ps[order[rank - 1]] <= rank / (m * c_m) * q:
            k_star = rank
    for rank in range(1, k_star + 1):
        rejected[order[rank - 1]] = True
    return adjusted, rejected


# ---------------------------------------------------------------------------
# Per-annotator test
# ---------------------------------------------------------------------------

def _one_sided_p(diffs: Sequence[float], epsilon: float, test: str) -> float:
    """P-value for H1: mean(diffs) < epsilon."""
    n = len(diffs)
    mean = sum(diffs) / n
    if all(d == diffs[0] for d in diffs):
        # Zero variance: the statistic is +/-inf (scipy returns the same 0/1
        # with a precision warning). Deterministic, so decide directly.
        return 0.0 if mean < epsilon else 1.0
    from scipy import stats

    if test == "ttest":
        return float(stats.ttest_1samp(list(diffs), epsilon, alternative="less").pvalue)
    if test == "wilcoxon":
        shifted = [d - epsilon for d in diffs]
        if all(s == 0 for s in shifted):
            return 1.0
        return float(stats.wilcoxon(shifted, alternative="less").pvalue)
    raise ValueError(f"unknown test {test!r}; use 'ttest' or 'wilcoxon'")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class AnnotatorAltResult:
    """One leave-one-out comparison: the LLM vs. annotator ``annotator_id``."""
    annotator_id: str
    n_items: int
    p_value: float
    p_value_adjusted: float
    rejected: bool
    # rho^f_j and rho^h_j: how often each side aligns at least as well.
    llm_advantage: float
    human_advantage: float
    # Mean alignment score S against the remaining annotators.
    llm_alignment: float
    human_alignment: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AltTestResult:
    """Outcome of :func:`alt_test`. ``passed`` is None when ``insufficient``."""
    passed: Optional[bool]
    winning_rate: Optional[float]
    advantage_probability: Optional[float]
    epsilon: float
    alpha: float
    metric: str
    test: str
    n_items: int
    n_annotators: int
    per_annotator: List[AnnotatorAltResult] = field(default_factory=list)
    skipped_annotators: List[Dict[str, Any]] = field(default_factory=list)
    n_items_dropped: int = 0
    insufficient: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["per_annotator"] = [a.to_dict() for a in self.per_annotator]
        return d


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------

def alt_test(
    llm: Mapping[Hashable, Any],
    humans: Mapping[Hashable, Mapping[Hashable, Any]],
    *,
    epsilon: float = DEFAULT_EPSILON,
    alpha: float = DEFAULT_Q,
    metric: Union[str, ScoringFn] = "accuracy",
    test: str = "ttest",
    min_items_per_annotator: int = MIN_ITEMS_PER_ANNOTATOR,
    min_annotators: int = MIN_ANNOTATORS,
    min_humans_per_item: int = MIN_HUMANS_PER_ITEM,
) -> AltTestResult:
    """
    Run the alt-test of Calderon, Reichart & Dror (ACL 2025).

    Args:
        llm: item id -> LLM label. ``None`` values are treated as missing.
        humans: annotator id -> (item id -> label). ``None`` labels are missing.
        epsilon: cost-benefit allowance (paper: 0.2 experts, 0.15 skilled,
            0.1 crowd workers).
        alpha: the BY target FDR ``q`` (paper: 0.05).
        metric: ``"accuracy"`` (categorical), ``"neg_rmse"`` (numeric /
            Likert), or a callable ``S(pred, remaining_annotations) -> float``
            where higher means better aligned.
        test: ``"ttest"`` (the paper's default) or ``"wilcoxon"`` (the paper's
            recommendation when annotators have fewer than 30 items; lower
            ``min_items_per_annotator`` to use it).
        min_items_per_annotator: annotators with fewer usable items are left
            out of the test and listed in ``skipped_annotators`` (paper: 30).
        min_annotators: fewer tested annotators than this makes the result
            ``insufficient`` (paper recommends 3; 2 is allowed but weaker).
        min_humans_per_item: items with fewer human labels are dropped
            (2 is the structural minimum: one left out, one remaining).

    Returns:
        An :class:`AltTestResult`.
    """
    if isinstance(metric, str):
        if metric not in SCORING_FUNCTIONS:
            raise ValueError(
                f"unknown metric {metric!r}; use one of {sorted(SCORING_FUNCTIONS)} or a callable"
            )
        score = SCORING_FUNCTIONS[metric]
        metric_name = metric
    elif callable(metric):
        score = metric
        metric_name = getattr(metric, "__name__", "custom")
    else:
        raise TypeError("metric must be a name or a callable")
    if test not in ("ttest", "wilcoxon"):
        raise ValueError(f"unknown test {test!r}; use 'ttest' or 'wilcoxon'")
    if min_humans_per_item < 2:
        raise ValueError("min_humans_per_item must be at least 2")

    def _result(**kw) -> AltTestResult:
        base = dict(
            passed=None, winning_rate=None, advantage_probability=None,
            epsilon=epsilon, alpha=alpha, metric=metric_name, test=test,
            n_items=0, n_annotators=0,
        )
        base.update(kw)
        return AltTestResult(**base)

    llm_labels = {i: v for i, v in llm.items() if v is not None}
    human_labels: Dict[Hashable, Dict[Hashable, Any]] = {
        h: {i: v for i, v in anns.items() if v is not None}
        for h, anns in humans.items()
    }

    # item -> annotators who labelled it (in annotator order).
    annotators_of: Dict[Hashable, List[Hashable]] = {}
    for h, anns in human_labels.items():
        for i in anns:
            annotators_of.setdefault(i, []).append(h)

    all_items = set(annotators_of)
    usable = {
        i for i, hs in annotators_of.items()
        if len(hs) >= min_humans_per_item and i in llm_labels
    }
    dropped = len(all_items) - len(usable)

    if not human_labels:
        return _result(insufficient="no human annotations")
    if not usable:
        return _result(
            n_items_dropped=dropped,
            insufficient=(
                f"no items have both an LLM label and at least "
                f"{min_humans_per_item} human labels"
            ),
        )

    tested_ids: List[Hashable] = []
    p_values: List[float] = []
    stats_rows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for h in human_labels:
        items = [i for i in human_labels[h] if i in usable]
        if len(items) < min_items_per_annotator:
            skipped.append({
                "annotator_id": str(h),
                "n_items": len(items),
                "reason": (
                    f"{len(items)} usable items, fewer than the "
                    f"{min_items_per_annotator} required"
                ),
            })
            continue
        w_f: List[int] = []
        w_h: List[int] = []
        s_f: List[float] = []
        s_h: List[float] = []
        for i in items:
            remaining = [human_labels[k][i] for k in annotators_of[i] if k != h]
            human_score = score(human_labels[h][i], remaining)
            llm_score = score(llm_labels[i], remaining)
            w_f.append(1 if llm_score >= human_score else 0)
            w_h.append(1 if human_score >= llm_score else 0)
            s_f.append(llm_score)
            s_h.append(human_score)
        diffs = [a - b for a, b in zip(w_h, w_f)]
        n = len(items)
        tested_ids.append(h)
        p_values.append(_one_sided_p(diffs, epsilon, test))
        stats_rows.append({
            "n_items": n,
            "llm_advantage": sum(w_f) / n,
            "human_advantage": sum(w_h) / n,
            "llm_alignment": sum(s_f) / n,
            "human_alignment": sum(s_h) / n,
        })

    n_tested = len(tested_ids)
    if n_tested < min_annotators:
        reasons = [
            f"{n_tested} annotator(s) have at least {min_items_per_annotator} "
            f"usable items; the test needs {min_annotators}"
        ]
        if skipped:
            reasons.append(
                "short: " + ", ".join(
                    f"{s['annotator_id']} ({s['n_items']})" for s in skipped
                )
            )
        return _result(
            n_items=len(usable), n_annotators=n_tested,
            skipped_annotators=skipped, n_items_dropped=dropped,
            insufficient="; ".join(reasons),
        )

    adjusted, rejected = benjamini_yekutieli(p_values, alpha)
    per_annotator = [
        AnnotatorAltResult(
            annotator_id=str(h),
            p_value=p,
            p_value_adjusted=adj,
            rejected=rej,
            **row,
        )
        for h, p, adj, rej, row in zip(tested_ids, p_values, adjusted, rejected, stats_rows)
    ]
    winning_rate = sum(rejected) / n_tested
    advantage = sum(r["llm_advantage"] for r in stats_rows) / n_tested
    return AltTestResult(
        passed=winning_rate >= PASS_THRESHOLD,
        winning_rate=winning_rate,
        advantage_probability=advantage,
        epsilon=epsilon,
        alpha=alpha,
        metric=metric_name,
        test=test,
        n_items=len(usable),
        n_annotators=n_tested,
        per_annotator=per_annotator,
        skipped_annotators=skipped,
        n_items_dropped=dropped,
    )
