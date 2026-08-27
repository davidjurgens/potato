"""
Agreement over time, and the re-calibration trigger built on it.

The IAA package had fourteen metric modules and no time dimension at all: it
could tell you what agreement *is*, never whether it is falling. That is the
half practitioners say matters. Calibration sessions -- annotators reviewing
pre-annotated items together and arguing about the disagreements -- are widely
credited with large agreement gains, and the qualifier that comes with the
advice is the operative part: it only holds if you re-calibrate periodically,
because guidelines drift as soon as new edge cases appear.

Drift is invisible to a single whole-project number. Early agreement and late
agreement average into one figure that looks acceptable while the recent work
has quietly become unusable.

Three decisions this module makes, all of them arguable, so all of them stated:

**Which timestamp.** An annotation has several. ``session_start`` is when the
annotator first *opened* the item, which for a queue skimmed once and answered
later is nowhere near when the answer was given. The last
:class:`~potato.interaction_tracking.AnnotationChange` for the schema is when
the answer reached its final value, which is what agreement is computed over,
so that is the anchor -- falling back to ``session_end``, then
``session_start``, then nothing.

**When an item enters a window.** Agreement is a property of an item across
annotators, not of one annotator's answer, so an item belongs to the window
containing the moment its *last* annotator finished it. That is when the item
first became measurable.

**Which metric.** Each window is scored by re-running
:func:`~potato.server_utils.iaa.dispatcher.compute_overlap_iaa` restricted to
that window's items, so every window uses the same per-schema metric the
whole-project report does. Picking one metric for the chart would silently
score a span schema and a slider schema with the same measure.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from potato.server_utils.iaa.dispatcher import compute_overlap_iaa, json_safe

logger = logging.getLogger(__name__)

#: Default number of windows the timeline is cut into when the caller does not
#: say. Six is enough to see a trend and few enough that each window keeps
#: enough items for a chance-corrected metric to mean anything.
DEFAULT_WINDOWS = 6

#: Below this many items a window's agreement is too noisy to act on. Windows
#: smaller than this are still reported -- hiding them would make a sparse
#: project look like it has no history -- but they are marked ``sparse`` and
#: the drop trigger ignores them.
MIN_ITEMS_PER_WINDOW = 5

#: Default relative fall in agreement that fires the re-calibration prompt.
#: 0.15 means "the latest window is 15% below the project baseline".
DEFAULT_DROP_THRESHOLD = 0.15

#: Metrics preferred when summarising a schema's window as one number, in
#: order. Chance-corrected measures come first: percent agreement rises with
#: class imbalance alone, so a chart of it can trend upward while the annotators
#: are agreeing less than chance would predict.
HEADLINE_METRICS = (
    "alpha_nominal", "alpha_ordinal", "alpha_interval", "alpha_masi",
    "krippendorff_alpha_u", "detection_alpha", "classification_alpha",
    "outcome.outcome_alpha",
    "fleiss_kappa", "cohen_kappa", "weighted_kappa_quadratic",
    "weighted_kappa_linear", "token_level_kappa",
    "kendall_tau", "icc_2_k", "pearson_r", "spearman_rho",
    "span_f1_exact", "detection_f1", "mean_jaccard", "mean_agreement",
    "percent_agreement",
)


# --------------------------------------------------------------- timestamps


def annotation_timestamp(user_state, instance_id: str,
                         schema_name: Optional[str] = None) -> Optional[float]:
    """
    When this annotator's answer on this item reached its final value.

    Prefers the last recorded change for ``schema_name`` -- the moment the
    answer being scored was actually given. ``session_end`` is the next best
    thing (when they navigated away), and ``session_start`` the last resort.

    Returns None when the item carries no behavioural data at all, which is
    normal for annotations imported or migrated in rather than made here.
    """
    behavioural = getattr(user_state, "instance_id_to_behavioral_data", None)
    if not behavioural:
        return None
    data = behavioural.get(instance_id)
    if data is None:
        return None

    changes = _attr(data, "annotation_changes") or []
    stamps = []
    for change in changes:
        if schema_name is not None and _attr(change, "schema_name") != schema_name:
            continue
        stamp = _attr(change, "timestamp")
        if isinstance(stamp, (int, float)) and stamp > 0:
            stamps.append(float(stamp))
    if stamps:
        return max(stamps)

    for key in ("session_end", "session_start"):
        stamp = _attr(data, key)
        if isinstance(stamp, (int, float)) and stamp > 0:
            return float(stamp)
    return None


def _attr(obj, name):
    """Read a field off a dataclass or the dict it deserialises to."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def item_completion_times(item_state_manager, user_states: Dict[str, Any],
                          instance_ids: Iterable[str],
                          schema_name: Optional[str] = None
                          ) -> Dict[str, float]:
    """
    ``{instance_id: when its last annotator finished}``, for items that have one.

    Items with no usable timestamp on any annotator are absent rather than
    given a default. Bucketing them into "now" would pile every migrated
    annotation into the most recent window and invent a cliff that is not
    there.
    """
    completed: Dict[str, float] = {}
    for iid in instance_ids:
        stamps = []
        for user_state in user_states.values():
            stamp = annotation_timestamp(user_state, iid, schema_name)
            if stamp is not None:
                stamps.append(stamp)
        if stamps:
            completed[iid] = max(stamps)
    return completed


# ------------------------------------------------------------------ windows


@dataclass
class Window:
    """One slice of the timeline and the agreement measured inside it."""

    index: int
    start: float
    end: float
    instance_ids: List[str] = field(default_factory=list)
    #: ``{schema_name: {metric: value}}``, from a restricted overlap report.
    schemas: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_items(self) -> int:
        return len(self.instance_ids)

    @property
    def sparse(self) -> bool:
        return self.n_items < MIN_ITEMS_PER_WINDOW

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "n_items": self.n_items,
            "sparse": self.sparse,
            "instance_ids": list(self.instance_ids),
            "schemas": json_safe(self.schemas),
        }


def split_windows(completion_times: Dict[str, float], n_windows: int = DEFAULT_WINDOWS,
                  by: str = "count") -> List[Window]:
    """
    Cut items into ``n_windows`` ordered slices.

    ``by="count"`` (the default) gives every window the same number of items;
    ``by="time"`` gives every window the same duration.

    Equal-count is the default because equal-duration windows on a study that
    ran in bursts produce empty stretches beside crowded ones, and an empty
    window's agreement is not a low number -- it is no number, which reads on a
    chart as a collapse.
    """
    if not completion_times or n_windows < 1:
        return []

    ordered = sorted(completion_times.items(), key=lambda pair: pair[1])

    if by == "time":
        first, last = ordered[0][1], ordered[-1][1]
        if last <= first:
            return [Window(index=0, start=first, end=last,
                           instance_ids=[iid for iid, _ in ordered])]
        span = (last - first) / n_windows
        windows = [Window(index=i, start=first + i * span,
                          end=first + (i + 1) * span)
                   for i in range(n_windows)]
        for iid, stamp in ordered:
            slot = min(int((stamp - first) / span), n_windows - 1)
            windows[slot].instance_ids.append(iid)
        return windows

    # Equal count. `n_windows` is capped at the item count so a five-item
    # project does not produce six windows, five of them empty.
    n_windows = min(n_windows, len(ordered))
    size = len(ordered) / n_windows
    windows: List[Window] = []
    for i in range(n_windows):
        chunk = ordered[int(round(i * size)):int(round((i + 1) * size))]
        if not chunk:
            continue
        windows.append(Window(
            index=len(windows),
            start=chunk[0][1],
            end=chunk[-1][1],
            instance_ids=[iid for iid, _ in chunk],
        ))
    return windows


def headline_metric(metrics: Dict[str, Any]) -> Tuple[Optional[str], Optional[float]]:
    """
    Pick one number to plot for a schema, preferring chance-corrected measures.

    Returns ``(metric_name, value)``, or ``(None, None)`` when nothing in the
    report is a usable number. Percent agreement is last on purpose: it rises
    with class imbalance alone, so a timeline drawn from it can trend upward
    while annotators agree less than chance would predict.
    """
    if not isinstance(metrics, dict):
        return None, None

    flat: Dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, dict):
            for inner, inner_value in value.items():
                flat[f"{key}.{inner}"] = inner_value
        else:
            flat[key] = value

    for name in HEADLINE_METRICS:
        value = flat.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isnan(value) and not math.isinf(value):
                return name, float(value)
    return None, None


# ------------------------------------------------------------------- report


def compute_agreement_over_time(item_state_manager, user_state_manager,
                                config: Dict[str, Any],
                                n_windows: int = DEFAULT_WINDOWS,
                                by: str = "count",
                                markers: Optional[Sequence[dict]] = None,
                                drop_threshold: Optional[float] = None
                                ) -> Dict[str, Any]:
    """
    Agreement per time window, with codebook markers and a drift verdict.

    Args:
        n_windows: How many slices to cut the timeline into.
        by: ``"count"`` for equal-sized windows, ``"time"`` for equal duration.
        markers: ``{revision, created_at, inferred}`` dicts from
            :func:`codebook_markers`, placed onto the timeline.
        drop_threshold: Relative fall from the baseline that fires the
            re-calibration prompt. Read from ``config`` when omitted.

    Returns:
        ``{"windows": [...], "schemas": {...}, "markers": [...],
        "triggers": [...], "n_items": int, "reason": str|None}``.
        ``reason`` is set, and everything else empty, when there is not enough
        data to compute anything -- so the admin page can say *why* rather than
        drawing an empty chart.
    """
    settings = (config.get("calibration") or {})
    if drop_threshold is None:
        drop_threshold = float(settings.get("drop_threshold",
                                            DEFAULT_DROP_THRESHOLD))

    overall = compute_overlap_iaa(item_state_manager, user_state_manager, config)
    overlap_ids = list(overall.get("items", {}).keys())
    if not overlap_ids:
        return _empty("No item has reached its annotator cap yet, so there is "
                      "no agreement to track over time.")

    user_states = _user_states_for(item_state_manager, user_state_manager,
                                   overlap_ids)
    completion = item_completion_times(item_state_manager, user_states,
                                       overlap_ids)
    if not completion:
        return _empty(
            "None of the overlapping items carry a timestamp, so they cannot "
            "be placed on a timeline. This is expected for annotations "
            "imported from another tool rather than made here.")

    windows = split_windows(completion, n_windows=n_windows, by=by)
    if len(windows) < 2:
        return _empty(
            "All the completed items fall in a single window, so there is "
            "nothing to compare against.")

    for window in windows:
        if not window.instance_ids:
            continue
        report = compute_overlap_iaa(item_state_manager, user_state_manager,
                                     config, instance_ids=window.instance_ids)
        window.schemas = report.get("schemas", {})

    schema_series = _build_series(windows, overall.get("schemas", {}))
    triggers = _find_drops(schema_series, windows, drop_threshold)

    return {
        "windows": [w.to_dict() for w in windows],
        "schemas": schema_series,
        "markers": [dict(m) for m in (markers or [])],
        "triggers": triggers,
        "drop_threshold": drop_threshold,
        "n_items": len(completion),
        "n_untimed_items": len(overlap_ids) - len(completion),
        "reason": None,
    }


def _empty(reason: str) -> Dict[str, Any]:
    return {"windows": [], "schemas": {}, "markers": [], "triggers": [],
            "drop_threshold": DEFAULT_DROP_THRESHOLD, "n_items": 0,
            "n_untimed_items": 0, "reason": reason}


def _user_states_for(item_state_manager, user_state_manager,
                     instance_ids: Iterable[str]) -> Dict[str, Any]:
    user_ids = set()
    for iid in instance_ids:
        user_ids.update(item_state_manager.instance_annotators.get(iid, ()) or ())
    states = {}
    for uid in user_ids:
        getter = getattr(user_state_manager, "get_user_state", None)
        state = getter(uid) if getter else None
        if state is not None:
            states[uid] = state
    return states


def _build_series(windows: List[Window],
                  overall_schemas: Dict[str, Any]) -> Dict[str, Any]:
    """
    Per schema: the metric being plotted, the value in each window, a baseline.

    The baseline is the whole-project figure rather than the first window's.
    A first window that happens to be unusually good or bad would otherwise
    set the bar for the entire study, and the first window is exactly where a
    still-uncalibrated team's numbers are least stable.
    """
    series: Dict[str, Any] = {}
    for name, report in overall_schemas.items():
        metric, baseline = headline_metric(report.get("metrics", {}))
        points = []
        for window in windows:
            window_report = window.schemas.get(name) or {}
            window_metrics = window_report.get("metrics", {}) or {}
            value = None
            note = None
            if metric is not None:
                _found, value = headline_metric(window_metrics)
                # Only compare like with like: if this window's best available
                # metric is not the one the baseline used, the comparison is
                # between two different measures and means nothing.
                if _found != metric:
                    value = None
            if value is None:
                note = _why_undefined(window, window_metrics, metric)
            points.append({
                "window": window.index,
                "value": value,
                "note": note,
                "n_items": window.n_items,
                "sparse": window.sparse,
            })
        used = [n for n in NOTE_FOOTNOTES
                if any(p.get("note") == n for p in points)]
        series[name] = {
            "metric": metric,
            "baseline": baseline,
            "kind": report.get("kind"),
            "annotation_type": report.get("annotation_type"),
            "points": points,
            "footnotes": [{"note": n, "explanation": NOTE_FOOTNOTES[n]}
                          for n in used],
        }
    return series


def _why_undefined(window: Window, metrics: Dict[str, Any],
                   metric: Optional[str]) -> Optional[str]:
    """
    Say why a window has no number, rather than leaving a hole in the chart.

    The case that makes this necessary: a chance-corrected coefficient is
    undefined when there is nothing to be right about by chance -- every
    annotator choosing the same label on every item gives 0/0. So a window of
    PERFECT agreement plots as a gap, which reads as missing data and is the
    exact opposite of what happened. Distinguishing "undefined because there
    was no disagreement to correct for" from "no data" is the difference
    between good news and a broken chart.
    """
    if not window.instance_ids:
        return "no items"
    if not metrics:
        return "no overlap"

    # Raw agreement, which stays defined where the coefficient does not.
    for raw in ("percent_agreement", "fleiss_kappa", "mean_agreement"):
        value = metrics.get(raw)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value == value and value >= 0.999:
                return "total agreement"
    return "undefined"


#: What each short cell note means, spelled out once under the table rather
#: than repeated in every cell -- the same footnote idiom the sweep tables on
#: this page already use. Repeating the sentence per cell forced the column
#: two hundred pixels wide and made the timeline unscannable, which defeats
#: the point of putting it in a row.
NOTE_FOOTNOTES = {
    "total agreement": (
        "every annotator chose the same label on every item in this window, so "
        "a chance-corrected coefficient has no disagreement to correct for and "
        "is undefined. This is the best case, not missing data."),
    "no overlap": (
        "fewer than two annotators overlapped on these items, so agreement "
        "cannot be computed."),
    "no items": "no items fell in this window.",
    "undefined": (
        "the metric is undefined for this window's data, most often because "
        "one label accounts for every judgement in it."),
}


def _find_drops(series: Dict[str, Any], windows: List[Window],
                threshold: float) -> List[dict]:
    """
    Which schemas have fallen far enough below baseline to warrant re-calibrating.

    Only the latest non-sparse window is judged. An earlier dip that the team
    already recovered from is history, not a call to action, and firing on it
    would train people to ignore the prompt.
    """
    triggers = []
    for name, entry in series.items():
        baseline = entry.get("baseline")
        if not isinstance(baseline, (int, float)) or baseline <= 0:
            # A baseline at or below zero means annotators already agree no
            # better than chance. A *relative* drop from it is meaningless --
            # that is a problem the whole-project number already reports.
            continue

        latest = None
        for point in reversed(entry.get("points") or []):
            if point.get("sparse"):
                continue
            if isinstance(point.get("value"), (int, float)):
                latest = point
                break
        if latest is None:
            continue

        drop = (baseline - latest["value"]) / baseline
        if drop >= threshold:
            triggers.append({
                "schema": name,
                "metric": entry.get("metric"),
                "baseline": baseline,
                "latest": latest["value"],
                "relative_drop": drop,
                "window": latest["window"],
                "n_items": latest["n_items"],
            })
    return sorted(triggers, key=lambda t: t["relative_drop"], reverse=True)


# ----------------------------------------------------------------- markers


def codebook_markers(task_dir: str, project: str) -> List[dict]:
    """
    When the codebook changed, for overlaying on the agreement timeline.

    A guideline edit that moved agreement is only visible if the edit and the
    movement are on the same axis -- that is the whole point of the overlay,
    and it is a join of two things Potato already had rather than new
    measurement.

    Bumps recorded since ``codebook_revision_history`` exists are exact.
    Older ones are filled in from the earliest annotation stamped with each
    revision, which is a lower bound, and are flagged ``inferred: True`` so
    the UI can draw them differently rather than presenting a guess as a fact.

    Returns ``[]`` on any failure: an admin page must not 500 because a
    project has no codebook database.
    """
    try:
        from potato.codebook.revision import revision_first_seen, revision_history
    except Exception:
        return []

    try:
        exact = {int(row["revision"]): float(row["created_at"])
                 for row in revision_history(task_dir, project)}
        inferred = revision_first_seen(task_dir, project)
    except Exception:
        logger.debug("Could not read codebook revisions for %s/%s",
                     task_dir, project, exc_info=True)
        return []

    markers = []
    for revision, created_at in sorted(exact.items()):
        markers.append({"revision": revision, "created_at": created_at,
                        "inferred": False})
    for revision, first_seen in sorted(inferred.items()):
        if revision in exact or revision <= 0:
            continue
        markers.append({"revision": revision, "created_at": first_seen,
                        "inferred": True})

    return sorted(markers, key=lambda m: m["created_at"])
