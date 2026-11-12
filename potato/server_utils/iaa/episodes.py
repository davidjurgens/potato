"""
Agreement over episode annotations.

An episode annotation is three different kinds of answer in one value, and
they need three different measures. Reporting one blended number would hide
which of them the annotators actually disagreed about — and they are fixed in
completely different ways:

| Layer | Question | Measure |
|---|---|---|
| phases | Do they agree *when* each phase was? | Temporal IoU, through the existing segment path |
| outcome | Do they agree whether it worked? | Krippendorff's alpha, nominal |
| reward | Do they agree how well it was going? | ICC and correlation on a common grid |

Nobody currently reports whether robot-data labels are reliable at all, so the
bar is low; the point of splitting them is that "they agree it failed but not
when the grasp started" and "they agree on the phases but not on whether it
worked" are different problems with different remedies.

## Why the reward curve is resampled

Two annotators draw a curve by dragging, so their samples land at different
times and in different numbers. Comparing them pointwise is impossible. Both
are linearly interpolated onto a common grid — the same interpolation the
timeline draws — and the resulting paired series go through
:mod:`potato.server_utils.iaa.continuous` unchanged.

Outside the drawn range the interpolation returns **nothing**, not zero.
"The annotator did not say" and "the annotator said zero" are different, and a
reward model trained on the second when the first was true learns that
unlabelled regions are bad.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Points on the common grid the reward curves are resampled onto. 200 is
#: dense enough that a one-second feature in a five-minute episode survives,
#: and coarse enough that the ICC is not dominated by interpolation.
DEFAULT_GRID = 200


def reward_at(points: Sequence[Dict[str, float]], t: float) -> Optional[float]:
    """
    Linear interpolation of a drawn reward curve, or None outside its range.

    Mirrors `rewardAt` in `episode-timeline.js` exactly, including the refusal
    to extrapolate. The two must agree: the annotator judges the curve by what
    the timeline drew, and scoring a different curve than the one they saw
    makes the number unattributable.
    """
    if not points:
        return None
    if t < points[0]["t"] or t > points[-1]["t"]:
        return None
    for i in range(1, len(points)):
        if t <= points[i]["t"]:
            a, b = points[i - 1], points[i]
            span = b["t"] - a["t"]
            if span <= 0:
                return b["value"]
            return a["value"] + (b["value"] - a["value"]) * ((t - a["t"]) / span)
    return points[-1]["value"]


def resample_pair(a: Sequence[Dict[str, float]],
                  b: Sequence[Dict[str, float]],
                  duration: float,
                  grid: int = DEFAULT_GRID) -> Tuple[List[float], List[float]]:
    """
    Two curves on a common grid, restricted to where **both** annotators drew.

    The overlap restriction is the whole correctness of this: comparing a
    region one annotator labelled against one they did not is comparing a
    judgement to an absence, and it drags the correlation toward whatever the
    other annotator happened to draw there.
    """
    if not a or not b or grid <= 1 or duration <= 0:
        return [], []
    xs: List[float] = []
    ys: List[float] = []
    for i in range(grid):
        t = duration * i / (grid - 1)
        va, vb = reward_at(a, t), reward_at(b, t)
        if va is None or vb is None:
            continue
        xs.append(va)
        ys.append(vb)
    return xs, ys


def reward_agreement(curves: Dict[str, Sequence[Dict[str, float]]],
                     duration: float,
                     grid: int = DEFAULT_GRID) -> Dict[str, Any]:
    """
    Agreement between annotators' reward curves for one episode.

    Returns ICC(2,1) and Pearson r across every annotator pair, plus the
    fraction of the episode both members of a pair actually covered — a high
    correlation over 5% of the timeline is not evidence about the other 95%,
    and reporting it without the coverage invites exactly that reading.
    """
    from potato.server_utils.iaa import continuous

    users = sorted(k for k, v in curves.items() if v)
    if len(users) < 2:
        return {"n_annotators": len(users), "note": "needs two curves"}

    iccs: List[float] = []
    rs: List[float] = []
    coverages: List[float] = []

    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            xs, ys = resample_pair(curves[users[i]], curves[users[j]],
                                   duration, grid)
            coverages.append(len(xs) / float(grid))
            if len(xs) < 3:
                continue
            # Both return NaN rather than None when undefined, so the guard
            # is a self-comparison rather than an `is not None`.
            icc = continuous.icc_2_1([list(pair) for pair in zip(xs, ys)])
            if icc == icc:
                iccs.append(icc)
            r = continuous.pearson_r(xs, ys)
            if r == r:
                rs.append(r)

    return {
        "n_annotators": len(users),
        "reward_icc": _mean(iccs),
        "reward_pearson_r": _mean(rs),
        "reward_coverage": _mean(coverages),
    }


def outcome_agreement(outcomes: Dict[str, Dict[str, Optional[str]]]
                      ) -> Dict[str, Any]:
    """
    Krippendorff's alpha over the per-episode outcome label.

    ``outcomes`` is ``{item_id: {user_id: label_or_None}}``. Unanswered
    outcomes are dropped rather than treated as a category: "did not say" is
    not a value annotators can agree on, and counting it as one manufactures
    agreement between two people who both skipped the question.
    """
    from potato.server_utils.iaa.alpha import krippendorff_alpha

    # (annotator, item, value) tuples -- the shape krippendorff_alpha takes.
    long_format = []
    answered = 0
    for item_id, per_user in outcomes.items():
        for user_id, label in per_user.items():
            if not label:
                continue
            answered += 1
            long_format.append((user_id, item_id, label))

    if answered < 2:
        return {"outcome_alpha": None,
                "outcome_alpha_note": "fewer than two outcomes were recorded"}

    labels = {row[2] for row in long_format}
    if len(labels) < 2:
        # Alpha divides by expected disagreement, which is zero when every
        # annotator gave the same answer everywhere. That is genuinely
        # undefined, not 1.0 -- and a bare NaN cannot be told from a broken
        # computation, so it travels with its reason.
        return {"outcome_alpha": None,
                "outcome_alpha_note": (
                    f"every annotator recorded '{next(iter(labels))}', so "
                    f"there is no variation for alpha to correct against. "
                    f"Perfect agreement, not a failed computation.")}

    alpha = krippendorff_alpha(long_format, level="nominal")
    return {"outcome_alpha": None if alpha != alpha else alpha,
            "n_outcomes": answered}


def episode_report(rows: Dict[str, Dict[str, Any]],
                   scheme: Dict[str, Any],
                   durations: Optional[Dict[str, float]] = None
                   ) -> Dict[str, Any]:
    """
    The full three-part report for an ``episode_annotation`` schema.

    ``rows`` is ``{item_id: {user_id: stored_value}}`` — the raw stored blob,
    not a pre-parsed one, so this function owns the parsing and cannot drift
    from what the timeline wrote.
    """
    from potato.server_utils import annotation_values
    from potato.server_utils.iaa.dispatcher import _aggregate_blobs

    segment_rows: Dict[str, Dict[str, Any]] = {}
    outcome_rows: Dict[str, Dict[str, Optional[str]]] = {}
    reward_metrics: List[Dict[str, Any]] = []

    for item_id, per_user in rows.items():
        segments = {}
        curves = {}
        outcomes = {}
        for user_id, stored in per_user.items():
            segments[user_id] = annotation_values.temporal_segments(
                scheme, stored)
            curves[user_id] = annotation_values.reward_curve(scheme, stored)
            outcomes[user_id] = annotation_values.episode_outcome(
                scheme, stored)

        if len(segments) >= 2:
            segment_rows[item_id] = segments
        if len(outcomes) >= 2:
            outcome_rows[item_id] = outcomes

        duration = (durations or {}).get(item_id) or _implied_duration(curves,
                                                                      segments)
        if duration > 0 and sum(1 for c in curves.values() if c) >= 2:
            reward_metrics.append(reward_agreement(curves, duration))

    report: Dict[str, Any] = {"n_items": len(rows)}
    if segment_rows:
        report["phases"] = _aggregate_blobs(segment_rows, scheme)
    if outcome_rows:
        report["outcome"] = outcome_agreement(outcome_rows)
    if reward_metrics:
        report["reward"] = {
            key: _mean([m[key] for m in reward_metrics
                        if m.get(key) is not None])
            for key in ("reward_icc", "reward_pearson_r", "reward_coverage")
        }
    return report


def _implied_duration(curves, segments) -> float:
    """
    How long the episode was, from the annotations themselves.

    A fallback for when the caller cannot supply it — the manifest is on disk
    and the agreement report runs from stored values alone. Using the furthest
    annotation is an underestimate of the episode, which makes the reward grid
    slightly denser than it needs to be and changes no conclusion.
    """
    ends = [p["t"] for curve in curves.values() for p in curve]
    ends += [s["end"] for group in segments.values() for s in group]
    return max(ends) if ends else 0.0


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    real = [v for v in values if v is not None]
    return sum(real) / len(real) if real else None
