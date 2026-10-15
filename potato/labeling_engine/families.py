"""
What "the machine got it right" means, per kind of annotation.

The contracts are written once, against a family's ``correct(pred, human)``
and ``class_of(pred)``. A family turns two values of one annotation type into
a loss in [0, 1] and calls the prediction correct when the loss is at most the
contract's ``tolerance``:

========== ====================================================== ==========
family     loss                                                   tolerance
========== ====================================================== ==========
trace      share of commonly marked steps labeled differently     0
spatial    1 - mean 3D IoU over matched objects                   0.5
segments   1 - mean temporal IoU (temporal_grounding, tiered)     0.5
nominal    0 if the same label, else 1                            0
ordinal    |a - b| / (number of scale points - 1)                 0
continuous |a - b| / (max - min)                                  0.05
multilabel 1 - Jaccard overlap of the label sets                  0
geometry   1 - mean IoU over matched shapes, unmatched counting 0 0.5
           (``annotation_values.distance``, the IAA definition)
temporal   the same, over time segments                           0.5
========== ====================================================== ==========

Geometry and temporal reuse the agreement code the IAA report uses, so a
machine is judged against a person exactly as two people are judged against
each other. Types with no family here (free text, and the
pairwise and composite types) are reported as unsupported rather than
guessed at.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from potato.server_utils.annotation_values import (
    distance, geometry_objects, selected_labels, temporal_segments)

from .schemes import SchemeSpec, normalize_label

ALL = "*"


class Family:
    kind = ""
    default_tolerance = 0.0
    per_class_ok = True

    def __init__(self, scheme: SchemeSpec, tolerance: Optional[float] = None):
        self.scheme = scheme
        self.tolerance = self.default_tolerance if tolerance is None else float(tolerance)

    def human_value(self, stored: Any) -> Any:
        """A person's answer, from the user state's stored value for the scheme."""
        raise NotImplementedError

    def loss(self, pred: Any, human: Any) -> float:
        raise NotImplementedError

    def correct(self, pred: Any, human: Any) -> bool:
        if pred is None or human is None:
            return False
        return self.loss(pred, human) <= self.tolerance + 1e-12

    def coerce(self, value: Any) -> Tuple[Any, Optional[str]]:
        """A machine answer as a valid value for the scheme, or ``(None, why)``.

        The runner applies it to every source. An answer that is not a
        value the scheme can hold (a label not in the list, a stale class
        name in a precomputed column) is never accepted, whatever the
        contract says about the rest: the contract only sees it if a person
        happens to label that item."""
        return value, None

    def class_of(self, pred: Any) -> str:
        """The class a per-class contract groups this prediction under."""
        return ALL

    def to_page(self, value: Any) -> Any:
        """A machine answer in the shape the annotation page prefills for a
        verify request, or None when the page cannot show it (the request is
        then recorded blind: the person never saw the answer)."""
        return None

    def classes(self) -> List[str]:
        return [ALL]


class Nominal(Family):
    kind = "nominal"

    def human_value(self, stored):
        chosen = [x for x in selected_labels(stored) if x != "free_response"]
        if not chosen:
            return None
        return normalize_label(chosen[0], self.scheme.labels) or chosen[0]

    def loss(self, pred, human):
        return 0.0 if str(pred) == str(human) else 1.0

    def coerce(self, value):
        if not self.scheme.labels:
            return value, None
        label = normalize_label(value, self.scheme.labels)
        if label is None:
            return None, f"{value!r} is not one of {list(self.scheme.labels)}"
        return label, None

    def class_of(self, pred):
        return str(pred)

    def classes(self):
        return list(self.scheme.labels)

    def to_page(self, value):
        return value


class Ordinal(Nominal):
    kind = "ordinal"

    def loss(self, pred, human):
        labels = self.scheme.labels
        try:
            a, b = labels.index(str(pred)), labels.index(str(human))
        except ValueError:
            return 1.0
        return abs(a - b) / max(1, len(labels) - 1)


class Continuous(Family):
    kind = "continuous"
    default_tolerance = 0.05
    per_class_ok = False

    def _range(self):
        # Both spellings the number scheme honours (schemas/number.py):
        # reading only min_value/max_value scored a 0-1000 `number` on 0-100,
        # so 500 against 510 was a loss of 0.1, not 0.01.
        raw = self.scheme.raw
        lo = raw.get("min_value", raw.get("min", 0))
        hi = raw.get("max_value", raw.get("max", 100))
        try:
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError):
            lo, hi = 0.0, 100.0
        return lo, max(hi, lo + 1e-9)

    def human_value(self, stored):
        values = stored.values() if isinstance(stored, dict) else [stored]
        for v in values:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return None

    def loss(self, pred, human):
        lo, hi = self._range()
        try:
            return min(1.0, abs(float(pred) - float(human)) / (hi - lo))
        except (TypeError, ValueError):
            return 1.0

    def to_page(self, value):
        return value

    def coerce(self, value):
        if isinstance(value, bool):
            return None, f"{value!r} is not a number"
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, f"{value!r} is not a number"


class MultiLabel(Family):
    kind = "multilabel"
    per_class_ok = False

    def human_value(self, stored):
        chosen = [x for x in selected_labels(stored) if x != "free_response"]
        return sorted(chosen) if chosen else []

    def loss(self, pred, human):
        a, b = set(pred or []), set(human or [])
        if not a and not b:
            return 0.0
        return 1.0 - len(a & b) / len(a | b)

    def to_page(self, value):
        return list(value or [])

    def coerce(self, value):
        if not isinstance(value, (list, tuple, set)):
            return None, f"{value!r} is not a list of labels"
        if not self.scheme.labels:
            return sorted(str(v) for v in value), None
        out = []
        for v in value:
            label = normalize_label(v, self.scheme.labels)
            if label is None:
                return None, f"{v!r} is not one of {list(self.scheme.labels)}"
            out.append(label)
        return sorted(set(out)), None


class Geometry(Family):
    kind = "geometry"
    default_tolerance = 0.5
    per_class_ok = False

    def human_value(self, stored):
        objs = geometry_objects(self.scheme.raw, stored)
        return objs

    def loss(self, pred, human):
        d = distance(self.scheme.raw, pred or [], human or [])
        return 1.0 if d is None else float(d)

    def to_page(self, value):
        """Image regions as the canvas's client objects. Machine boxes are
        normalized [x, y, w, h], so a 1x1 "image" keeps them normalized.
        The page read the server shape ({"bbox": [...]}) as nothing, showed
        no box under "a model's answer is filled in", and Next stored []."""
        if self.scheme.annotation_type != "image_annotation":
            return None
        from potato.export.cv_utils import to_client_object
        # The label's own colour: an empty one drew the box as a solid black
        # rectangle over the image.
        colors = {(l.get("name") if isinstance(l, dict) else str(l)):
                  (l.get("color") if isinstance(l, dict) else None) or ""
                  for l in (self.scheme.raw.get("labels") or [])}
        out = []
        for obj in value or []:
            if not isinstance(obj, dict):
                continue
            label = str(obj.get("label") or "")
            o = to_client_object(obj.get("type") or "bbox", label, colors.get(label, ""),
                                 img_w=1.0, img_h=1.0, bbox=obj.get("bbox"),
                                 points=obj.get("points"), rle=obj.get("rle"),
                                 provenance={"source": "model"})
            if o:
                out.append(o)
        return out


class Temporal(Geometry):
    kind = "temporal"

    def to_page(self, value):
        return None

    def human_value(self, stored):
        return temporal_segments(self.scheme.raw, stored)


class Trace(Family):
    """Step-level judgments on an agent trace or chain of thought.

    A value is ``{step index: label}`` (a process reward of 1/-1/0, or a
    per-step verdict). The loss is the share of steps both sides marked on
    which they differ; a step only one side marked is not compared, and a pair
    with no step in common has loss 1 (nothing was agreed on).
    """
    kind = "trace"
    default_tolerance = 0.0
    per_class_ok = False

    @staticmethod
    def steps_of(value: Any) -> Dict[str, Any]:
        from potato.step_agreement import steps_from_stored
        return steps_from_stored(value)

    def human_value(self, stored):
        steps = self.steps_of(stored)
        return steps or None

    def loss(self, pred, human):
        a, b = self.steps_of(pred), self.steps_of(human)
        shared = set(a) & set(b)
        if not shared:
            return 1.0
        return sum(1 for k in shared if str(a[k]) != str(b[k])) / len(shared)


class Spatial(Geometry):
    """3D objects (cuboids, points, polylines), matched by 3D IoU."""
    kind = "spatial"

    def human_value(self, stored):
        from potato.server_utils.iaa.structured import spatial_objects
        return spatial_objects(stored)

    def loss(self, pred, human):
        from potato.server_utils.iaa.structured import spatial_distance
        return spatial_distance(pred, human)


class Segments(Temporal):
    """Time segments for temporal_grounding and tiered_annotation, read and
    matched as the agreement report does (``iaa/structured.py``)."""
    kind = "segments"

    def human_value(self, stored):
        from potato.server_utils.iaa.structured import segment_list
        return segment_list(stored)

    def loss(self, pred, human):
        from potato.server_utils.iaa.structured import segment_distance
        return segment_distance(pred, human)


#: The type lists live with the agreement measures, so the report and the
#: engine cannot disagree about which family a type belongs to.
from potato.server_utils.iaa.structured import (  # noqa: E402
    SEGMENT_TYPES, SPATIAL_TYPES, TRACE_TYPES)


class Unsupported(Family):
    kind = "unsupported"
    per_class_ok = False

    def human_value(self, stored):
        return None

    def loss(self, pred, human):
        return 1.0


def family_for(scheme: SchemeSpec, tolerance: Optional[float] = None) -> Family:
    from potato.server_utils.iaa.dispatcher import SchemaKind, classify_schema
    atype = scheme.annotation_type
    if atype in TRACE_TYPES:
        return Trace(scheme, tolerance)
    if atype in SPATIAL_TYPES:
        return Spatial(scheme, tolerance)
    if atype in SEGMENT_TYPES:
        return Segments(scheme, tolerance)
    kind = classify_schema(scheme.raw)
    cls = {
        SchemaKind.NOMINAL: Nominal,
        SchemaKind.ORDINAL: Ordinal,
        SchemaKind.CONTINUOUS: Continuous,
        SchemaKind.MULTILABEL: MultiLabel,
        SchemaKind.GEOMETRY: Geometry,
        SchemaKind.TEMPORAL: Temporal,
    }.get(kind, Unsupported)
    return cls(scheme, tolerance)
