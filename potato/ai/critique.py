"""
VLM-as-judge critique of image annotations.

This is the check that geometry agreement cannot perform. Krippendorff's alpha
over IoU (``server_utils/iaa/geometry.py``) answers "did the annotators draw the
same shape?" -- it is silent when two annotators confidently draw the same
*wrong* thing, and it needs more than one annotator to say anything at all. A
vision model looking at each region independently answers a different question:
"is what is inside this boundary actually a {label}, and does the boundary fit
it?" One annotator is enough, and systematic error is exactly what it catches.

The module is deliberately pure: no PIL, no network, no Flask, no config. It
computes crop windows, builds prompts, and parses verdicts. Rendering the crops
and calling the model live in :mod:`potato.ai.critique_service`, mirroring the
``typing_dynamics`` / ``typing_store`` split so the two judge subsystems stay
one thing to learn.

Two design points that are load-bearing, and neither is obvious:

**A crop tight to the annotation makes boundary quality unjudgeable.** Cropping
exactly to the stored bbox means the object fills the frame by construction, so
every boundary looks perfect and the model says "tight" every time. The crop
therefore carries context around the region (``DEFAULT_CONTEXT_RATIO``), and
the region's own outline is drawn into the crop by the service. Without the
drawn outline the model cannot see where the annotator's boundary *is*, and
answers about a boundary it is only imagining.

**A judge is not ground truth.** Every verdict carries a confidence, and one
below ``DEFAULT_MIN_CONFIDENCE`` is recorded as ``uncertain`` and kept out of
the review queue rather than presented as a finding. A queue padded with
coin-flips trains annotators to dismiss it, which costs more than the feature
returns. :func:`summarize` states this in a ``caveat`` that the UI shows.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------

#: What the model can say about the *content* of a region. Append-only: these
#: strings are stored in verdict records and read by the client.
CRITIQUE_VERDICTS = (
    "confirmed",      # contains the labelled thing, boundary acceptable
    "wrong_label",    # contains something, but not this label
    "not_an_object",  # contains no discernible object of any labelled class
    "loose_boundary", # right thing, boundary too loose / clipped
    "uncertain",      # the model could not tell, or said so with low confidence
)

#: What the model can say about the *boundary*, independent of the label.
BOUNDARY_VERDICTS = ("tight", "loose", "clipped", "unknown")

#: Verdicts worth an annotator's attention. ``uncertain`` is deliberately
#: absent -- see the module docstring.
FLAGGING_VERDICTS = frozenset({"wrong_label", "not_an_object", "loose_boundary"})

#: How much context to include around the region, as a fraction of the larger
#: bbox side. 0.6 keeps the region dominant while leaving enough surroundings
#: for "does the box clip the object?" to have an answer.
DEFAULT_CONTEXT_RATIO = 0.6

#: Floor on crop size in source pixels. A 12x9 keypoint region upscaled from a
#: 12x9 crop is unreadable; widening the window first preserves real detail.
DEFAULT_MIN_CROP_PX = 96

#: Verdicts below this confidence become ``uncertain``.
DEFAULT_MIN_CONFIDENCE = 0.5

#: Default cap on regions critiqued in one pass. Each region is a separate
#: model call, so an image with 400 boxes would otherwise mean 400 round trips.
DEFAULT_MAX_REGIONS = 24


class CritiqueError(Exception):
    """Raised when a critique cannot be attempted at all."""


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

@dataclass
class CritiqueRegion:
    """One annotation, resolved to absolute pixels and ready to crop.

    ``index`` is the position in the stored object list, and is how a verdict
    is matched back to the annotation the annotator can see. It is NOT an id:
    deleting an annotation renumbers everything after it, which is why the
    client re-runs a critique rather than reusing verdicts after an edit.
    """

    index: int
    label: str
    type: str
    bbox: Tuple[float, float, float, float]  # x, y, w, h in absolute px
    area: float = 0.0
    instance: Optional[int] = None
    points: Optional[List[List[float]]] = None  # absolute px, for polygon-ish
    rle: Optional[dict] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "type": self.type,
            "bbox": list(self.bbox),
            "area": self.area,
            "instance": self.instance,
        }


@dataclass
class CropWindow:
    """A padded, clamped crop rectangle in absolute source pixels."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return max(0, self.x1 - self.x0)

    @property
    def height(self) -> int:
        return max(0, self.y1 - self.y0)

    def shift(self, points: Sequence[Sequence[float]]) -> List[List[float]]:
        """Translate absolute source points into crop-local coordinates."""
        return [[float(p[0]) - self.x0, float(p[1]) - self.y0] for p in points]

    def shift_bbox(self, bbox: Sequence[float]) -> List[float]:
        """Translate an absolute [x, y, w, h] into crop-local coordinates."""
        return [float(bbox[0]) - self.x0, float(bbox[1]) - self.y0,
                float(bbox[2]), float(bbox[3])]

    def to_dict(self) -> Dict[str, int]:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}


@dataclass
class CritiqueVerdict:
    """The model's judgement of one region, after confidence gating."""

    index: int
    label: str
    verdict: str = "uncertain"
    boundary: str = "unknown"
    suggested_label: str = ""
    confidence: float = 0.0
    rationale: str = ""
    flagged: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "verdict": self.verdict,
            "boundary": self.boundary,
            "suggested_label": self.suggested_label,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "flagged": self.flagged,
            "error": self.error,
        }


@dataclass
class MissedObject:
    """Something the model believes the annotator did not annotate.

    ``bbox`` is normalized (0-1) and approximate -- vision-language models are
    poor localizers, which is why this is rendered as a hint to look at a part
    of the image rather than as an acceptable annotation. Accepting it would
    put a coordinate the model guessed into the dataset.
    """

    label: str
    bbox: Optional[Tuple[float, float, float, float]] = None
    confidence: float = 0.0
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "bbox": list(self.bbox) if self.bbox else None,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


@dataclass
class CritiqueSummary:
    """Roll-up of one critique pass over one image."""

    reviewed: int = 0
    confirmed: int = 0
    flagged: int = 0
    uncertain: int = 0
    errors: int = 0
    missed: int = 0
    skipped: int = 0
    by_verdict: Dict[str, int] = field(default_factory=dict)
    caveat: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewed": self.reviewed,
            "confirmed": self.confirmed,
            "flagged": self.flagged,
            "uncertain": self.uncertain,
            "errors": self.errors,
            "missed": self.missed,
            "skipped": self.skipped,
            "by_verdict": dict(self.by_verdict),
            "caveat": self.caveat,
        }


# --------------------------------------------------------------------------
# Regions and crops
# --------------------------------------------------------------------------

def regions_from_objects(objects: Sequence[Any], img_w: float,
                         img_h: float) -> List[CritiqueRegion]:
    """Resolve stored annotation objects into croppable regions.

    Goes through ``cv_utils.normalize_annotation_object`` rather than reading
    ``coordinates`` directly, so every geometry type the platform supports --
    box, polygon, polyline, mask, ellipse, keypoint set, cuboid -- yields a
    bbox by the same rule the exporters use. A type added to the contract is
    critiqueable with no change here.

    Objects that normalize to nothing (malformed, or a type with no extent) are
    skipped, and their absence is reported as ``skipped`` by :func:`summarize`
    rather than silently dropped.
    """
    from potato.export.cv_utils import normalize_annotation_object

    regions: List[CritiqueRegion] = []
    for index, obj in enumerate(objects):
        try:
            canonical = normalize_annotation_object(obj, img_w, img_h)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Region %d did not normalize: %s", index, exc)
            continue
        if not canonical:
            continue
        bbox = canonical.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        w, h = float(bbox[2]), float(bbox[3])
        # A zero-extent region has no pixels to show the model. Points and
        # keypoints legitimately have zero area but a non-zero bbox; a bbox
        # with no size at all is degenerate input.
        if w <= 0 and h <= 0:
            continue
        regions.append(CritiqueRegion(
            index=index,
            label=str(canonical.get("label") or ""),
            type=str(canonical.get("type") or ""),
            bbox=(float(bbox[0]), float(bbox[1]), w, h),
            area=float(canonical.get("area") or 0.0),
            instance=canonical.get("instance"),
            points=canonical.get("points"),
            rle=canonical.get("rle"),
        ))
    return regions


def _fit_axis(low: float, high: float, extent: int,
              min_px: int) -> Tuple[int, int]:
    """Widen one axis to ``min_px`` and slide it inside ``[0, extent]``.

    Growing symmetrically and then clamping is not enough: a region against the
    left edge grows to -43..53 and clamps back to 0..53, so the crop that most
    needed widening is the one that stays small. Sliding the window after
    growing recovers the width on whichever side has room.
    """
    lo, hi = float(low), float(high)
    want = float(min(min_px, extent)) if extent > 0 else float(min_px)

    grow = (want - (hi - lo)) / 2.0
    if grow > 0:
        lo -= grow
        hi += grow

    if lo < 0:
        hi -= lo
        lo = 0.0
    if extent > 0 and hi > extent:
        lo -= (hi - extent)
        hi = float(extent)
    lo = max(0.0, lo)

    return int(math.floor(lo)), int(math.ceil(hi))


def crop_window(bbox: Sequence[float], img_w: int, img_h: int,
                context_ratio: float = DEFAULT_CONTEXT_RATIO,
                min_px: int = DEFAULT_MIN_CROP_PX) -> CropWindow:
    """Compute a padded crop around ``bbox``, clamped to the image.

    Padding is proportional to the *larger* side rather than each side
    separately, so a long thin bar keeps its aspect ratio recognisable instead
    of being padded into a square of mostly background.
    """
    x, y, w, h = (float(v) for v in bbox[:4])
    pad = max(float(w), float(h)) * max(0.0, float(context_ratio))

    x0 = x - pad
    y0 = y - pad
    x1 = x + w + pad
    y1 = y + h + pad

    x0, x1 = _fit_axis(x0, x1, int(img_w), min_px)
    y0, y1 = _fit_axis(y0, y1, int(img_h), min_px)

    # Clamping can collapse the window on a degenerate image; never return an
    # empty crop, since PIL raises on it and the caller would see a stack trace
    # instead of a verdict.
    if x1 <= x0:
        x0, x1 = 0, max(1, int(img_w))
    if y1 <= y0:
        y0, y1 = 0, max(1, int(img_h))
    return CropWindow(x0, y0, x1, y1)


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

_REGION_TEMPLATE = """You are reviewing one region of an image that a human annotator has labelled.

The region the annotator marked is outlined in {outline_colour} in this crop. \
Surrounding context is included so you can judge whether the outline fits the object.

The annotator labelled it: "{label}"
Allowed labels for this task: {labels}
{description}
Answer these questions about the OUTLINED region only:
1. Does the outlined region contain a "{label}"?
2. If not, which of the allowed labels does it contain (or none)?
3. Does the outline fit the object tightly, is it too loose (much larger than \
the object), or does it clip the object (cutting part of it off)?

Reply with ONLY a JSON object:
{{"verdict": "confirmed" | "wrong_label" | "not_an_object" | "loose_boundary" | "uncertain",
 "suggested_label": "<one of the allowed labels, or empty>",
 "boundary": "tight" | "loose" | "clipped",
 "confidence": <number between 0 and 1>,
 "rationale": "<one short sentence>"}}

Use "uncertain" and a low confidence when the crop is too small, blurred or \
ambiguous to judge. Being unsure is a useful answer; guessing is not."""


_MISSED_TEMPLATE = """You are reviewing a human annotator's work on this image.

Labels for this task: {labels}
{description}
The annotator has already marked {count} region(s): {existing}

Identify objects belonging to the allowed labels that appear in the image but \
that the annotator appears to have MISSED. Do not repeat regions already listed \
above. If nothing was missed, return an empty list -- that is the expected \
answer for careful work.

Reply with ONLY a JSON object:
{{"missed": [{{"label": "<one of the allowed labels>",
             "bbox": {{"x": <0-1>, "y": <0-1>, "width": <0-1>, "height": <0-1>}},
             "confidence": <number between 0 and 1>,
             "rationale": "<one short sentence>"}}]}}

Coordinates are normalized to the image, with x,y at the top-left of the box. \
Only report objects you are confident about."""


def build_region_prompt(region: CritiqueRegion, labels: Sequence[str],
                        description: str = "",
                        outline_colour: str = "bright red") -> str:
    """Build the per-region critique prompt.

    ``outline_colour`` must match what the service actually draws, or the
    prompt directs the model at a colour that is not in the image.
    """
    label_list = ", ".join(str(l) for l in labels) if labels else "any object"
    desc = f"Task description: {description}\n" if description else ""
    return _REGION_TEMPLATE.format(
        outline_colour=outline_colour,
        label=region.label or "(unlabelled)",
        labels=label_list,
        description=desc,
    )


def build_missed_prompt(regions: Sequence[CritiqueRegion],
                        labels: Sequence[str],
                        description: str = "") -> str:
    """Build the whole-image "what did they miss?" prompt."""
    label_list = ", ".join(str(l) for l in labels) if labels else "any object"
    desc = f"Task description: {description}\n" if description else ""
    if regions:
        existing = "; ".join(
            f'{r.label or "unlabelled"} at '
            f'x={r.bbox[0]:.0f},y={r.bbox[1]:.0f},w={r.bbox[2]:.0f},h={r.bbox[3]:.0f}'
            for r in regions
        )
    else:
        existing = "none"
    return _MISSED_TEMPLATE.format(
        labels=label_list,
        description=desc,
        count=len(regions),
        existing=existing,
    )


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def coerce_payload(raw: Any) -> Dict[str, Any]:
    """Normalize whatever an endpoint returned into a dict.

    Open models routinely wrap JSON in ``` fences or prefix it with prose, and
    endpoints differ in whether they hand back a dict, a pydantic model or a
    string. Returning ``{}`` on failure keeps a malformed response a single
    ``uncertain`` verdict instead of an exception that loses the whole pass.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:  # noqa: BLE001
            return {}
    if not isinstance(raw, str):
        return {}

    text = raw.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        pass

    # Salvage the first balanced {...} block. A plain "find last brace" scan
    # fails on the fenced-JSON-plus-commentary shape open models emit, where
    # trailing prose can contain braces of its own.
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start:i + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    return {}
    return {}


def _confidence(value: Any) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    if conf != conf or conf in (float("inf"), float("-inf")):  # NaN / inf
        return 0.0
    # Models sometimes answer on a 0-100 scale despite the instruction.
    if conf > 1.0:
        conf = conf / 100.0 if conf <= 100.0 else 1.0
    return max(0.0, min(1.0, conf))


def parse_region_verdict(raw: Any, region: CritiqueRegion,
                         valid_labels: Sequence[str],
                         min_confidence: float = DEFAULT_MIN_CONFIDENCE
                         ) -> CritiqueVerdict:
    """Turn a model response into a gated :class:`CritiqueVerdict`."""
    payload = coerce_payload(raw)
    verdict = CritiqueVerdict(index=region.index, label=region.label)

    if not payload:
        verdict.verdict = "uncertain"
        verdict.rationale = "The model did not return a readable verdict."
        return verdict

    said = str(payload.get("verdict") or "").strip().lower().replace(" ", "_")
    if said not in CRITIQUE_VERDICTS:
        # An unrecognised verdict string is not a disagreement -- it is an
        # unparsed answer, and flagging on it would invent findings.
        said = "uncertain"

    boundary = str(payload.get("boundary") or "").strip().lower()
    if boundary not in BOUNDARY_VERDICTS:
        boundary = "unknown"

    verdict.boundary = boundary
    verdict.confidence = _confidence(payload.get("confidence"))
    verdict.rationale = str(payload.get("rationale") or "").strip()

    suggested = str(payload.get("suggested_label") or "").strip()
    if suggested:
        from potato.ai.judge import _fuzzy_match_label
        # Same matcher the LLM judge uses, so a model label is resolved
        # identically whichever subsystem reports it.
        matched = _fuzzy_match_label(suggested, list(valid_labels))
        verdict.suggested_label = matched or ""
        if said == "wrong_label" and not matched:
            # It disagrees, but names something outside the task's vocabulary.
            # That is not actionable: the annotator cannot apply a label the
            # schema does not have.
            said = "uncertain"
            if not verdict.rationale:
                verdict.rationale = (
                    f"The model suggested '{suggested}', which is not a "
                    f"label in this task.")

    # A "confirmed" content verdict paired with a bad boundary is a boundary
    # finding: the model answered both questions and only one is a problem.
    if said == "confirmed" and boundary in ("loose", "clipped"):
        said = "loose_boundary"

    # A wrong_label verdict that agrees with the existing label is a model
    # contradiction; trust the label it named, not the verdict word.
    if said == "wrong_label" and verdict.suggested_label == region.label:
        said = "confirmed" if boundary not in ("loose", "clipped") else "loose_boundary"

    if said in FLAGGING_VERDICTS and verdict.confidence < min_confidence:
        said = "uncertain"

    verdict.verdict = said
    verdict.flagged = said in FLAGGING_VERDICTS
    return verdict


def parse_missed(raw: Any, valid_labels: Sequence[str],
                 min_confidence: float = DEFAULT_MIN_CONFIDENCE
                 ) -> List[MissedObject]:
    """Parse the whole-image "missed objects" response.

    Entries naming a label outside the schema are dropped rather than kept with
    a foreign label -- the annotator has no way to act on them, and they would
    make a careful pass look sloppy.
    """
    from potato.ai.judge import _fuzzy_match_label

    payload = coerce_payload(raw)
    items = payload.get("missed")
    if not isinstance(items, list):
        return []

    out: List[MissedObject] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        label = _fuzzy_match_label(str(entry.get("label") or ""),
                                   list(valid_labels))
        if not label:
            continue
        confidence = _confidence(entry.get("confidence"))
        if confidence < min_confidence:
            continue
        bbox = None
        raw_box = entry.get("bbox")
        if isinstance(raw_box, dict):
            try:
                bbox = (
                    max(0.0, min(1.0, float(raw_box.get("x", 0)))),
                    max(0.0, min(1.0, float(raw_box.get("y", 0)))),
                    max(0.0, min(1.0, float(raw_box.get("width", 0)))),
                    max(0.0, min(1.0, float(raw_box.get("height", 0)))),
                )
            except (TypeError, ValueError):
                bbox = None
        out.append(MissedObject(
            label=label,
            bbox=bbox,
            confidence=confidence,
            rationale=str(entry.get("rationale") or "").strip(),
        ))
    return out


#: How much of a reported "missed" object must lie inside an existing
#: annotation before it is treated as already covered.
DEFAULT_COVERAGE_RATIO = 0.5


def suppress_covered(missed: Sequence[MissedObject],
                     regions: Sequence[CritiqueRegion],
                     img_w: float, img_h: float,
                     coverage_ratio: float = DEFAULT_COVERAGE_RATIO
                     ) -> List[MissedObject]:
    """Drop "missed" objects that sit inside an annotation that already exists.

    Found by running the pass on real output: an annotator who boxed a triangle
    but called it a circle got told twice -- once as ``wrong_label`` on that
    region, and again as a missed triangle in the same place. Both come from the
    same mistake, and showing it twice makes a three-region image look like it
    has four problems.

    The test is **containment, not IoU**, and that took a second live run to get
    right. A deliberately oversized box plainly contained a car, but its IoU
    with the car was 0.12 -- low precisely *because* the box was three times too
    big -- so the model's "you missed this car" survived, about a car that was
    annotated. IoU asks "are these the same object?"; the question here is "is
    this already inside something I drew?", which is asymmetric.

    Overlap alone decides, deliberately, without comparing labels: a region the
    annotator has already drawn is not missed, whatever either party calls it.
    The label disagreement is the per-region verdict's job to report.

    A missed object much LARGER than an existing region is still kept -- "there
    is a whole bus here" when you annotated one wheel is a real finding, and
    containment correctly scores it low.
    """
    if not missed or not regions:
        return list(missed)

    from potato.server_utils.iaa.geometry import containment_bbox

    kept: List[MissedObject] = []
    for candidate in missed:
        if candidate.bbox is None:
            # No location to compare. Keep it: "there is an unannotated car
            # somewhere in this image" is still worth a look.
            kept.append(candidate)
            continue
        absolute = [candidate.bbox[0] * img_w, candidate.bbox[1] * img_h,
                    candidate.bbox[2] * img_w, candidate.bbox[3] * img_h]
        if any(containment_bbox(absolute, list(r.bbox)) >= coverage_ratio
               for r in regions):
            continue
        kept.append(candidate)
    return kept


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

CAVEAT = (
    "These are a vision model's opinions, not ground truth. It is useful for "
    "catching systematic mistakes a second annotator would also miss, and it "
    "is wrong often enough that a flag is a prompt to look again, never a "
    "reason to change an annotation you can see is correct."
)


def summarize(verdicts: Sequence[CritiqueVerdict],
              missed: Sequence[MissedObject] = (),
              skipped: int = 0) -> CritiqueSummary:
    """Roll a critique pass up for the review queue header and the admin view."""
    summary = CritiqueSummary(reviewed=len(verdicts), missed=len(missed),
                              skipped=skipped, caveat=CAVEAT)
    for v in verdicts:
        summary.by_verdict[v.verdict] = summary.by_verdict.get(v.verdict, 0) + 1
        if v.error:
            summary.errors += 1
        elif v.flagged:
            summary.flagged += 1
        elif v.verdict == "uncertain":
            summary.uncertain += 1
        elif v.verdict == "confirmed":
            summary.confirmed += 1
    return summary
