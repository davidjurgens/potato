"""Held-out scores for peaks, signal intervals and robot episodes.

=========  ===============================================================
peaks      precision, recall and F1 of peaks matched one to one within a
           tolerance (the prediction's, or 0.5% of the spectrum's x range)
intervals  epoch mode: accuracy and macro-F1 over the annotated epochs;
           free mode: interval precision, recall and F1 at IoU 0.5
episode    phase accuracy and macro-F1 over a 10 Hz grid, phase segment F1
           at IoU 0.5, outcome accuracy, and Pearson's r of the reward curve
=========  ===============================================================

Standard library only, like :mod:`potato.training.evaluation`.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = ["score_peaks", "score_intervals", "score_episodes", "PEAK_TOLERANCE"]

#: Default peak tolerance, as a share of the spectrum's x range.
PEAK_TOLERANCE = 0.005
#: IoU at which a predicted interval or phase matches an annotated one.
SEGMENT_IOU = 0.5
#: Grid the phase timelines are compared on, in seconds.
PHASE_STEP = 0.1


def _f1(p: float, r: float) -> float:
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _macro_f1(gold: Sequence[str], predicted: Sequence[Optional[str]],
              ignore: Optional[str] = None) -> float:
    """Macro-F1 over the labels either side used; *ignore* (no phase) is a
    class for the counts but not one of the averaged labels."""
    labels = sorted((set(gold) | {p for p in predicted if p is not None}) - {ignore})
    if not labels:
        return 0.0
    scores = []
    for label in labels:
        tp = sum(1 for g, p in zip(gold, predicted) if g == label and p == label)
        fp = sum(1 for g, p in zip(gold, predicted) if g != label and p == label)
        fn = sum(1 for g, p in zip(gold, predicted) if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(_f1(precision, recall))
    return sum(scores) / len(scores)


# -------------------------------------------------------------------- peaks

def _peak_xs(value: Any) -> List[float]:
    peaks = value.get("peaks") if isinstance(value, dict) else value
    out = []
    for p in peaks if isinstance(peaks, list) else []:
        x = _num(p.get("x") if isinstance(p, dict) else p)
        if x is not None:
            out.append(x)
    return sorted(out)


def _tolerance(target: Any, payload: Any) -> float:
    if isinstance(payload, dict):
        given = _num(payload.get("tolerance"))
        if given is not None and given > 0:
            return given
        span = payload.get("x_range")
        if isinstance(span, list) and len(span) == 2:
            lo, hi = _num(span[0]), _num(span[1])
            if lo is not None and hi is not None and hi > lo:
                return PEAK_TOLERANCE * (hi - lo)
    xs = _peak_xs(target)
    return PEAK_TOLERANCE * (xs[-1] - xs[0]) if len(xs) > 1 else 0.0


def match_peaks(gold: Sequence[float], predicted: Sequence[float],
                tolerance: float) -> List[Tuple[int, int, float]]:
    """``(gold index, predicted index, distance)`` for peaks matched one to
    one, nearest pairs first, within *tolerance*."""
    pairs = sorted((abs(g - p), i, j) for i, g in enumerate(gold)
                   for j, p in enumerate(predicted) if abs(g - p) <= tolerance)
    used_g, used_p, out = set(), set(), []
    for distance, i, j in pairs:
        if i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        out.append((i, j, distance))
    return out


def score_peaks(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """Peaks pooled over spectra. A spectrum with no prediction contributes
    its peaks as misses; a predicted peak no annotated peak is near is a
    false alarm, including on a spectrum the annotator said has none."""
    tp = n_gold = n_pred = 0
    offsets: List[float] = []
    for target, payload in zip(gold, predicted):
        g, p = _peak_xs(target), _peak_xs(payload)
        n_gold += len(g)
        n_pred += len(p)
        tolerance = _tolerance(target, payload)
        for _i, _j, distance in match_peaks(g, p, tolerance):
            tp += 1
            offsets.append(distance)
    if not n_gold and not n_pred:
        return {}
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gold if n_gold else 0.0
    return {"precision": precision, "recall": recall, "f1": _f1(precision, recall),
            "mean_offset": sum(offsets) / len(offsets) if offsets else 0.0,
            "n_peaks": float(n_gold), "n_predicted_peaks": float(n_pred)}


# ---------------------------------------------------------------- intervals

def _intervals(value: Any) -> List[Tuple[float, float, str]]:
    ivs = value.get("intervals") if isinstance(value, dict) else value
    out = []
    for iv in ivs if isinstance(ivs, list) else []:
        if not isinstance(iv, dict):
            continue
        a, b = _num(iv.get("start")), _num(iv.get("end"))
        if a is not None and b is not None and b > a:
            out.append((a, b, str(iv.get("label", ""))))
    return out


def _label_at(intervals: Sequence[Tuple[float, float, str]], t: float) -> Optional[str]:
    for a, b, label in intervals:
        if a <= t < b:
            return label
    return None


def _iou(a: Tuple[float, float, str], b: Tuple[float, float, str]) -> float:
    overlap = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return overlap / union if union > 0 else 0.0


def _segment_counts(gold: Sequence[Tuple[float, float, str]],
                    predicted: Sequence[Tuple[float, float, str]]) -> int:
    """Matches at IoU >= SEGMENT_IOU, same label, one to one."""
    pairs = sorted(((_iou(a, b), i, j) for i, a in enumerate(gold)
                    for j, b in enumerate(predicted) if a[2] == b[2]), reverse=True)
    used_g, used_p, tp = set(), set(), 0
    for iou, i, j in pairs:
        if iou < SEGMENT_IOU or i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        tp += 1
    return tp


def score_intervals(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    """Epoch-mode targets are scored per epoch, at each annotated epoch's
    centre; free-mode targets as intervals. A run is one scheme, so one
    mode, which the first target names."""
    epoch = isinstance(gold[0], dict) and gold[0].get("mode") == "epoch"
    if epoch:
        g_labels: List[str] = []
        p_labels: List[Optional[str]] = []
        for target, payload in zip(gold, predicted):
            length = _num(target.get("epoch_length")) or 30.0
            guess = _intervals(payload)
            for a, b, label in _intervals(target):
                n = max(1, int(round((b - a) / length)))
                for k in range(n):
                    centre = a + (k + 0.5) * (b - a) / n
                    g_labels.append(label)
                    p_labels.append(_label_at(guess, centre))
        if not g_labels:
            return {}
        return {"accuracy": sum(1 for g, p in zip(g_labels, p_labels) if g == p) / len(g_labels),
                "macro_f1": _macro_f1(g_labels, p_labels),
                "n_epochs": float(len(g_labels))}
    tp = n_gold = n_pred = 0
    for target, payload in zip(gold, predicted):
        g, p = _intervals(target), _intervals(payload)
        n_gold += len(g)
        n_pred += len(p)
        tp += _segment_counts(g, p)
    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gold if n_gold else 0.0
    return {"interval_precision": precision, "interval_recall": recall,
            "interval_f1": _f1(precision, recall), "n_intervals": float(n_gold)}


# ----------------------------------------------------------------- episodes

def _outcome(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    outcome = value.get("outcome")
    if isinstance(outcome, dict):
        outcome = outcome.get("result")
    return str(outcome) if outcome not in (None, "") else None


def _reward(value: Any) -> List[Tuple[float, float]]:
    points = value.get("reward") if isinstance(value, dict) else None
    out = []
    for point in points if isinstance(points, list) else []:
        if isinstance(point, dict):
            t, v = _num(point.get("t")), _num(point.get("value"))
            if t is not None and v is not None:
                out.append((t, v))
    return sorted(out)


def _interp(points: Sequence[Tuple[float, float]], t: float) -> float:
    if t <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return points[-1][1]


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def score_episodes(gold: List[Any], predicted: List[Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    g_frames: List[str] = []
    p_frames: List[Optional[str]] = []
    tp = n_gold = n_pred = 0
    outcomes: List[Tuple[str, Optional[str]]] = []
    rewards_g: List[float] = []
    rewards_p: List[float] = []
    for target, payload in zip(gold, predicted):
        phases_g = _intervals({"intervals": target.get("phases")})
        phases_p = _intervals({"intervals": (payload or {}).get("phases")}) \
            if isinstance(payload, dict) else []
        if phases_g:
            end = max(b for _a, b, _l in phases_g)
            steps = int(end / PHASE_STEP)
            for k in range(steps):
                t = (k + 0.5) * PHASE_STEP
                g_frames.append(_label_at(phases_g, t) or "")
                p_frames.append(_label_at(phases_p, t) or "")
            n_gold += len(phases_g)
            n_pred += len(phases_p)
            tp += _segment_counts(phases_g, phases_p)
        if _outcome(target) is not None:
            outcomes.append((_outcome(target), _outcome(payload)))
        curve_g, curve_p = _reward(target), _reward(payload)
        if len(curve_g) >= 2 and curve_p:
            for t, v in curve_g:
                rewards_g.append(v)
                rewards_p.append(_interp(curve_p, t))
    if g_frames:
        out["phase_accuracy"] = sum(1 for g, p in zip(g_frames, p_frames) if g == p) / len(g_frames)
        out["phase_macro_f1"] = _macro_f1(g_frames, p_frames, ignore="")
        precision = tp / n_pred if n_pred else 0.0
        recall = tp / n_gold if n_gold else 0.0
        out["phase_segment_f1"] = _f1(precision, recall)
    if outcomes:
        out["outcome_accuracy"] = sum(1 for g, p in outcomes if g == p) / len(outcomes)
    r = _pearson(rewards_g, rewards_p)
    if r is not None:
        out["reward_pearson"] = r
    return out
