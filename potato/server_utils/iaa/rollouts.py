"""
Agreement over world-model rollout evaluations.

"Do annotators agree on *when* the physics broke?" is measurable and, as far as
we can tell, unmeasured anywhere. Video-generation benchmarks report FVD and
win rates; none reports whether the humans producing those win rates agree with
each other, which means none of them can distinguish a model difference from
annotator noise.

## The same three questions as geometry, asked of a point in time

This module is deliberately shaped like :mod:`potato.server_utils.iaa.geometry_agreement`,
because the decomposition is the same and a dashboard that presented them
differently would imply they were different kinds of claim:

| Measure | Question |
|---|---|
| detection | Do annotators agree this rollout breaks *at all*? |
| localization | Given both marked a break, do they agree *when*? |
| category | Do they agree *why* it broke? |
| severity | Do they agree *how badly*? |

Plus nominal alpha over the preference winner and the counterfactual verdict,
which are ordinary categorical answers and need nothing new.

## The tolerance is swept, not chosen

Two break-points count as the same break when they are within a tolerance
window. Every number here depends on that window: annotators who agree to
within two seconds may agree on nothing at a quarter-second. Picking one
tolerance and reporting a single number makes the claim unfalsifiable, because
the reader cannot tell a tight agreement from a generous window.

So the report is a **sweep**. The default grid spans a frame or two up to a
couple of seconds, and the curve itself is the finding: agreement that is flat
across the sweep means annotators genuinely identify the same instant;
agreement that only appears at two seconds means they agree there is a problem
somewhere in the clip.

## Why "clean" changes the arithmetic

A stream with no marks from an annotator is ambiguous unless they said so. This
module therefore counts an annotator as having answered about a stream only if
they either marked a break on it or explicitly marked it clean. An annotator
who did neither is **excluded** from that stream's detection rows rather than
counted as having found nothing — counting them would manufacture agreement
between one person who checked and one who never looked.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .alpha import krippendorff_alpha

logger = logging.getLogger(__name__)

#: Tolerance windows, in seconds, at which the report is computed.
#:
#: The low end is roughly one frame at 24-30 fps; the high end is where "they
#: agree something is wrong in this shot" is the most that can be claimed.
DEFAULT_TOLERANCES = (0.04, 0.25, 0.5, 1.0, 2.0)

#: The tolerance whose numbers are quoted as *the* headline, when one must be.
#: Half a second: long enough to absorb reaction time and frame-stepping, short
#: enough that two annotators at that distance are looking at the same event.
DEFAULT_TOLERANCE = 0.5

#: Between-item pairs sampled for the chance baseline.
DEFAULT_CHANCE_SAMPLES = 2000

#: Seeded so a reported number is reproducible. An agreement statistic that
#: moves between runs of the same data cannot go in a paper.
DEFAULT_SEED = 20260815


# ---------------------------------------------------------------------------
# Matching break-points
# ---------------------------------------------------------------------------

def breakpoint_similarity(a: Dict[str, Any], b: Dict[str, Any],
                          tolerance: float) -> float:
    """
    How much two marks look like the same break: 1 at zero offset, 0 at the
    tolerance.

    A linear ramp rather than a step, so the matcher prefers the *closer* of
    two candidates inside the window instead of treating them as equally good.
    With a step function, a Hungarian assignment over three near-simultaneous
    marks is decided by tie-breaking order.
    """
    if tolerance <= 0:
        return 1.0 if a.get("t") == b.get("t") else 0.0
    try:
        delta = abs(float(a["t"]) - float(b["t"]))
    except (KeyError, TypeError, ValueError):
        return 0.0
    return max(0.0, 1.0 - delta / tolerance)


def match_breakpoints(marks_a: Sequence[Dict[str, Any]],
                      marks_b: Sequence[Dict[str, Any]],
                      tolerance: float,
                      ) -> Tuple[List[Tuple[int, int, float]], List[int], List[int]]:
    """
    Pair two annotators' marks on one stream, within the tolerance window.

    Delegates to :func:`potato.server_utils.iaa.geometry.match_instances` so the
    assignment is globally optimal (Hungarian) wherever scipy is available, and
    so this shares its behaviour with every other matched-pair measure in the
    package rather than growing a second, subtly different matcher.

    The threshold is just above zero because :func:`breakpoint_similarity`
    already returns 0 outside the window; a threshold of exactly 0 would match
    pairs that are precisely one tolerance apart, which is the boundary case
    the window is meant to exclude.
    """
    from . import geometry

    return geometry.match_instances(
        list(marks_a), list(marks_b), threshold=1e-9,
        sim_fn=lambda x, y: breakpoint_similarity(x, y, tolerance))


def _clusters(marks_by_annotator: Dict[str, List[Dict[str, Any]]],
              tolerance: float) -> List[Dict[str, Dict[str, Any]]]:
    """
    Group one stream's marks into clusters different annotators agree on.

    Greedy against the first annotator who contributed each cluster, matching
    :func:`geometry_agreement._matched_clusters`. The alternative — a global
    assignment across N annotators — is a much larger problem for a difference
    that only appears when several annotators mark near-simultaneous breaks,
    which is itself a sign the taxonomy needs splitting.
    """
    clusters: List[Dict[str, Dict[str, Any]]] = []
    for annotator in sorted(marks_by_annotator):
        for mark in marks_by_annotator[annotator]:
            placed = False
            for cluster in clusters:
                if annotator in cluster:
                    continue
                reference = next(iter(cluster.values()))
                if breakpoint_similarity(reference, mark, tolerance) > 0:
                    cluster[annotator] = mark
                    placed = True
                    break
            if not placed:
                clusters.append({annotator: mark})
    return clusters


# ---------------------------------------------------------------------------
# Reshaping stored annotations
# ---------------------------------------------------------------------------

def by_stream(marks: Sequence[Dict[str, Any]]
              ) -> Dict[str, List[Dict[str, Any]]]:
    """Split one annotator's marks by the rollout they belong to."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for mark in marks or []:
        if not isinstance(mark, dict):
            continue
        try:
            float(mark["t"])
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(str(mark.get("stream", "")), []).append(mark)
    for stream in out:
        out[stream].sort(key=lambda m: float(m["t"]))
    return out


def answered_streams(marks: Sequence[Dict[str, Any]],
                     clean: Sequence[str]) -> set:
    """
    Streams this annotator actually gave an answer about.

    The whole reason the schema makes "no breaks" an explicit act. Without it,
    an unmarked stream is indistinguishable between "watched it, nothing wrong"
    and "never got to it", and the two readings give opposite detection
    agreements.
    """
    return set(by_stream(marks).keys()) | {str(s) for s in (clean or [])}


# ---------------------------------------------------------------------------
# The measures
# ---------------------------------------------------------------------------

def detection_agreement(items: Dict[str, Dict[str, Dict[str, Any]]],
                        tolerance: float) -> Dict[str, Any]:
    """
    Alpha over present/absent per break cluster, per stream.

    ``items`` is ``{item_id: {annotator: {"violations": [...], "clean": [...]}}}``.

    A unit is one (item, stream, cluster). An annotator who answered about that
    stream contributes "present" or "absent"; one who did not answer about it
    contributes nothing at all.
    """
    rows: List[Tuple[str, str, str]] = []
    for item_id, by_annotator in items.items():
        streams = _streams_in(by_annotator)
        for stream in sorted(streams):
            responders = [a for a, value in by_annotator.items()
                          if stream in answered_streams(
                              value.get("violations"), value.get("clean"))]
            if len(responders) < 2:
                continue
            marks = {a: by_stream(by_annotator[a].get("violations")).get(
                stream, []) for a in responders}
            for index, cluster in enumerate(_clusters(marks, tolerance)):
                unit = f"{item_id}::{stream}#{index}"
                for annotator in responders:
                    rows.append((annotator, unit,
                                 "break" if annotator in cluster else "none"))
    return _alpha_result(rows, "nominal",
                         "every annotator marked the same breaks")


def category_agreement(items: Dict[str, Dict[str, Dict[str, Any]]],
                       tolerance: float, field: str = "type",
                       level: str = "nominal") -> Dict[str, Any]:
    """
    Alpha over a per-mark field, on clusters at least two annotators marked.

    Restricted to agreed-upon breaks on purpose: mixing in marks only one
    annotator made would conflate "we disagree what broke" with "one of us
    missed it", which is the detection question and is reported separately.

    ``level`` is ``"ordinal"`` for severity, because the distance between
    "subtle" and "breaks the scene" is genuinely larger than between adjacent
    grades, and nominal alpha would throw that away.
    """
    rows: List[Tuple[str, str, Any]] = []
    for item_id, by_annotator in items.items():
        for stream in sorted(_streams_in(by_annotator)):
            marks = {a: by_stream(v.get("violations")).get(stream, [])
                     for a, v in by_annotator.items()}
            marks = {a: m for a, m in marks.items() if m}
            for index, cluster in enumerate(_clusters(marks, tolerance)):
                if len(cluster) < 2:
                    continue
                unit = f"{item_id}::{stream}#{index}"
                for annotator, mark in cluster.items():
                    value = mark.get(field)
                    if value in (None, ""):
                        continue
                    rows.append((annotator, unit, value))
    return _alpha_result(
        rows, level, f"every matched break got the same {field}")


def localization(items: Dict[str, Dict[str, Dict[str, Any]]],
                 tolerance: float,
                 fps: float = 0.0,
                 chance_samples: int = DEFAULT_CHANCE_SAMPLES,
                 seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """
    How far apart matched break-points are, raw and chance-corrected.

    Two numbers, because they answer different questions:

    * ``mean_offset`` (and ``mean_offset_frames``) is the direct answer —
      "annotators place the break within 3.2 frames of each other" — and is what
      belongs in a paper's methods section.
    * ``sigma`` / ``ks`` are the chance-corrected forms, comparing the
      within-item offsets against offsets between *different* items. They are
      what makes the number comparable across corpora: a benchmark of one-second
      clips produces small offsets whether or not anyone agrees.

    ``sigma`` here is **conditional on a match**, so it is bounded by the
    tolerance by construction and rises as the tolerance falls. That is not a
    defect to correct for; it is why the report sweeps the tolerance rather
    than quoting one value.
    """
    within = _within_offsets(items, tolerance)
    between = _between_offsets(items, chance_samples, random.Random(seed))

    mean_within = (sum(within) / len(within)) if within else float("nan")
    mean_between = (sum(between) / len(between)) if between else float("nan")

    result: Dict[str, Any] = {
        "n_matched_pairs": len(within),
        "n_chance_pairs": len(between),
        "mean_offset": mean_within,
        "median_offset": _median(within),
        "mean_chance_offset": mean_between,
        "sigma": _sigma(within, between),
        "ks": _ks_statistic(within, between),
    }
    if fps > 0 and within:
        result["mean_offset_frames"] = mean_within * fps
        result["median_offset_frames"] = _median(within) * fps
    return result


def scalar_agreement(items: Dict[str, Dict[str, Dict[str, Any]]],
                     path: Sequence[str],
                     level: str = "nominal",
                     unanimous_note: str = "every annotator answered the same",
                     ) -> Dict[str, Any]:
    """
    Alpha over a single per-item answer — the preference winner, the
    counterfactual verdict.

    Blank answers are dropped rather than treated as a category: "did not say"
    is not a value two annotators can agree on, and counting it as one
    manufactures agreement between two people who both skipped the question.
    """
    rows: List[Tuple[str, str, Any]] = []
    for item_id, by_annotator in items.items():
        for annotator, value in by_annotator.items():
            node: Any = value
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
            if node in (None, "", []):
                continue
            rows.append((annotator, item_id, node))
    return _alpha_result(rows, level, unanimous_note)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def rollout_report(rows: Dict[str, Dict[str, Any]],
                   scheme: Optional[Dict[str, Any]] = None,
                   *,
                   tolerances: Sequence[float] = DEFAULT_TOLERANCES,
                   headline: float = DEFAULT_TOLERANCE,
                   chance_samples: int = DEFAULT_CHANCE_SAMPLES,
                   seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """
    The full report for a ``rollout_evaluation`` schema.

    ``rows`` is ``{item_id: {annotator_id: stored_value}}`` — the raw stored
    blob, not a pre-parsed one, so this function owns the parsing and cannot
    drift from what the client wrote.
    """
    from potato.server_utils import annotation_values

    items: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for item_id, per_user in rows.items():
        parsed = {}
        for user_id, stored in per_user.items():
            value = annotation_values.rollout_value(scheme or {}, stored)
            if value is not None:
                parsed[user_id] = value
        if len(parsed) >= 2:
            items[item_id] = parsed

    fps = float((scheme or {}).get("fps") or 0.0)

    report: Dict[str, Any] = {
        "n_items": len(items),
        "n_items_skipped": len(rows) - len(items),
        "fps": fps or None,
        "headline_tolerance": headline,
    }
    if not items:
        report["note"] = (
            "No item has two or more annotators, so agreement is undefined. "
            "Raise annotators_per_instance, or wait for more annotations.")
        return report

    # The sweep. Detection and localization are the two that move with the
    # tolerance; category and severity are computed on the clusters the
    # tolerance produces, so they move too.
    sweep = []
    grid = sorted(set(list(tolerances) + [headline]))
    for tolerance in grid:
        sweep.append({
            "tolerance": tolerance,
            "tolerance_frames": (tolerance * fps) if fps > 0 else None,
            "detection": detection_agreement(items, tolerance),
            "localization": localization(items, tolerance, fps=fps,
                                         chance_samples=chance_samples,
                                         seed=seed),
            "category": category_agreement(items, tolerance, "type"),
            "severity": category_agreement(items, tolerance, "severity",
                                           level="ordinal"),
        })
    report["sweep"] = sweep

    at_headline = next((row for row in sweep
                        if abs(row["tolerance"] - headline) < 1e-9), sweep[0])
    report["detection"] = at_headline["detection"]
    report["localization"] = at_headline["localization"]
    report["category"] = at_headline["category"]
    report["severity"] = at_headline["severity"]

    report["preference"] = scalar_agreement(
        items, ("preference", "winner"),
        unanimous_note="every annotator preferred the same rollout")
    report["counterfactual"] = scalar_agreement(
        items, ("counterfactual", "verdict"),
        unanimous_note="every annotator gave the same verdict")
    report["coverage"] = _coverage(items)
    return report


def _coverage(items: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """
    How much of the task was actually answered.

    Detection agreement is computed only over streams an annotator answered
    about, which is correct but silently narrows the denominator. Reporting the
    share of (annotator, stream) pairs that got an answer keeps that visible: a
    0.9 detection alpha over a third of the streams is a different claim from
    a 0.9 over all of them.
    """
    answered = 0
    possible = 0
    for by_annotator in items.values():
        streams = _streams_in(by_annotator)
        if not streams:
            continue
        for value in by_annotator.values():
            possible += len(streams)
            answered += len(answered_streams(value.get("violations"),
                                             value.get("clean")) & streams)
    return {
        "answered_stream_responses": answered,
        "possible_stream_responses": possible,
        "answered_fraction": (answered / possible) if possible else float("nan"),
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _streams_in(by_annotator: Dict[str, Dict[str, Any]]) -> set:
    """
    Every stream any annotator said anything about.

    Derived from the annotations rather than from the item, because the report
    runs from stored values alone — the manifest is on disk and the set may
    have been read months ago. A stream nobody mentioned contributes no rows
    either way, so nothing is lost.
    """
    streams: set = set()
    for value in by_annotator.values():
        streams |= answered_streams(value.get("violations"),
                                    value.get("clean"))
    return streams


def _within_offsets(items: Dict[str, Dict[str, Dict[str, Any]]],
                    tolerance: float) -> List[float]:
    """Absolute time offsets between matched marks, same item and stream."""
    out: List[float] = []
    for by_annotator in items.values():
        annotators = sorted(by_annotator)
        for stream in sorted(_streams_in(by_annotator)):
            marks = {a: by_stream(by_annotator[a].get("violations")).get(
                stream, []) for a in annotators}
            for i, left in enumerate(annotators):
                for right in annotators[i + 1:]:
                    if not marks[left] or not marks[right]:
                        continue
                    matches, _, _ = match_breakpoints(
                        marks[left], marks[right], tolerance)
                    for a_idx, b_idx, _score in matches:
                        out.append(abs(float(marks[left][a_idx]["t"])
                                       - float(marks[right][b_idx]["t"])))
    return out


def _between_offsets(items: Dict[str, Dict[str, Dict[str, Any]]],
                     samples: int, rng: random.Random) -> List[float]:
    """
    The chance baseline: offsets between marks on *different* items.

    This is what makes the measure chance-corrected. A benchmark of one-second
    clips produces small offsets whether or not anyone agrees, so the ratio
    stays honest instead of rewarding the corpus for being short.
    """
    pool: List[Tuple[str, float]] = []
    for item_id, by_annotator in items.items():
        for value in by_annotator.values():
            for mark in value.get("violations") or []:
                try:
                    pool.append((item_id, float(mark["t"])))
                except (KeyError, TypeError, ValueError):
                    continue
    if len(pool) < 2:
        return []

    out: List[float] = []
    attempts = 0
    limit = samples * 4
    while len(out) < samples and attempts < limit:
        attempts += 1
        left_item, left = pool[rng.randrange(len(pool))]
        right_item, right = pool[rng.randrange(len(pool))]
        if left_item == right_item:
            continue
        out.append(abs(left - right))
    return out


def _sigma(within: Sequence[float], between: Sequence[float]) -> float:
    """``1 - mean(within) / mean(between)``: alpha's form with an offset."""
    if not within or not between:
        return float("nan")
    expected = sum(between) / len(between)
    if expected <= 0:
        # Every mark in the corpus is at the same instant, so there is no
        # variation to agree about — undefined, not perfect.
        return float("nan")
    return 1.0 - (sum(within) / len(within)) / expected


def _ks_statistic(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Two-sample Kolmogorov-Smirnov statistic, in [0, 1].

    Duplicated from ``geometry_agreement`` rather than imported, because that
    module pulls in the whole geometry stack (mask decoding, cuboid volumes) on
    import and this one is reachable from a report that has no geometry in it.
    The statistic is a sorted merge; there is nothing to share but eleven lines.
    """
    if not a or not b:
        return float("nan")
    sorted_a, sorted_b = sorted(a), sorted(b)
    i = j = 0
    cdf_a = cdf_b = 0.0
    best = 0.0
    n, m = len(sorted_a), len(sorted_b)
    while i < n and j < m:
        if sorted_a[i] <= sorted_b[j]:
            i += 1
            cdf_a = i / n
        else:
            j += 1
            cdf_b = j / m
        best = max(best, abs(cdf_a - cdf_b))
    return best


def _median(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _alpha_result(rows, level: str, unanimous_note: str) -> Dict[str, Any]:
    """
    Alpha, plus a reason when it is undefined.

    Alpha divides by expected disagreement, so a corpus where every annotator
    gave the same answer everywhere has D_e = 0 and alpha is genuinely
    undefined — not 1.0. A bare NaN is technically right and practically
    useless, because the reader cannot tell "perfect agreement" from "the
    computation broke". So the unanimous case is named.
    """
    values = {str(row[2]) for row in rows}
    result: Dict[str, Any] = {
        "n_units": len({row[1] for row in rows}),
        "n_judgements": len(rows),
    }
    if len(rows) < 2:
        result["alpha"] = None
        result["note"] = "fewer than two judgements to compare"
        return result
    if len(values) < 2:
        result["alpha"] = None
        result["note"] = (
            f"{unanimous_note}, so there is no variation for alpha to correct "
            f"against. Perfect agreement, not a failed computation.")
        return result

    value = krippendorff_alpha(rows, level)
    result["alpha"] = None if (isinstance(value, float)
                               and math.isnan(value)) else value
    return result
