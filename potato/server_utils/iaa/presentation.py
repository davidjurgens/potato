"""
Turning an agreement report into rows a table can draw.

## Why the template could not be left to do this

`/admin/iaa?format=html` iterated ``metrics.items()`` and formatted each value
with ``"%.3f"`` when it was a number and ``n/a`` otherwise. That works for a
report that is a flat mapping of name to score, which is what nominal, ordinal,
continuous and geometry reports are.

It is wrong for the two that are not. A rollout report is four groups of
metrics behind a sweep over a matching tolerance; an episode report is three
groups. Every one of those groups is a dict, so every real number in both
reports rendered as **n/a** — and the only numbers that did render were the
ones that are not scores at all. ``n_items_skipped: 0`` came out as **"weak
agreement"**, in red, because the banding rule was ``value < 0.2`` applied to
whatever happened to be numeric.

Both failures are the same mistake: asking the template to infer what a metric
*is* from its value. It cannot. ``0.0`` is the floor for alpha, a neutral for a
count, and a perfect score for mean absolute error. So the classification lives
here, keyed on the metric's **name**, and the template only draws what it is
handed.

## Notes are content, not the absence of content

``_alpha_result`` deliberately returns ``alpha: None`` with a sentence saying
why — "every annotator marked the same breaks, so there is no variation for
alpha to correct against. Perfect agreement, not a failed computation." The
flat table printed that as ``n/a``, which says the opposite of what the
sentence says. Notes travel with their row here.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence

#: How a metric should be read. The template uses this for two decisions —
#: whether a value may be banded strong/weak, and which explanatory note to
#: print above the table — and nothing else.
#:
#: ``kappa``        chance-corrected, roughly -1..1, higher better. Bandable.
#: ``correlation``  -1..1, higher better. Bandable.
#: ``raw``          0..1 with no chance correction, higher better. Bandable.
#: ``span``         span F1 / token kappa, higher better. Bandable.
#: ``lower``        an error or a distance. **Lower** is better, so the
#:                  strong/weak bands would be exactly inverted. Never banded.
#: ``distribution`` a test statistic, not an agreement score. Never banded.
#: ``coverage``     how much of the task was answered. 0..1 and higher is
#:                  better, but it is not agreement: a coverage of 1.0 banded
#:                  "strong agreement" says annotators agreed when all it says
#:                  is that they answered. Never banded.
#: ``count``        a count, a parameter, a frame rate. Never banded, and
#:                  rendered as an integer rather than to three decimals.
#: ``unknown``      a name this module does not recognise. Never banded — see
#:                  the note on the fallback in ``metric_scale``.
SCALES = ("kappa", "correlation", "raw", "span", "lower", "distribution",
          "coverage", "count", "unknown")

_CORRELATION = {"pearson_r", "spearman_rho", "kendall_tau", "icc_2_k",
                "icc_2_1", "reward_icc", "reward_pearson_r", "correlation"}
_RAW = {"percent_agreement", "mean_jaccard", "mean_agreement",
        "mean_matched_iou", "detection_f1", "span_f1_exact",
        "span_f1_partial", "iou", "giou",
        # Grounding: an expression id supplies the correspondence, so these are
        # plain overlap between two answers to the same question -- not
        # chance-corrected, and not to be read against the kappa bands.
        "mean_iou", "median_iou",
        # The sweep column: the fraction of compared expression pairs that
        # clear the row's IoU threshold.
        "agreement"}
_COVERAGE = {"reward_coverage", "answered_fraction"}
_SPAN = {"span_f1_exact", "span_f1_partial", "token_level_kappa"}
_LOWER = {"mae", "rmse", "spearman_footrule", "mean_offset", "median_offset",
          "mean_chance_offset", "mean_object_count_diff",
          # A caption distance, or the gap between two annotators' points: 0
          # means they gave the same answer, so banding either as an agreement
          # score inverts it.
          "mean_pairwise_distance", "median_pairwise_distance"}
_COUNT_NAMES = {"fps", "tolerance", "tolerance_frames", "headline_tolerance",
                "cap", "answered_stream_responses",
                "possible_stream_responses",
                # Parameters of the grounding sweep, not measurements taken
                # from it.
                "iou_threshold", "headline_iou_threshold"}

#: alpha and kappa appear as a whole underscore-separated token in every name
#: this codebase produces — `alpha`, `detection_alpha`, `alpha_masi`,
#: `krippendorff_alpha_u`, `weighted_kappa_linear` — and matching the token
#: rather than listing the names means a new coefficient is classified before
#: anyone remembers to add it here.
_KAPPA_TOKEN = re.compile(r"(?:^|_)(?:alpha|kappa|gamma)(?:_|$)")


def metric_scale(name: str) -> str:
    """
    Which scale a metric is on, from its name alone.

    The leaf of a dotted name decides it: ``detection.alpha`` and a bare
    ``alpha`` are the same coefficient and must be read the same way.
    """
    leaf = str(name).rsplit(".", 1)[-1]
    if leaf.startswith("n_") or leaf in _COUNT_NAMES:
        return "count"
    if leaf.endswith("_frames") and len(leaf) > len("_frames"):
        # `mean_offset_frames` is `mean_offset` in different units. Without
        # this, a metric quoted in both seconds and frames needs two entries in
        # every table below, and forgetting one is silent: `median_offset_frames`
        # fell through to the bandable default and a five-frame disagreement
        # was labelled "strong agreement" in green.
        return metric_scale(leaf[:-len("_frames")])
    if leaf in _LOWER:
        return "lower"
    if leaf in _COVERAGE:
        return "coverage"
    if leaf in _SPAN:
        return "span"
    if leaf in _CORRELATION:
        return "correlation"
    if leaf in _RAW:
        return "raw"
    if leaf == "ks":
        # A two-sample Kolmogorov-Smirnov statistic. It is in [0, 1] and higher
        # does mean more separation between the within- and between-item
        # distributions, but it is a distance between distributions, not an
        # agreement coefficient, and banding it as one would invite reading it
        # against the kappa conventions.
        return "distribution"
    if leaf == "sigma":
        # 1 - mean(within)/mean(between): alpha's own form applied to offsets,
        # so it reads on the same scale.
        return "kappa"
    if _KAPPA_TOKEN.search(leaf):
        return "kappa"
    # Unrecognised, and therefore unbanded. Defaulting to a bandable scale is
    # the same mistake this module exists to fix, one level up: it decides that
    # an unknown 0.9 is "strong agreement" on no evidence beyond its being a
    # number. A missing band is a missing hint; a wrong band is a false claim.
    return "unknown"


#: Only these may carry a strong/weak band. See ``metric_scale``.
BANDABLE = ("kappa", "correlation", "raw", "span")

#: Keys that describe the sweep rather than being metrics of their own.
#: :func:`sweep_table` reads them; :func:`flatten` must not emit them as rows.
_SWEEP_KEYS = frozenset({"sweep", "sweep_parameter", "sweep_parameter_label"})


def band_for(name: str, value: Any) -> str:
    """``"strong"``, ``"weak"``, or ``""`` — the empty string meaning unbanded."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if metric_scale(name) not in BANDABLE:
        return ""
    if value >= 0.6:
        return "strong"
    if value < 0.2:
        return "weak"
    return ""


def flatten(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    A report's scalars as display rows, one level of grouping flattened out.

    Groups become dotted names — ``detection.alpha`` — which is the form
    :func:`~potato.server_utils.iaa.dispatcher.metrics_for_schema` already
    declares, so the names on the page and the names in that table are the same
    strings.

    Sweeps are not flattened: a five-tolerance sweep over four groups is 120
    rows and a curve read down a table of 120 rows is not read at all. It comes
    back from :func:`sweep_table` instead.
    """
    rows: List[Dict[str, Any]] = []
    for key, value in metrics.items():
        if key in _SWEEP_KEYS:
            continue
        if isinstance(value, dict):
            rows.extend(_group_rows(key, value))
        elif isinstance(value, list):
            continue
        elif key == "note":
            rows.append(_row("note", None, note=str(value)))
        else:
            rows.append(_row(key, value))
    return rows


def _group_rows(prefix: str, group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    One group of a nested report: its measures, with its counts subordinated.

    A group carries both — ``detection`` is an alpha over 6 judgements about 3
    units — and giving each its own row buries the one number the reader came
    for under its own denominators. A rollout report has 9 measures and 19
    counts; as equal rows that is a 28-row table where nothing stands out.

    So the counts become a caption on the measures they qualify. They are not
    dropped: a coefficient over four judgements and one over four hundred are
    different claims, and the reader has to be able to tell without opening the
    JSON. A group that is *only* counts (nothing to caption) keeps them as
    rows.

    The group's ``note`` is not a row either. It explains why a value is
    missing, so it attaches to the missing value; printed beside it, the row
    would still say ``n/a`` — the thing the note exists to contradict.
    """
    note = group.get("note")
    measures: List[Dict[str, Any]] = []
    counts: List[Dict[str, Any]] = []
    for key, value in group.items():
        if key == "note" or isinstance(value, (dict, list)):
            continue
        row = _row(f"{prefix}.{key}", value)
        (counts if row["scale"] == "count" else measures).append(row)

    if not measures:
        return counts

    context = ", ".join(_count_phrase(row) for row in counts
                        if row["value"] is not None)
    for index, row in enumerate(measures):
        # On the first measure only. The denominators are the same for every
        # measure in the group — repeating "3 matched pairs, 2,000 chance
        # pairs" under six consecutive rows reads as six different facts.
        row["context"] = context if index == 0 else ""
        if note and row["value"] is None:
            row["note"] = str(note)
            row["display"] = ""
    return measures


def _count_phrase(row: Dict[str, Any]) -> str:
    """``n_judgements: 6`` reads as "6 judgements" in a caption."""
    leaf = row["name"].rsplit(".", 1)[-1]
    if leaf.startswith("n_"):
        return f"{row['display']} {leaf[2:].replace('_', ' ')}"
    if leaf.endswith("_responses"):
        # "answered stream responses 18" is not a sentence. These come in
        # answered/possible pairs, so the noun belongs once, at the end.
        return f"{row['display']} {leaf.split('_')[0]}"
    return f"{leaf.replace('_', ' ')} {row['display']}"


def _row(name: str, value: Any, note: str = "") -> Dict[str, Any]:
    """
    One display row. ``display`` is the finished string the cell prints.

    Formatting happens here rather than in the template because the correct
    format depends on what the metric is: a count of 2000 chance pairs printed
    as ``2000.000`` reads as a measurement, and a coefficient printed as ``1``
    reads as a count.
    """
    if isinstance(value, float) and math.isnan(value):
        value = None
    scale = metric_scale(name)
    if isinstance(value, str):
        # A string metric is its own explanation; there is nothing to format.
        return {"name": name, "value": None, "display": value, "is_text": True,
                "note": note, "context": "", "scale": scale, "band": ""}
    if value is None:
        # A note explains why the value is missing, so printing "n/a" in front
        # of it contradicts the sentence that follows.
        display = "" if note else "n/a"
    elif scale == "count" and isinstance(value, (int, float)):
        # Integer format only when the value *is* integral. The scale also
        # covers parameters — a 0.5 s matching window, a 29.97 frame rate —
        # and rounding those to "0" and "30" prints a different number from
        # the one the report computed.
        display = (f"{value:,.0f}" if float(value).is_integer()
                   else f"{value:g}")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        display = f"{value:.3f}"
    else:
        display = str(value)
    return {"name": name, "value": value, "display": display, "is_text": False,
            "note": note, "context": "", "scale": scale,
            "band": band_for(name, value)}


def sweep_table(metrics: Dict[str, Any],
                columns: Optional[Sequence[str]] = None,
                ) -> Optional[Dict[str, Any]]:
    """
    The sweep as a table: one row per parameter value, one column per metric.

    The sweep is the finding, not an appendix to it. Agreement that is flat
    across the sweep means annotators identify the same instant; agreement that
    appears only at the loosest tolerance means the most anyone can claim is
    that something is wrong somewhere in the clip. A reader can see which of
    those they are looking at from a table and cannot see it from a single
    headline number, which is why the headline row is marked rather than
    extracted.

    ``columns`` defaults to whatever dotted names the sweep rows contain, in
    first-seen order; pass ``metrics_for_schema(scheme)`` to pin the column set
    and its order to the schema's declared metrics.
    """
    sweep = metrics.get("sweep")
    if not isinstance(sweep, list) or not sweep:
        return None
    if not all(isinstance(row, dict) for row in sweep):
        return None

    parameter = metrics.get("sweep_parameter") or "tolerance"
    if parameter not in sweep[0]:
        return None

    available: List[str] = []
    for row in sweep:
        for key, value in row.items():
            if key == parameter or isinstance(value, list):
                continue
            if isinstance(value, dict):
                for leaf, inner in value.items():
                    if leaf == "note" or isinstance(inner, (dict, list)):
                        continue
                    name = f"{key}.{leaf}"
                    if name not in available:
                        available.append(name)
            elif key not in available:
                available.append(key)

    chosen = [c for c in (columns or available) if c in available]
    if not chosen:
        chosen = available

    headline = metrics.get(f"headline_{parameter}")
    # An undefined cell in a sweep needs its reason as badly as one in the flat
    # table does — "alpha is undefined because everyone agreed" and "alpha is
    # undefined because there was nothing to compare" are opposite readings of
    # the same blank. A sweep cell has no room for a sentence, so the reasons
    # become numbered footnotes under the table.
    footnotes: List[str] = []
    body = []
    for row in sweep:
        cells = []
        for name in chosen:
            value, note = _lookup(row, name)
            cell = _row(name, value, note=note)
            cell["footnote"] = 0
            if note:
                if note not in footnotes:
                    footnotes.append(note)
                cell["footnote"] = footnotes.index(note) + 1
                cell["display"] = "—"
            cells.append(cell)
        value = row.get(parameter)
        body.append({
            "parameter": value,
            "is_headline": (headline is not None
                            and isinstance(value, (int, float))
                            and abs(float(value) - float(headline)) < 1e-9),
            "cells": cells,
        })
    return {"parameter": parameter,
            "parameter_label": metrics.get("sweep_parameter_label") or parameter,
            "columns": chosen, "rows": body, "headline": headline,
            "footnotes": footnotes}


def _lookup(row: Dict[str, Any], dotted: str):
    """``(value, note)`` for a dotted name, the note being the group's."""
    node: Any = row
    parent: Any = None
    for part in dotted.split("."):
        parent = node
        node = node.get(part) if isinstance(node, dict) else None
    note = ""
    if node is None and isinstance(parent, dict):
        note = str(parent.get("note") or "")
    return node, note


#: Scales that get an explanatory note above the table. The note's *text* is
#: not here: it is localized, and lives in ``i18n.py`` under
#: ``iaa_scale_<scale>_label`` / ``_note`` with zh and ja translations. This
#: layer decides which notes a card needs; the template prints them. Counts are
#: absent deliberately — a count needs no scale explained.
SCALE_NOTES = ("kappa", "correlation", "raw", "span", "lower", "distribution",
               "coverage")


def present(report: Dict[str, Any]) -> Dict[str, Any]:
    """
    A display-ready copy of a full ``/admin/iaa`` report.

    Only the HTML path calls this. The JSON body stays the nested report, which
    is what the API contract and every downstream analysis script read; a
    presentation layer that changed the payload would be a breaking change made
    for the benefit of a table.
    """
    from potato.server_utils.iaa.dispatcher import metrics_for_schema

    out = dict(report)
    schemas = {}
    for name, schema in (report.get("schemas") or {}).items():
        metrics = schema.get("metrics") or {}
        declared = metrics_for_schema(
            {"annotation_type": schema.get("annotation_type"), "name": name},
            kind=schema.get("kind"))
        rows = flatten(metrics)
        table = sweep_table(metrics, declared)
        present_scales = [row["scale"] for row in rows]
        if table:
            present_scales.extend(metric_scale(c) for c in table["columns"])
        # In SCALE_NOTES' order, not first-seen order: the notes are a legend
        # and a legend that reorders itself per card is read as a different
        # legend.
        scales = [s for s in SCALE_NOTES if s in present_scales]
        schemas[name] = dict(schema, rows=rows, sweep=table, scales=scales,
                             n_items=metrics.get("n_items"),
                             n_annotators=metrics.get("n_annotators"),
                             n_aligned_items=metrics.get("n_aligned_items"))
    out["schemas"] = schemas
    return out
