"""
Calibration metrics for judge predictions.

Pure functions (no Potato imports) computing Expected Calibration Error (ECE),
reliability-diagram bins, and the Brier score from per-prediction
(confidence, correctness) pairs. ``confidence`` is the k-sample vote fraction;
``correct`` is 1 if the modal prediction matched the human gold label else 0.

These did not exist anywhere in Potato — implemented here and covered by
known-value fixtures in tests/unit/test_jc_calibration.py.
"""

from typing import Dict, List, Sequence


def _bin_index(conf: float, n_bins: int) -> int:
    """Equal-width bin index in [0, n_bins-1]; conf==1.0 lands in the last bin."""
    if conf <= 0:
        return 0
    if conf >= 1:
        return n_bins - 1
    return min(n_bins - 1, int(conf * n_bins))


def reliability_bins(
    confidences: Sequence[float],
    correctness: Sequence[int],
    n_bins: int = 10,
) -> List[Dict[str, float]]:
    """Return per-bin stats for a reliability diagram.

    Each bin dict has: bin_lo, bin_hi, count, mean_confidence, accuracy.
    Empty bins are included (count=0) so the diagram has a consistent x-axis.
    """
    if len(confidences) != len(correctness):
        raise ValueError("confidences and correctness must be the same length")
    width = 1.0 / n_bins
    sums_conf = [0.0] * n_bins
    sums_corr = [0.0] * n_bins
    counts = [0] * n_bins
    for c, y in zip(confidences, correctness):
        b = _bin_index(float(c), n_bins)
        sums_conf[b] += float(c)
        sums_corr[b] += float(y)
        counts[b] += 1

    bins = []
    for b in range(n_bins):
        n = counts[b]
        bins.append({
            "bin_lo": round(b * width, 6),
            "bin_hi": round((b + 1) * width, 6),
            "count": n,
            "mean_confidence": round(sums_conf[b] / n, 6) if n else 0.0,
            "accuracy": round(sums_corr[b] / n, 6) if n else 0.0,
        })
    return bins


def expected_calibration_error(
    confidences: Sequence[float],
    correctness: Sequence[int],
    n_bins: int = 10,
) -> float:
    """ECE = sum over bins of (n_b/N) * |accuracy_b - mean_confidence_b|."""
    n_total = len(confidences)
    if n_total == 0:
        return 0.0
    ece = 0.0
    for b in reliability_bins(confidences, correctness, n_bins):
        if b["count"] == 0:
            continue
        ece += (b["count"] / n_total) * abs(b["accuracy"] - b["mean_confidence"])
    return round(ece, 6)


def brier_score(confidences: Sequence[float], correctness: Sequence[int]) -> float:
    """Mean squared error between confidence and correctness (lower is better)."""
    n = len(confidences)
    if n == 0:
        return 0.0
    return round(sum((float(c) - float(y)) ** 2 for c, y in zip(confidences, correctness)) / n, 6)


def calibration_report(
    confidences: Sequence[float],
    correctness: Sequence[int],
    n_bins: int = 10,
) -> Dict:
    """Bundle ECE, Brier, and reliability bins for one model."""
    return {
        "ece": expected_calibration_error(confidences, correctness, n_bins),
        "brier": brier_score(confidences, correctness),
        "n_bins": n_bins,
        "reliability_bins": reliability_bins(confidences, correctness, n_bins),
        "n": len(confidences),
    }
