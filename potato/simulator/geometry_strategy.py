"""
Geometry generation and perturbation for simulated annotators.

The simulator could not produce image annotations at all, so vision projects
could not be piloted, load-tested, or — most importantly — used to validate the
agreement statistics against a known ground truth. Every other modality could.

The noise model is the point. Real annotators do not disagree by picking a
different label from a list; they disagree by drawing the same object slightly
differently, missing an object, hallucinating one, or calling it the wrong
thing. Those are four separate failure modes with four separate remedies, and
``iaa.dispatcher`` reports them separately — so the simulator has to be able to
produce them separately or the report cannot be checked.

All objects use the client coordinate contract: normalized 0..1 under
``coordinates``. Nothing here builds a shape by hand that the client would not
produce.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence

#: Tools a simulated annotator can draw with, absent explicit configuration.
DEFAULT_TOOLS = ("bbox",)

#: Even a perfect annotator does not reproduce a boundary exactly. Keeping a
#: floor here is deliberate: a simulator that emits byte-identical geometry
#: would make an exact-match comparator look correct, which is precisely the
#: bug that made image gold standards unusable.
#:
#: Calibrated in normalized units against a realistic expert boundary error of
#: ~2-3px on a 640px image. This matters more than it looks: the error applies
#: independently to each annotator, and IoU punishes a fixed pixel error far
#: harder on small objects (the same 0.004 costs a 0.08-wide box ~4x the IoU it
#: costs a 0.30-wide one), which is exactly why detection benchmarks report
#: small-object accuracy separately.
MIN_JITTER = 0.004


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _pick_label(labels: Sequence[str], rng: random.Random) -> str:
    return rng.choice(list(labels)) if labels else "object"


def random_objects(
    labels: Sequence[str],
    tools: Sequence[str] = DEFAULT_TOOLS,
    rng: Optional[random.Random] = None,
    count_range: tuple = (1, 4),
) -> List[Dict[str, Any]]:
    """A plausible set of shapes for one image, in client-contract form."""
    rng = rng or random
    tools = [t for t in (tools or DEFAULT_TOOLS) if t in _BUILDERS] or list(DEFAULT_TOOLS)

    count = rng.randint(*count_range)
    return [
        _BUILDERS[rng.choice(tools)](_pick_label(labels, rng), rng)
        for _ in range(count)
    ]


def _build_bbox(label: str, rng: random.Random) -> Dict[str, Any]:
    width = rng.uniform(0.08, 0.35)
    height = rng.uniform(0.08, 0.35)
    return {
        "type": "bbox",
        "label": label,
        "coordinates": {
            "x": round(rng.uniform(0.0, 1.0 - width), 4),
            "y": round(rng.uniform(0.0, 1.0 - height), 4),
            "width": round(width, 4),
            "height": round(height, 4),
        },
    }


def _build_polygon(label: str, rng: random.Random) -> Dict[str, Any]:
    cx = rng.uniform(0.2, 0.8)
    cy = rng.uniform(0.2, 0.8)
    radius = rng.uniform(0.05, 0.18)
    sides = rng.randint(3, 6)
    points = []
    for i in range(sides):
        angle = 2 * 3.14159265 * i / sides
        points.append({
            "x": round(_clamp(cx + radius * _cos(angle)), 4),
            "y": round(_clamp(cy + radius * _sin(angle)), 4),
        })
    return {"type": "polygon", "label": label, "coordinates": points}


def _build_landmark(label: str, rng: random.Random) -> Dict[str, Any]:
    return {
        "type": "landmark",
        "label": label,
        "coordinates": {"x": round(rng.uniform(0.0, 1.0), 4),
                        "y": round(rng.uniform(0.0, 1.0), 4)},
    }


def _cos(x: float) -> float:
    import math
    return math.cos(x)


def _sin(x: float) -> float:
    import math
    return math.sin(x)


_BUILDERS = {
    "bbox": _build_bbox,
    "polygon": _build_polygon,
    "landmark": _build_landmark,
}


def noise_levels(accuracy: float) -> Dict[str, float]:
    """
    Map a competence profile's accuracy onto the four ways annotators differ.

    Kept as one function so a study can reason about what "an 0.8 annotator"
    means, and so the mapping is testable without running a simulation.
    """
    miss = _clamp(1.0 - accuracy)
    return {
        # A gentle boundary ramp on purpose. Jitter interacts with the 0.5 IoU
        # match threshold far more violently than it looks: because the error
        # applies independently to both annotators and IoU is unforgiving on
        # small objects, a coefficient of 0.09 here pushed detection F1 down to
        # 0.62 at accuracy 0.8 — i.e. a "good" annotator appearing to miss a
        # third of the objects they had in fact drawn. 0.04 puts an 0.8
        # annotator at ~8px of boundary error on a 640px image, which is what
        # that competence should actually look like.
        "jitter": MIN_JITTER + 0.04 * miss,
        "drop": 0.30 * miss,
        "mislabel": 0.40 * miss,
        "spurious": 0.25 * miss,
    }


def perturb_objects(
    objects: Sequence[Dict[str, Any]],
    labels: Sequence[str],
    accuracy: float,
    rng: Optional[random.Random] = None,
) -> List[Dict[str, Any]]:
    """
    Redraw a reference set the way an annotator of this competence would.

    Applies, independently: boundary jitter, dropped objects (a detection
    miss), mislabelled objects (a classification error), and spurious extra
    objects (a false positive).
    """
    rng = rng or random
    levels = noise_levels(accuracy)
    out: List[Dict[str, Any]] = []

    for obj in objects or []:
        if rng.random() < levels["drop"]:
            continue
        moved = jitter_object(obj, levels["jitter"], rng)
        if labels and rng.random() < levels["mislabel"]:
            alternatives = [l for l in labels if l != moved.get("label")]
            if alternatives:
                moved["label"] = rng.choice(alternatives)
        out.append(moved)

    if rng.random() < levels["spurious"]:
        out.extend(random_objects(labels, DEFAULT_TOOLS, rng, count_range=(1, 1)))

    return out


def jitter_object(obj: Dict[str, Any], amount: float,
                  rng: Optional[random.Random] = None) -> Dict[str, Any]:
    """Nudge one shape's boundary, preserving its type, label and contract shape."""
    rng = rng or random
    moved = dict(obj)
    coords = obj.get("coordinates")

    def shift(value):
        return round(_clamp(float(value) + rng.gauss(0.0, amount)), 4)

    if isinstance(coords, list):
        moved["coordinates"] = [
            {"x": shift(p.get("x", 0)), "y": shift(p.get("y", 0))}
            for p in coords if isinstance(p, dict)
        ]
    elif isinstance(coords, dict) and "width" in coords:
        width = float(coords.get("width", 0))
        height = float(coords.get("height", 0))
        new = {
            "x": shift(coords.get("x", 0)),
            "y": shift(coords.get("y", 0)),
            # Size drifts too, but half as much: annotators disagree about
            # where a box sits more than about how big the object is.
            "width": round(_clamp(width + rng.gauss(0.0, amount / 2), 0.01, 1.0), 4),
            "height": round(_clamp(height + rng.gauss(0.0, amount / 2), 0.01, 1.0), 4),
        }
        # Keep the box inside the image without shrinking it.
        new["x"] = round(_clamp(new["x"], 0.0, max(0.0, 1.0 - new["width"])), 4)
        new["y"] = round(_clamp(new["y"], 0.0, max(0.0, 1.0 - new["height"])), 4)
        moved["coordinates"] = new
    elif isinstance(coords, dict):
        moved["coordinates"] = {"x": shift(coords.get("x", 0)),
                                "y": shift(coords.get("y", 0))}

    return moved
