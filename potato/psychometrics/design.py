"""Study designer: power analysis for annotation studies, before you spend.

Answers the question every annotation project guesses at: *how many
annotators per item do I need?* For a given item count, expected annotator
accuracy, and label-space size, a Monte Carlo simulation with statistical
synthetic annotators (no LLM) estimates, for each candidate redundancy m:

- the sampling distribution of Krippendorff's alpha (mean + 95% interval),
- the accuracy of majority vote against the simulated truth,
- the total judgment count and cost.

The recommendation is the smallest m whose alpha 95% interval is narrower
than the target width — i.e., the cheapest design that still yields a
defensibly precise agreement estimate.

Krippendorff's alpha (nominal) is computed with a fast vectorized
implementation validated against ``simpledorff`` in the unit tests; the
simulation is seeded and fully deterministic.

CLI::

    python -m potato.psychometrics.design --items 500 --accuracy 0.75 \
        --classes 3 --target-ci 0.10 --cost 0.08
"""

import argparse
import json
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import numpy as np


def nominal_alpha(responses: np.ndarray, num_classes: int) -> float:
    """Krippendorff's alpha (nominal) for a complete items x annotators matrix.

    Args:
        responses: int array of shape (n_items, m) with values in [0, K).
        num_classes: K.

    Returns:
        Alpha in (-inf, 1]; nan when the coincidence matrix is degenerate
        (e.g., every response identical).
    """
    n_items, m = responses.shape
    if m < 2:
        return float("nan")
    # Per-item class counts via one-hot sum: (n_items, K)
    counts = np.zeros((n_items, num_classes), dtype=np.float64)
    np.add.at(counts, (np.arange(n_items)[:, None], responses), 1.0)
    # Within-item ordered co-occurrence pairs, normalized by (m_u - 1):
    # o[c, k] = sum_u (counts_uc * counts_uk - diag) / (m - 1)
    pair = np.einsum("uc,uk->ck", counts, counts)
    pair[np.diag_indices(num_classes)] -= counts.sum(axis=0)
    o = pair / (m - 1)
    n_c = o.sum(axis=1)
    n = n_c.sum()
    if n <= 1:
        return float("nan")
    d_observed = n - np.trace(o)
    # d_expected = sum_{c != k} n_c n_k / (n - 1)
    d_expected = (n_c.sum() ** 2 - (n_c**2).sum()) / (n - 1)
    if d_expected <= 0:
        return float("nan")
    return float(1.0 - d_observed / d_expected)


def simulate_responses(
    n_items: int,
    m: int,
    accuracy: float,
    num_classes: int,
    rng: np.random.Generator,
) -> tuple:
    """Simulate one study: (truth [n_items], responses [n_items x m])."""
    truth = rng.integers(0, num_classes, n_items)
    correct = rng.random((n_items, m)) < accuracy
    # Wrong answers: uniform over the K-1 other labels via a shifted draw.
    shift = rng.integers(1, num_classes, (n_items, m))
    wrong = (truth[:, None] + shift) % num_classes
    responses = np.where(correct, truth[:, None], wrong)
    return truth, responses


@dataclass
class DesignRow:
    """Simulation summary for one candidate annotators-per-item value."""

    annotators_per_item: int
    alpha_mean: float
    alpha_lo: float  # 2.5th percentile across simulations
    alpha_hi: float  # 97.5th percentile
    alpha_ci_width: float
    majority_accuracy: float
    total_judgments: int
    cost: Optional[float] = None


@dataclass
class DesignReport:
    """Full power-analysis report."""

    n_items: int
    annotator_accuracy: float
    num_classes: int
    target_ci_width: float
    n_simulations: int
    seed: int
    rows: List[DesignRow] = field(default_factory=list)
    recommended: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


def power_analysis(
    n_items: int,
    annotator_accuracy: float,
    num_classes: int = 2,
    target_ci_width: float = 0.10,
    min_annotators: int = 2,
    max_annotators: int = 8,
    n_simulations: int = 100,
    cost_per_judgment: Optional[float] = None,
    seed: int = 0,
) -> DesignReport:
    """Monte Carlo power analysis over candidate annotators-per-item values."""
    if n_items < 2:
        raise ValueError("n_items must be at least 2")
    if not 0.0 < annotator_accuracy <= 1.0:
        raise ValueError("annotator_accuracy must be in (0, 1]")
    if num_classes < 2:
        raise ValueError("num_classes must be at least 2")
    if min_annotators < 2:
        raise ValueError("min_annotators must be at least 2")
    if max_annotators < min_annotators:
        raise ValueError("max_annotators must be >= min_annotators")
    if n_simulations < 10:
        raise ValueError("n_simulations must be at least 10")

    report = DesignReport(
        n_items=n_items,
        annotator_accuracy=annotator_accuracy,
        num_classes=num_classes,
        target_ci_width=target_ci_width,
        n_simulations=n_simulations,
        seed=seed,
    )
    rng = np.random.default_rng(seed)
    for m in range(min_annotators, max_annotators + 1):
        alphas = np.empty(n_simulations)
        majority_hits = np.empty(n_simulations)
        for s in range(n_simulations):
            truth, responses = simulate_responses(
                n_items, m, annotator_accuracy, num_classes, rng
            )
            alphas[s] = nominal_alpha(responses, num_classes)
            counts = np.zeros((n_items, num_classes))
            np.add.at(counts, (np.arange(n_items)[:, None], responses), 1.0)
            # Deterministic-but-unbiased tie break via tiny seeded jitter.
            counts += rng.random(counts.shape) * 1e-9
            majority_hits[s] = float(np.mean(np.argmax(counts, axis=1) == truth))
        alphas = alphas[~np.isnan(alphas)]
        if alphas.size == 0:
            continue
        lo, hi = np.percentile(alphas, [2.5, 97.5])
        row = DesignRow(
            annotators_per_item=m,
            alpha_mean=round(float(np.mean(alphas)), 4),
            alpha_lo=round(float(lo), 4),
            alpha_hi=round(float(hi), 4),
            alpha_ci_width=round(float(hi - lo), 4),
            majority_accuracy=round(float(np.mean(majority_hits)), 4),
            total_judgments=n_items * m,
            cost=(
                round(n_items * m * cost_per_judgment, 2)
                if cost_per_judgment is not None
                else None
            ),
        )
        report.rows.append(row)
        if report.recommended is None and row.alpha_ci_width <= target_ci_width:
            report.recommended = m
    return report


def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m potato.psychometrics.design",
        description=(
            "Power analysis for annotation studies: how many annotators per "
            "item for a defensibly precise agreement estimate?"
        ),
    )
    parser.add_argument("--items", type=int, required=True, help="number of items")
    parser.add_argument(
        "--accuracy",
        type=float,
        required=True,
        help="expected per-annotator accuracy in (0, 1], e.g. from a pilot",
    )
    parser.add_argument("--classes", type=int, default=2, help="number of labels")
    parser.add_argument(
        "--target-ci",
        type=float,
        default=0.10,
        help="target width of the 95%% interval on alpha (default 0.10)",
    )
    parser.add_argument("--min-annotators", type=int, default=2)
    parser.add_argument("--max-annotators", type=int, default=8)
    parser.add_argument("--sims", type=int, default=100)
    parser.add_argument("--cost", type=float, default=None, help="cost per judgment")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    report = power_analysis(
        n_items=args.items,
        annotator_accuracy=args.accuracy,
        num_classes=args.classes,
        target_ci_width=args.target_ci,
        min_annotators=args.min_annotators,
        max_annotators=args.max_annotators,
        n_simulations=args.sims,
        cost_per_judgment=args.cost,
        seed=args.seed,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    print(
        f"Power analysis: {report.n_items} items, "
        f"accuracy {report.annotator_accuracy:.2f}, "
        f"{report.num_classes} labels, {report.n_simulations} simulations"
    )
    header = (
        f"{'ann/item':>8} {'alpha':>7} {'95% interval':>16} {'width':>7} "
        f"{'majority acc':>13} {'judgments':>10}"
    )
    if any(r.cost is not None for r in report.rows):
        header += f" {'cost':>10}"
    print(header)
    for row in report.rows:
        line = (
            f"{row.annotators_per_item:>8} {row.alpha_mean:>7.3f} "
            f"[{row.alpha_lo:>6.3f}, {row.alpha_hi:>6.3f}] "
            f"{row.alpha_ci_width:>7.3f} {row.majority_accuracy:>13.3f} "
            f"{row.total_judgments:>10}"
        )
        if row.cost is not None:
            line += f" {row.cost:>10.2f}"
        marker = "  <- recommended" if row.annotators_per_item == report.recommended else ""
        print(line + marker)
    if report.recommended is None:
        print(
            f"No m <= {report.rows[-1].annotators_per_item if report.rows else '?'} "
            f"reaches a {report.target_ci_width:.2f}-wide alpha interval; "
            "consider more items or better-trained annotators."
        )


if __name__ == "__main__":
    _main()
