"""
Annotation telemetry: how a drawn annotation was produced, not what it contains.

This is the geometry analogue of :mod:`potato.typing_dynamics`. Where that module
records the writing process behind a free-text answer, this one records the
*drawing* process behind a box, polygon or mask: when each shape was committed,
how many vertices it took, whether the annotator zoomed in before deciding, how
often they revised, and — the signal with the sharpest teeth — how quickly they
accepted an AI suggestion.

Deliberately pure: no Flask, no I/O, no database. ``summarize()`` is testable
against hand-built synthetic traces, and a feature added later can be recomputed
from stored streams rather than requiring re-collection. Storage lives in
:mod:`potato.annotation_telemetry_store`.

Content-blind by construction
-----------------------------
An event records *that* a shape was committed, *when*, of what geometry kind, and
one integer of context. It never records coordinates, so a stream cannot be used
to reconstruct the annotation. That matters because telemetry is collected from
every annotator including ones who did not consent to having their *work*
inspected in this form — and because a stream that cannot leak the answer is one
nobody has to argue about.

What the signals are for
------------------------
The literature on annotation quality is thinner than the writing-process
literature, so the claims here are correspondingly narrower.

- **AI-accept latency** is the strongest of them. Automation bias — accepting a
  system's suggestion without independent evaluation — is well established
  (Skitka, Mosier & Burdick, 1999, *Int. J. Human-Computer Studies* 51(5),
  doi:10.1006/ijhc.1999.0252; Parasuraman & Manzey, 2010, *Human Factors* 52(3),
  doi:10.1177/0018720810376055). A human cannot inspect a mask boundary and
  decide in 300ms; a *median* under that across many items is not fast expertise,
  it is not looking.
- **Time-on-task and revision counts** separate careful from careless annotation
  only *relative to a population*, not against a universal constant. This is the
  same finding as Conijn, Roeser & van Zaanen (2019) for keystrokes
  (doi:10.1007/s11145-019-09953-8): thresholds cannot be transplanted between
  tasks. Everything here is therefore calibrated against the project's own
  distribution, and the built-in defaults are documented as starting points.
- **Zoom behaviour** is a proxy for inspection, and a weak one on its own: a
  project whose objects fill the frame needs no zoom at all. It is reported
  because it is diagnostic *in combination* — never zooming while also accepting
  every suggestion instantly is a different story from either alone.

What this is not
----------------
It is not a verdict on an annotator. Every flag here is a screening signal whose
correct use is to decide *what to look at*, and the docs say so in those words.
Treating ``rubber_stamping`` as proof of misconduct would be a misuse of a
measure that cannot distinguish an inattentive annotator from a genuinely
excellent detector whose suggestions deserve to be accepted.
"""

from __future__ import annotations

import base64
import json
import math
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Bumped when the packed layout changes incompatibly. Stored inside every blob.
PACK_VERSION = 1

# --------------------------------------------------------------------------
# Vocabularies
#
# Both are append-only. Codes are persisted inside packed event blobs, so
# reordering or reusing a code would silently reinterpret stored data.
# --------------------------------------------------------------------------

#: What the annotator did. "unknown" is index 0 so an unrecognised action from a
#: newer client degrades to a visible placeholder rather than being dropped.
ACTIONS: List[str] = [
    "unknown",
    "shape_add",     # a shape was committed to the canvas
    "shape_edit",    # an existing shape was moved, resized or reshaped
    "shape_remove",
    "vertex",        # one polygon/polyline/keypoint vertex placed
    "stroke",        # one brush or eraser stroke completed
    "fill",          # flood fill applied
    "tool",          # tool switch
    "zoom",
    "pan",
    "undo",
    "redo",
    "ai_suggest",    # a suggestion was rendered to the annotator
    "ai_accept",
    "ai_reject",
    "focus",
    "blur",
]

#: Geometry kinds, matching the client coordinate contract in
#: ``potato/export/cv_utils.py``. Kept as its own vocabulary rather than reusing
#: VALID_TOOLS because a tool and a geometry kind are not the same thing (the
#: brush and eraser tools both produce a mask).
SHAPE_KINDS: List[str] = [
    "unknown",
    "bbox",
    "polygon",
    "polyline",
    "mask",
    "landmark",
    "keypoint_set",
    "ellipse",
    "cuboid_2d",
    "freeform",
    "tubelet",
]

_ACTION_CODE = {name: i for i, name in enumerate(ACTIONS)}
_SHAPE_CODE = {name: i for i, name in enumerate(SHAPE_KINDS)}

#: Actions that commit or change annotation content, as distinct from
#: navigating the viewport.
PRODUCTIVE_ACTIONS = frozenset({
    "shape_add", "shape_edit", "shape_remove", "stroke", "fill",
    "ai_accept",
})

#: Actions that record no work and no inspection — only that the interface
#: exists. Arming a tool is one: the manager selects a default tool when it is
#: constructed and clears it on teardown, so *every page view* emits one of
#: these whether or not the annotator did anything.
BOOKKEEPING_ACTIONS = frozenset({"tool", "focus", "blur", "unknown"})


def has_substance(events: Sequence[TelemetryEvent]) -> bool:
    """Whether a stream is worth storing at all.

    A session whose every event is bookkeeping is a page view, not work, and
    storing it is not merely untidy: session count is the denominator of the
    admin risk score, so a row per page view dilutes every flag rate toward
    zero. Measured live — four page views produced four sessions containing one
    ``tool`` event each.

    Zoom and pan *do* count. "Spent two minutes examining this image and drew
    nothing" is a real observation about the work; "the page loaded" is not.
    """
    return any(e.action not in BOOKKEEPING_ACTIONS for e in events)

#: Gap above which the annotator is treated as idle rather than working. Two
#: minutes rather than a tighter bound because inspecting a hard image is real
#: work that produces no events at all.
DEFAULT_IDLE_MS = 120_000

#: Zoom above which the annotator is treated as inspecting rather than viewing.
#: Slightly above 1.0 so a fit-to-window that lands at 1.02 does not read as
#: deliberate magnification.
ZOOM_INSPECT_THRESHOLD = 1.05

#: A shape committed within this window of an ``ai_accept`` *is* that accept's
#: shape — the client commits an accepted suggestion through the same path as a
#: hand-drawn one, so it arrives as a ``shape_add`` milliseconds later.
#:
#: This matters because the two must not be measured the same way. An annotator
#: who reviews eight good suggestions for four seconds each, then accepts them,
#: produces eight shapes in rapid succession — and a pace measure that counted
#: them would report "hasty" about the one annotator whose accept latency
#: proves they were careful. Caught by running the exporter on a two-annotator
#: fixture and noticing the careful one was flagged too.
ACCEPT_SHAPE_WINDOW_MS = 500


# --------------------------------------------------------------------------
# Event model
# --------------------------------------------------------------------------


@dataclass
class TelemetryEvent:
    """One recorded interaction.

    Attributes:
        t_ms: milliseconds since the session started. Relative rather than
            absolute so a stream carries no wall-clock information about the
            annotator beyond the session's own duration.
        action: one of :data:`ACTIONS`.
        shape: one of :data:`SHAPE_KINDS`; ``"unknown"`` when not applicable.
        value: one integer of context whose meaning depends on ``action``:

            ============  ===============================================
            ``shape_add``  vertices in the committed geometry (4 for a
                           bbox, ``len(points)`` for a polygon, 0 for a
                           mask, which has no vertices)
            ``stroke``     stroke length in image pixels
            ``zoom``       zoom level × 100, so 250 means 2.5×
            ``pan``        pan distance in screen pixels
            ``vertex``     the vertex's ordinal within its shape
            others         0
            ============  ===============================================

        meta: sparse extras. ``{"sid": ...}`` pairs an ``ai_accept`` or
            ``ai_reject`` with the ``ai_suggest`` that produced it;
            ``{"tool": ...}`` names the tool on a switch.
    """

    t_ms: int
    action: str
    shape: str = "unknown"
    value: int = 0
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "t_ms": self.t_ms,
            "action": self.action,
            "shape": self.shape,
            "value": self.value,
        }
        if self.meta:
            out["meta"] = self.meta
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TelemetryEvent":
        action = str(data.get("action") or "unknown")
        shape = str(data.get("shape") or "unknown")
        # An unrecognised name from a newer client becomes "unknown" rather than
        # raising: losing one event's specificity is better than rejecting a
        # whole session, and the count of unknowns is itself reported.
        return cls(
            t_ms=int(data.get("t_ms") or 0),
            action=action if action in _ACTION_CODE else "unknown",
            shape=shape if shape in _SHAPE_CODE else "unknown",
            value=int(data.get("value") or 0),
            meta=data.get("meta") if isinstance(data.get("meta"), dict) else None,
        )


def pack_events(events: Sequence[TelemetryEvent]) -> bytes:
    """Pack a session's events into a compact zlib-compressed blob.

    Timestamps are delta-encoded against the previous event. Unlike keystroke
    streams these are sparse — a few hundred events for a whole image rather
    than thousands for one paragraph — so the packing is about keeping the
    column uniform with the typing store rather than about volume.
    """
    if not events:
        return b""

    times: List[int] = []
    actions: List[int] = []
    shapes: List[int] = []
    values: List[int] = []
    metas: List[List[Any]] = []

    prev_t = 0
    for i, e in enumerate(events):
        times.append(e.t_ms - prev_t)
        prev_t = e.t_ms
        actions.append(_ACTION_CODE.get(e.action, 0))
        shapes.append(_SHAPE_CODE.get(e.shape, 0))
        values.append(int(e.value))
        if e.meta:
            metas.append([i, e.meta])

    payload = {
        "v": PACK_VERSION,
        "n": len(events),
        "t": times,
        "a": actions,
        "s": shapes,
        "val": values,
        "m": metas,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return zlib.compress(raw, 6)


def unpack_events(blob: Optional[bytes]) -> List[TelemetryEvent]:
    """Reverse :func:`pack_events`. Returns ``[]`` for empty or absent blobs."""
    if not blob:
        return []

    payload = json.loads(zlib.decompress(blob).decode("utf-8"))
    version = payload.get("v")
    if version != PACK_VERSION:
        raise ValueError(
            f"Unsupported telemetry pack version {version!r} "
            f"(this build reads version {PACK_VERSION})"
        )

    n = payload.get("n", 0)
    times = payload.get("t", [])
    actions = payload.get("a", [])
    shapes = payload.get("s", [])
    values = payload.get("val", [])
    metas = {int(i): m for i, m in payload.get("m", [])}

    out: List[TelemetryEvent] = []
    t = 0
    for i in range(n):
        t += times[i]
        out.append(TelemetryEvent(
            t_ms=t,
            action=ACTIONS[actions[i]] if actions[i] < len(ACTIONS) else "unknown",
            shape=SHAPE_KINDS[shapes[i]] if shapes[i] < len(SHAPE_KINDS) else "unknown",
            value=values[i],
            meta=metas.get(i),
        ))
    return out


def pack_events_b64(events: Sequence[TelemetryEvent]) -> str:
    """Base64 form of :func:`pack_events`, for JSON transport and text columns."""
    return base64.b64encode(pack_events(events)).decode("ascii")


def unpack_events_b64(data: Optional[str]) -> List[TelemetryEvent]:
    """Reverse :func:`pack_events_b64`."""
    if not data:
        return []
    return unpack_events(base64.b64decode(data))


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------


@dataclass
class TelemetrySummary:
    """Derived features for one drawing session on one instance and schema."""

    schema_name: str = ""
    instance_id: str = ""

    # -- volume --
    events: int = 0
    unknown_events: int = 0
    shapes_added: int = 0
    #: Of those, the ones that arrived by accepting a suggestion rather than by
    #: being drawn. Pace is measured over the remainder.
    shapes_from_ai: int = 0
    shapes_drawn: int = 0
    shapes_edited: int = 0
    shapes_removed: int = 0
    strokes: int = 0
    fills: int = 0
    vertices_total: int = 0
    vertices_median: float = 0.0
    stroke_px_total: int = 0

    # -- timing --
    duration_ms: int = 0
    active_ms: int = 0
    idle_ms: int = 0
    time_to_first_shape_ms: Optional[int] = None
    shape_interval_median_ms: Optional[float] = None
    shape_interval_min_ms: Optional[int] = None

    # -- viewport --
    zoom_events: int = 0
    pan_events: int = 0
    max_zoom: float = 1.0
    zoomed_ms: int = 0
    zoomed_fraction: float = 0.0

    # -- revision --
    undo_count: int = 0
    redo_count: int = 0
    tool_switches: int = 0
    revision_ratio: float = 0.0

    # -- AI assistance --
    ai_suggested: int = 0
    ai_accepted: int = 0
    ai_rejected: int = 0
    ai_accept_latency_median_ms: Optional[float] = None
    ai_accept_latency_min_ms: Optional[int] = None
    ai_accepted_then_edited: int = 0
    ai_accept_rate: float = 0.0

    #: Per-geometry-kind commit counts, e.g. ``{"bbox": 3, "mask": 1}``.
    shape_kinds: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "instance_id": self.instance_id,
            "events": self.events,
            "unknown_events": self.unknown_events,
            "shapes_added": self.shapes_added,
            "shapes_from_ai": self.shapes_from_ai,
            "shapes_drawn": self.shapes_drawn,
            "shapes_edited": self.shapes_edited,
            "shapes_removed": self.shapes_removed,
            "strokes": self.strokes,
            "fills": self.fills,
            "vertices_total": self.vertices_total,
            "vertices_median": self.vertices_median,
            "stroke_px_total": self.stroke_px_total,
            "duration_ms": self.duration_ms,
            "active_ms": self.active_ms,
            "idle_ms": self.idle_ms,
            "time_to_first_shape_ms": self.time_to_first_shape_ms,
            "shape_interval_median_ms": self.shape_interval_median_ms,
            "shape_interval_min_ms": self.shape_interval_min_ms,
            "zoom_events": self.zoom_events,
            "pan_events": self.pan_events,
            "max_zoom": self.max_zoom,
            "zoomed_ms": self.zoomed_ms,
            "zoomed_fraction": self.zoomed_fraction,
            "undo_count": self.undo_count,
            "redo_count": self.redo_count,
            "tool_switches": self.tool_switches,
            "revision_ratio": self.revision_ratio,
            "ai_suggested": self.ai_suggested,
            "ai_accepted": self.ai_accepted,
            "ai_rejected": self.ai_rejected,
            "ai_accept_latency_median_ms": self.ai_accept_latency_median_ms,
            "ai_accept_latency_min_ms": self.ai_accept_latency_min_ms,
            "ai_accepted_then_edited": self.ai_accepted_then_edited,
            "ai_accept_rate": self.ai_accept_rate,
            "shape_kinds": dict(self.shape_kinds),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TelemetrySummary":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


def summarize(
    events: Sequence[TelemetryEvent],
    *,
    schema_name: str = "",
    instance_id: str = "",
    idle_ms: int = DEFAULT_IDLE_MS,
) -> TelemetrySummary:
    """Derive features from one session's event stream.

    Args:
        events: the stream, in any order — sorted here, because a client that
            batches from several buffers can legitimately deliver them
            interleaved, and every timing feature below would be nonsense on an
            unsorted stream.
        idle_ms: gap above which time is charged to ``idle_ms`` rather than
            ``active_ms``.
    """
    summary = TelemetrySummary(schema_name=schema_name, instance_id=instance_id)
    if not events:
        return summary

    ordered = sorted(events, key=lambda e: e.t_ms)
    summary.events = len(ordered)
    summary.duration_ms = max(0, ordered[-1].t_ms - ordered[0].t_ms)

    vertex_counts: List[int] = []
    #: Commit times of HAND-DRAWN shapes only; see ACCEPT_SHAPE_WINDOW_MS.
    shape_times: List[int] = []
    last_accept_at: Optional[int] = None
    # Suggestion id -> the time it was rendered. Pairing happens here rather
    # than on the client so the latency cannot be forged by a modified client
    # and so it can be recomputed if the definition changes.
    suggested_at: Dict[Any, int] = {}
    accept_latencies: List[int] = []
    # Accept time -> whether an edit followed it before the next accept.
    accept_times: List[int] = []
    edit_times: List[int] = []

    zoom = 1.0
    prev_t = ordered[0].t_ms

    for e in ordered:
        gap = e.t_ms - prev_t
        if gap > 0:
            if gap <= idle_ms:
                summary.active_ms += gap
                if zoom >= ZOOM_INSPECT_THRESHOLD:
                    summary.zoomed_ms += gap
            else:
                summary.idle_ms += gap
        prev_t = e.t_ms

        if e.action == "unknown":
            summary.unknown_events += 1

        elif e.action == "shape_add":
            summary.shapes_added += 1
            summary.shape_kinds[e.shape] = summary.shape_kinds.get(e.shape, 0) + 1
            if e.value > 0:
                vertex_counts.append(e.value)
                summary.vertices_total += e.value
            from_ai = (last_accept_at is not None
                       and e.t_ms - last_accept_at <= ACCEPT_SHAPE_WINDOW_MS)
            if from_ai:
                summary.shapes_from_ai += 1
                # Consumed: one accept produces one shape, so a second shape in
                # the window is genuinely drawn rather than a duplicate accept.
                last_accept_at = None
            else:
                summary.shapes_drawn += 1
                shape_times.append(e.t_ms)
            if summary.time_to_first_shape_ms is None:
                # From when the instance appeared, which is where `t_ms` is
                # measured from. Subtracting the first event's offset (as this
                # did) reported zero whenever the first event WAS the shape —
                # so the look-before-you-draw interval this exists to measure
                # was the one interval it could never see.
                summary.time_to_first_shape_ms = max(0, e.t_ms)

        elif e.action == "shape_edit":
            summary.shapes_edited += 1
            edit_times.append(e.t_ms)
        elif e.action == "shape_remove":
            summary.shapes_removed += 1
        elif e.action == "stroke":
            summary.strokes += 1
            summary.stroke_px_total += max(0, e.value)
        elif e.action == "fill":
            summary.fills += 1
        elif e.action == "tool":
            summary.tool_switches += 1
        elif e.action == "undo":
            summary.undo_count += 1
        elif e.action == "redo":
            summary.redo_count += 1
        elif e.action == "pan":
            summary.pan_events += 1
        elif e.action == "zoom":
            summary.zoom_events += 1
            # value is zoom x100; a client that omits it leaves zoom unchanged
            # rather than resetting the running level to 0.01.
            if e.value > 0:
                zoom = e.value / 100.0
                summary.max_zoom = max(summary.max_zoom, zoom)

        elif e.action == "ai_suggest":
            summary.ai_suggested += 1
            sid = (e.meta or {}).get("sid")
            if sid is not None:
                suggested_at[sid] = e.t_ms
        elif e.action == "ai_accept":
            summary.ai_accepted += 1
            accept_times.append(e.t_ms)
            last_accept_at = e.t_ms
            sid = (e.meta or {}).get("sid")
            if sid is not None and sid in suggested_at:
                accept_latencies.append(max(0, e.t_ms - suggested_at[sid]))
        elif e.action == "ai_reject":
            summary.ai_rejected += 1

    summary.vertices_median = float(_median(vertex_counts) or 0.0)

    if len(shape_times) >= 2:
        gaps = [b - a for a, b in zip(shape_times, shape_times[1:])]
        summary.shape_interval_median_ms = _median(gaps)
        summary.shape_interval_min_ms = min(gaps)

    if accept_latencies:
        summary.ai_accept_latency_median_ms = _median(accept_latencies)
        summary.ai_accept_latency_min_ms = min(accept_latencies)

    # An accept counts as "then edited" when an edit falls between it and the
    # next accept. Attributing every later edit to the accept would let one
    # correction excuse a hundred rubber-stamps.
    for i, at in enumerate(accept_times):
        upper = accept_times[i + 1] if i + 1 < len(accept_times) else math.inf
        if any(at < et < upper for et in edit_times):
            summary.ai_accepted_then_edited += 1

    denominator = summary.shapes_added + summary.shapes_edited
    summary.revision_ratio = (
        summary.shapes_edited / denominator if denominator else 0.0)

    if summary.ai_suggested:
        summary.ai_accept_rate = summary.ai_accepted / summary.ai_suggested

    if summary.duration_ms > 0:
        summary.zoomed_fraction = summary.zoomed_ms / summary.duration_ms

    return summary


def merge_summaries(
    summaries: Sequence[TelemetrySummary],
) -> Optional[TelemetrySummary]:
    """Combine sessions on the same field into one view.

    Leaving an image and coming back is one piece of work, not two short ones,
    and every rate below would be distorted by treating it as two. Counts add;
    medians are recomputed as count-weighted means of the parts, which is an
    approximation — the true median needs the raw streams, which are in SQLite
    for exactly that reason.
    """
    present = [s for s in summaries if s is not None]
    if not present:
        return None
    if len(present) == 1:
        return present[0]

    out = TelemetrySummary(
        schema_name=present[0].schema_name,
        instance_id=present[0].instance_id,
    )
    for attr in ("events", "unknown_events", "shapes_added", "shapes_from_ai",
                 "shapes_drawn", "shapes_edited",
                 "shapes_removed", "strokes", "fills", "vertices_total",
                 "stroke_px_total", "duration_ms", "active_ms", "idle_ms",
                 "zoom_events", "pan_events", "zoomed_ms", "undo_count",
                 "redo_count", "tool_switches", "ai_suggested", "ai_accepted",
                 "ai_rejected", "ai_accepted_then_edited"):
        setattr(out, attr, sum(getattr(s, attr) or 0 for s in present))

    out.max_zoom = max(s.max_zoom for s in present)
    for s in present:
        for kind, n in (s.shape_kinds or {}).items():
            out.shape_kinds[kind] = out.shape_kinds.get(kind, 0) + n

    firsts = [s.time_to_first_shape_ms for s in present
              if s.time_to_first_shape_ms is not None]
    out.time_to_first_shape_ms = min(firsts) if firsts else None

    out.vertices_median = _weighted_mean(
        [(s.vertices_median, s.shapes_added) for s in present]) or 0.0
    out.shape_interval_median_ms = _weighted_mean(
        [(s.shape_interval_median_ms, max(0, s.shapes_drawn - 1))
         for s in present])
    mins = [s.shape_interval_min_ms for s in present
            if s.shape_interval_min_ms is not None]
    out.shape_interval_min_ms = min(mins) if mins else None

    out.ai_accept_latency_median_ms = _weighted_mean(
        [(s.ai_accept_latency_median_ms, s.ai_accepted) for s in present])
    lat_mins = [s.ai_accept_latency_min_ms for s in present
                if s.ai_accept_latency_min_ms is not None]
    out.ai_accept_latency_min_ms = min(lat_mins) if lat_mins else None

    denominator = out.shapes_added + out.shapes_edited
    out.revision_ratio = out.shapes_edited / denominator if denominator else 0.0
    out.ai_accept_rate = (
        out.ai_accepted / out.ai_suggested if out.ai_suggested else 0.0)
    out.zoomed_fraction = (
        out.zoomed_ms / out.duration_ms if out.duration_ms else 0.0)
    return out


def _weighted_mean(
    pairs: Iterable[Tuple[Optional[float], int]]
) -> Optional[float]:
    total = 0.0
    weight = 0
    for value, w in pairs:
        if value is None or w <= 0:
            continue
        total += float(value) * w
        weight += w
    return total / weight if weight else None


# --------------------------------------------------------------------------
# Screening flags
#
# Kept in this module rather than a separate detector because the rule set is
# small and every rule reads directly off the summary. If it grows a fitted
# model it should move, exactly as typing_detect did.
# --------------------------------------------------------------------------


#: Defaults. Every one is a *starting point* for calibration, not a constant
#: with evidence behind it at these values — see the module docstring.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    #: Median ms between a suggestion appearing and being accepted.
    "ai_accept_latency_ms": 500.0,
    #: Below this many accepts, latency is too noisy to screen on.
    "min_accepts": 5.0,
    #: Fraction of accepts that were subsequently corrected. Above this, the
    #: annotator is evidently reviewing, whatever the latency says.
    "accept_edit_floor": 0.05,
    #: Median ms between consecutive shape commits.
    "shape_interval_ms": 700.0,
    #: Below this many shapes, interval is too noisy to screen on.
    "min_shapes": 4.0,
}


@dataclass
class TelemetryVerdict:
    """Screening output. ``flags`` is empty when nothing was triggered."""

    flags: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    notes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flags": list(self.flags),
            "scores": dict(self.scores),
            "notes": dict(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TelemetryVerdict":
        data = data or {}
        return cls(
            flags=list(data.get("flags") or []),
            scores=dict(data.get("scores") or {}),
            notes=dict(data.get("notes") or {}),
        )


def evaluate(
    summary: TelemetrySummary,
    thresholds: Optional[Dict[str, float]] = None,
) -> TelemetryVerdict:
    """Screen one summary for review-worthy patterns.

    Returns a verdict whose ``notes`` say what each flag does *not* establish.
    That is not decoration: a flag surfaced in an admin dashboard without its
    caveat will be read as a finding, and none of these are findings.
    """
    t = dict(DEFAULT_THRESHOLDS)
    t.update(thresholds or {})
    verdict = TelemetryVerdict()

    # -- rubber-stamping AI suggestions ------------------------------------
    accepts = summary.ai_accepted
    latency = summary.ai_accept_latency_median_ms
    if accepts >= t["min_accepts"] and latency is not None:
        edited_rate = (summary.ai_accepted_then_edited / accepts) if accepts else 0.0
        verdict.scores["ai_accept_latency_median_ms"] = float(latency)
        verdict.scores["ai_accept_edited_rate"] = edited_rate
        if latency < t["ai_accept_latency_ms"] and edited_rate <= t["accept_edit_floor"]:
            verdict.flags.append("rubber_stamping")
            verdict.notes["rubber_stamping"] = (
                f"{accepts} suggestions accepted with a median latency of "
                f"{latency:.0f}ms and {edited_rate:.0%} subsequently corrected. "
                "This is consistent with accepting without inspecting — and "
                "also with a detector whose output genuinely needs no "
                "correction. Check the suggestions before the annotator."
            )

    # -- unusually fast shape production -----------------------------------
    # Gated on shapes DRAWN, not shapes added: accepted suggestions arrive in
    # rapid succession by construction, and counting them would flag the
    # annotator whose accept latency proves they reviewed each one.
    interval = summary.shape_interval_median_ms
    if summary.shapes_drawn >= t["min_shapes"] and interval is not None:
        verdict.scores["shape_interval_median_ms"] = float(interval)
        if interval < t["shape_interval_ms"]:
            verdict.flags.append("hasty")
            verdict.notes["hasty"] = (
                f"Shapes committed a median of {interval:.0f}ms apart. Fast is "
                "not the same as careless, and box-drawing on obvious objects "
                "is genuinely quick; calibrate this threshold against the "
                "project's own distribution before acting on it."
            )

    # -- never inspected ---------------------------------------------------
    # Reported only alongside another signal. Alone it is uninformative: a
    # project whose objects fill the frame needs no zoom at all, and flagging
    # every such annotator would train reviewers to ignore the flag.
    if verdict.flags and summary.max_zoom < ZOOM_INSPECT_THRESHOLD:
        verdict.flags.append("never_zoomed")
        verdict.notes["never_zoomed"] = (
            "The image was never magnified. Only meaningful because another "
            "signal fired; on its own it says the objects may simply have been "
            "large enough to see."
        )

    return verdict


def calibrate_thresholds(
    rows: Sequence[Dict[str, Any]],
    percentile: float = 5.0,
) -> Dict[str, float]:
    """Fit thresholds from a project's own distribution.

    Args:
        rows: session feature dicts, as returned by
            ``annotation_telemetry_store.feature_matrix()``.
        percentile: the lower tail treated as unusual. 5 means "the fastest 5%
            of this project's sessions", which is a statement about *this*
            project and not a borrowed constant.

    Returns an empty dict when there is not enough data — a threshold fitted on
    a handful of sessions is worse than the documented default, because it looks
    principled.
    """
    out: Dict[str, float] = {}
    for key, column in (("ai_accept_latency_ms", "ai_accept_latency_median_ms"),
                        ("shape_interval_ms", "shape_interval_median_ms")):
        values = sorted(
            float(r[column]) for r in rows
            if r.get(column) is not None
        )
        if len(values) < 30:
            continue
        index = max(0, min(len(values) - 1,
                           int(round((percentile / 100.0) * (len(values) - 1)))))
        out[key] = values[index]
    return out
