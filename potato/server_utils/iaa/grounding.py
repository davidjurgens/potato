"""
Agreement between annotators on a ``grounding_eval`` schema.

## Why this is not the geometry report

The geometry report (``_aggregate_blobs``) has a hard problem: two annotators
draw N and M shapes on the same image and nothing says which of theirs is which
of ours, so it has to *match* them before it can compare them, and a matching
mistake is indistinguishable from a disagreement.

Grounding has no such problem. Every region is drawn in answer to a named
referring expression, so the expression id **is** the correspondence. What is
left is a much cleaner question, and it splits into three that have different
answers and different remedies:

===================  ==========================================================
Do they agree...     Measured by
===================  ==========================================================
that it is there?    alpha over located / not-present — a genuine categorical
                     variable, and the one place chance correction matters,
                     because two annotators who say "present" to everything
                     agree perfectly by construction
where it is?         similarity between the regions, swept across IoU
                     thresholds
at all?              coverage — the fraction of expressions anyone answered
===================  ==========================================================

Blending them would hide which one went wrong. "Annotators disagree about the
red mug" means something different if one of them says there is no red mug than
if they both found it and drew different boxes: the first is a problem with the
expression, the second with the drawing.

## Points are scored as distance, never with the region measure

A point has no area, so there is no overlap to compute and
``region_similarity`` falls back to a distance-derived score. That score is
compressed into the top of the range: two annotators pointing at **opposite
corners of the image** — the most complete disagreement available — still score
about 0.86, which the admin page bands as *strong agreement*, in green.

So the region measure applied to a ``region_type: point`` schema does not merely
lose precision; it reports near-perfect agreement no matter what the annotators
did. That is a confidently wrong number, which is worse than a missing one, and
it is measured in ``tests/unit/test_iaa_grounding.py`` rather than asserted here.

Points therefore get their own section measuring the **distance** between them
in normalized image units, where 0 is perfect and there is no ceiling to
saturate against. It is on a different scale from IoU and is named a distance so
nothing bands it as a coefficient; the two are never averaged together.

## An unanswered expression is excluded, not counted as a disagreement

Counting silence as disagreement makes annotators look worse the more they
skipped, which is a statement about their diligence rather than about whether
they agree — and it makes the number improve when you *remove* the hard
expressions. The count is reported separately so the exclusion is visible.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from potato.server_utils.iaa.alpha import krippendorff_alpha

logger = logging.getLogger(__name__)

#: Client ``type`` values that are a bare point. These have no interior, so they
#: are routed to the distance measure rather than to region similarity.
POINT_TYPES = frozenset({"landmark", "point", "keypoint"})

#: Swept rather than fixed, for the same reason the rollout report sweeps its
#: matching window: agreement that holds at 0.9 means annotators draw the same
#: box, agreement that appears only at 0.25 means the most anyone can claim is
#: that they found the same object.
DEFAULT_IOU_THRESHOLDS = (0.25, 0.5, 0.75, 0.9)

#: The threshold quoted in the headline. 0.5 is the COCO convention and the one
#: readers assume when a single number is given without one.
HEADLINE_THRESHOLD = 0.5

LOCATED = "located"
NOT_PRESENT = "not_present"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_answers(stored: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    ``{expression_id: {"regions": [...], "absent": bool}}`` from one stored blob.

    Returns None when the blob is not a grounding payload at all, so a schema
    misconfiguration shows up as "no data" rather than as silent zeros.
    """
    value = stored
    if isinstance(value, dict) and "regions" not in value and "absent" not in value:
        # The dispatcher hands over `{label: value}` for some schemas.
        value = next(iter(value.values()), None)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None

    regions = value.get("regions")
    absent = value.get("absent")
    if not isinstance(regions, dict) and not isinstance(absent, list):
        return None

    answers: Dict[str, Dict[str, Any]] = {}
    for expression_id, shapes in (regions or {}).items():
        if isinstance(shapes, list) and shapes:
            answers[str(expression_id)] = {"regions": shapes, "absent": False}
    for expression_id in (absent or []):
        # An explicit not-present wins over a stale region list: the client
        # clears the regions when the annotator presses the absent button, and
        # trusting the leftovers would resurrect an answer they retracted.
        answers[str(expression_id)] = {"regions": [], "absent": True}
    return answers


def parse_rows(rows: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Dict]]:
    """``{item: {annotator: parsed_answers}}``, dropping items with < 2 usable."""
    parsed: Dict[str, Dict[str, Dict]] = {}
    for item_id, per_user in (rows or {}).items():
        usable = {}
        for user_id, stored in per_user.items():
            answers = parse_answers(stored)
            if answers is not None:
                usable[user_id] = answers
        if len(usable) >= 2:
            parsed[item_id] = usable
    return parsed


# ---------------------------------------------------------------------------
# Similarity between two answers to the same expression
# ---------------------------------------------------------------------------

def _is_point(region: Any) -> bool:
    return (isinstance(region, dict)
            and str(region.get("type", "")).lower() in POINT_TYPES)


def _point_xy(region: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    coordinates = region.get("coordinates")
    if isinstance(coordinates, dict) and "x" in coordinates and "y" in coordinates:
        try:
            return float(coordinates["x"]), float(coordinates["y"])
        except (TypeError, ValueError):
            return None
    if isinstance(coordinates, list) and coordinates:
        first = coordinates[0]
        if isinstance(first, dict) and "x" in first and "y" in first:
            try:
                return float(first["x"]), float(first["y"])
            except (TypeError, ValueError):
                return None
    return None


def set_similarity(a: Sequence[Dict], b: Sequence[Dict]) -> Optional[float]:
    """
    Similarity between two annotators' region *sets* for one expression.

    The schema is built for one region per expression and that is the case this
    reduces to exactly — with one region each, this is plain IoU. But an
    expression like "the two cats" legitimately takes several, so the general
    case is a greedy best-match with the leftovers counted against the score:

        sum(matched similarity) / max(len(a), len(b))

    Dividing by the larger set is what makes an unmatched region cost something.
    Dividing by the number of matches instead would score "I found one of your
    three" as perfect agreement about that one, which is true and useless.

    Returns None when either side has no comparable region.
    """
    from potato.grounding.metrics import region_similarity

    left = [r for r in a if isinstance(r, dict)]
    right = [r for r in b if isinstance(r, dict)]
    if not left or not right:
        return None

    remaining = list(range(len(right)))
    total = 0.0
    for region in left:
        best_score, best_index = 0.0, None
        for index in remaining:
            try:
                score = region_similarity(region, right[index])
            except Exception:  # a malformed shape must not sink the report
                logger.debug("region_similarity failed", exc_info=True)
                continue
            if score > best_score:
                best_score, best_index = score, index
        if best_index is not None:
            total += best_score
            remaining.remove(best_index)
    return total / max(len(left), len(right))


def point_distance(a: Sequence[Dict], b: Sequence[Dict]) -> Optional[float]:
    """
    Distance between two annotators' points, in normalized image units.

    Only the first point on each side: a ``region_type: point`` schema collects
    one point per expression, and averaging over a set here would quietly
    average distances that belong to different referents.
    """
    left = next((_point_xy(r) for r in a if _is_point(r)), None)
    right = next((_point_xy(r) for r in b if _is_point(r)), None)
    if left is None or right is None:
        return None
    return math.hypot(left[0] - right[0], left[1] - right[1])


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def grounding_report(rows: Dict[str, Dict[str, Any]],
                     scheme: Optional[Dict[str, Any]] = None,
                     thresholds: Sequence[float] = DEFAULT_IOU_THRESHOLDS,
                     ) -> Dict[str, Any]:
    """
    Detection, localization and coverage agreement over a grounding schema.

    ``rows`` is ``{item_id: {user_id: stored_blob}}`` exactly as ``_gather_raw``
    produces it. Blobs are parsed here rather than by the caller so that the
    measure and the parser cannot drift apart — the same reason the episode and
    rollout reports take their input raw.
    """
    scheme = scheme or {}
    parsed = parse_rows(rows)

    # (annotator, expression_key, value) for the detection alpha. The expression
    # key is item-scoped because the same expression id may appear on many items
    # and they are different questions.
    detection_long: List[Tuple[str, str, str]] = []
    detection_hits = detection_pairs = 0

    localization_scores: List[float] = []
    point_distances: List[float] = []
    n_multi_region = 0

    answered = possible = 0

    for item_id, per_user in parsed.items():
        expression_ids = sorted({eid for answers in per_user.values()
                                 for eid in answers})
        for expression_id in expression_ids:
            key = f"{item_id}::{expression_id}"
            answers_here: Dict[str, Dict[str, Any]] = {}
            for user_id, answers in per_user.items():
                possible += 1
                answer = answers.get(expression_id)
                if not answer:
                    continue
                answered += 1
                answers_here[user_id] = answer
                detection_long.append(
                    (user_id, key, NOT_PRESENT if answer["absent"] else LOCATED))

            if len(answers_here) < 2:
                continue

            users = sorted(answers_here)
            for i in range(len(users)):
                for j in range(i + 1, len(users)):
                    left = answers_here[users[i]]
                    right = answers_here[users[j]]
                    detection_pairs += 1
                    if left["absent"] == right["absent"]:
                        detection_hits += 1
                    if left["absent"] or right["absent"]:
                        # One of them says there is nothing to locate, so there
                        # is no localization question to ask. It is already
                        # counted as a detection disagreement above; scoring it
                        # as an IoU of 0 as well would penalise it twice.
                        continue
                    if len(left["regions"]) > 1 or len(right["regions"]) > 1:
                        n_multi_region += 1
                    if any(_is_point(r) for r in left["regions"]):
                        distance = point_distance(left["regions"], right["regions"])
                        if distance is not None:
                            point_distances.append(distance)
                        continue
                    score = set_similarity(left["regions"], right["regions"])
                    if score is not None:
                        localization_scores.append(score)

    report: Dict[str, Any] = {
        "detection": _detection_section(detection_long, detection_hits,
                                        detection_pairs),
        "localization": _localization_section(localization_scores, n_multi_region),
        "coverage": {
            "answered_fraction": (answered / possible) if possible else float("nan"),
            "n_answered": answered,
            "n_unanswered_excluded": possible - answered,
        },
    }

    if point_distances:
        report["pointing"] = {
            # Named a distance, not an agreement: 0 is perfect and it has no
            # upper bound of 1, so reading it against the kappa conventions
            # would invert it.
            "mean_pairwise_distance": sum(point_distances) / len(point_distances),
            "median_pairwise_distance": _median(point_distances),
            "n_pairs_compared": len(point_distances),
        }

    sweep = []
    for threshold in thresholds:
        sweep.append({
            "iou_threshold": float(threshold),
            "localization": {
                "agreement": _fraction_at_least(localization_scores, threshold),
            },
        })
    if sweep:
        report["sweep"] = sweep
        # Named rather than inferred, so a presenter never has to guess which
        # key of a sweep row is the parameter.
        report["sweep_parameter"] = "iou_threshold"
        report["sweep_parameter_label"] = "IoU threshold"
        report["headline_iou_threshold"] = float(HEADLINE_THRESHOLD)

    report["region_type"] = str(scheme.get("region_type", "box")).lower()
    return report


def _detection_section(long_format, hits, pairs) -> Dict[str, Any]:
    """
    Alpha AND raw percent agreement, because either alone misleads here.

    Percent agreement is inflated whenever one answer dominates, and in most
    grounding corpora almost every expression is present — so a lazy annotator
    who never presses "not present" scores near 1.0. Alpha corrects for that,
    but is undefined when *every* answer is the same, which is a perfectly
    normal corpus. Reporting both means the degenerate case is legible instead
    of appearing as a missing number.
    """
    distinct = {value for _, _, value in long_format}
    section: Dict[str, Any] = {
        "percent_agreement": (hits / pairs) if pairs else float("nan"),
        "n_expression_pairs": pairs,
        "n_present_absent_answers": len(long_format),
    }
    if len(distinct) < 2:
        section["alpha"] = float("nan")
        section["note"] = (
            "alpha is undefined: every answer was "
            f"{next(iter(distinct), 'absent')!r}, so there is no variation to "
            "correct for chance against.")
        return section
    try:
        section["alpha"] = krippendorff_alpha(long_format, level="nominal")
    except Exception:
        logger.warning("detection alpha failed", exc_info=True)
        section["alpha"] = float("nan")
    return section


def _localization_section(scores: List[float], n_multi_region: int) -> Dict[str, Any]:
    section: Dict[str, Any] = {
        "mean_iou": (sum(scores) / len(scores)) if scores else float("nan"),
        "median_iou": _median(scores) if scores else float("nan"),
        "n_pairs_compared": len(scores),
    }
    if n_multi_region:
        # Surfaced rather than silently averaged in: a multi-region answer is
        # scored by a greedy match, which is an approximation, and a reader
        # should know how much of the number rests on one.
        section["n_pairs_multi_region"] = n_multi_region
    return section


def _fraction_at_least(scores: Sequence[float], threshold: float) -> float:
    if not scores:
        return float("nan")
    return sum(1 for value in scores if value >= threshold) / len(scores)


def _median(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0
