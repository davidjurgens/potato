"""
Reliability Exporter

The intercoder-reliability table content analyses report: one row per
question with Krippendorff's alpha, a 95% bootstrap interval, percent
agreement, and how many units and coders it rests on.

Written to ``reliability.csv`` and ``reliability.md`` (the same table as
Markdown, ready to paste into a methods section).

The level of measurement follows the question type: ``radio`` / ``select``
nominal, ``likert`` ordinal, ``number`` / ``slider`` / ``vas`` interval,
``multiselect`` and ``hierarchical_multiselect`` MASI (Passonneau 2006; sets
that overlap count as partial agreement). ``span`` is positional: nominal
alpha with every character of the item as a unit, labelled by the span covering
it or ``O``, pooled over items (the coefficient /admin/iaa reports per item as
``positional_alpha``). A coder who opened an item and marked nothing counts as
``O`` throughout. Alpha comes from ``potato.server_utils.iaa.alpha``. The interval
is a percentile bootstrap that resamples units (items) with replacement,
``bootstrap`` times (default 1000), seeded so it reproduces; this is not the
coincidence-resampling bootstrap of Hayes & Krippendorff (2007). Percent
agreement is the share of coder pairs on a unit that gave the same answer.

Only units coded by two or more coders count. Krippendorff (2004) suggests
relying on variables with alpha of at least .800 and drawing tentative
conclusions down to .667; the table reports the numbers and leaves the
judgment to the reader.
"""

from __future__ import annotations

import csv
import itertools
import math
import os
import random
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

LEVELS = {"radio": "nominal", "select": "nominal", "likert": "ordinal", "number": "interval",
          "slider": "interval", "vas": "interval", "multiselect": "masi",
          "hierarchical_multiselect": "masi", "span": "positional"}
COLUMNS = ["schema", "level", "alpha", "ci95_low", "ci95_high", "percent_agreement",
           "units", "coders", "pairable_values"]


def _value(scheme: dict, labels: Any):
    if not isinstance(labels, dict) or not labels:
        return None
    kind = scheme.get("annotation_type")
    if kind == "hierarchical_multiselect":
        # Stored as one comma-joined value, {"selected_labels": "101,201"}.
        from potato.server_utils.iaa.dispatcher import _unpack_joined
        return frozenset(_unpack_joined(labels, "selected_labels")) or None
    if kind == "multiselect":
        chosen = frozenset(k for k, v in labels.items() if v not in (None, "", False))
        return chosen or None
    if kind in ("radio", "select"):
        for k, v in labels.items():
            if v not in (None, "", False):
                return str(v) if kind == "select" else str(k)
        return None
    for v in labels.values():
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _alpha(rows, level):
    from potato.server_utils.iaa.alpha import krippendorff_alpha
    try:
        return krippendorff_alpha(rows, level=level)
    except Exception:
        return float("nan")


def _span_units(context: ExportContext, scheme: dict) -> Dict[Tuple[str, str], dict]:
    """``{(item, field): {"length": n, "coders": {coder: [spans]}}}``.

    Every coder with a record on the item is a coder of each of its fields, so
    one who read the item and highlighted nothing counts as all ``O``.
    """
    name = scheme["name"]
    text_key = (context.config.get("item_properties") or {}).get("text_key", "text")
    records: Dict[str, Dict[str, list]] = defaultdict(dict)
    for ann in context.annotations:
        spans = (ann.get("spans") or {}).get(name) or []
        records[str(ann.get("instance_id"))][str(ann.get("user_id"))] = [
            s for s in spans if isinstance(s, dict)]
    units: Dict[Tuple[str, str], dict] = {}
    for item_id, by_coder in records.items():
        if len(by_coder) < 2:
            continue
        fields = {s.get("target_field") or text_key
                  for spans in by_coder.values() for s in spans}
        for field_name in fields or ():
            mine = {c: [(s.get("start"), s.get("end"), s.get("name") or s.get("label"))
                        for s in spans if (s.get("target_field") or text_key) == field_name]
                    for c, spans in by_coder.items()}
            item = context.items.get(item_id)
            text = context._span_anchor_text(item, field_name) if isinstance(item, dict) else None
            if isinstance(text, str) and text:
                length = len(text)
            else:
                # No source to measure: the furthest span end is the best bound.
                ends = [int(e) for spans in mine.values() for _s, e, _l in spans
                        if isinstance(e, (int, float))]
                length = max(ends, default=0)
            if length > 0:
                # A span ending past the text it was measured against is
                # scored only up to the text's end; counted so it is said.
                past = sum(1 for spans in mine.values() for _s, e, _l in spans
                           if isinstance(e, (int, float)) and e > length)
                units[(item_id, field_name)] = {"length": length, "coders": mine,
                                                "past_end": past}
    return units


def _span_coincidences(unit: dict):
    """Per-unit coincidence counts for nominal alpha, and agreeing pairs.

    Counting by the pattern of labels across coders keeps this linear in the
    text length, so the bootstrap can sum per-item tables instead of
    recomputing alpha over every character a thousand times.
    """
    from potato.server_utils.iaa.span import spans_to_bio
    length = unit["length"]
    columns = []
    for spans in unit["coders"].values():
        tags = spans_to_bio(spans, length)
        columns.append(["O" if t == "O" else t.split("-", 1)[1] for t in tags])
    m = len(columns)
    patterns = Counter(zip(*columns))
    o: Dict[Tuple[str, str], float] = defaultdict(float)
    agree = 0
    for pattern, times in patterns.items():
        counts = Counter(pattern)
        for c, nc in counts.items():
            agree += times * nc * (nc - 1) // 2
            for k, nk in counts.items():
                o[(c, k)] += times * (nc * nk - (nc if c == k else 0)) / (m - 1)
    return o, agree, length * m * (m - 1) // 2, length * m


def _alpha_from_coincidences(o: Dict[Tuple[str, str], float]) -> float:
    totals: Dict[str, float] = defaultdict(float)
    for (c, _k), v in o.items():
        totals[c] += v
    n = sum(totals.values())
    expected = n * n - sum(v * v for v in totals.values())
    if n <= 1 or expected <= 0:
        return float("nan")
    observed = sum(v for (c, k), v in o.items() if c != k)
    return 1.0 - (n - 1) * observed / expected


def _merge(tables):
    out: Dict[Tuple[str, str], float] = defaultdict(float)
    for table in tables:
        for key, v in table.items():
            out[key] += v
    return out


def _round(x):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 3)


class ReliabilityExporter(BaseExporter):
    format_name = "reliability"
    description = "Intercoder reliability per question: Krippendorff's alpha with bootstrap CI"
    file_extensions = [".csv", ".md"]

    def _schemes(self, context):
        return [s for s in context.schemas or [] if s.get("annotation_type") in LEVELS]

    @staticmethod
    def _span_row(context, scheme, reps, seed, undefined_notes):
        name = scheme["name"]
        units = _span_units(context, scheme)
        past = [f"{item}" for (item, _f), unit in sorted(units.items()) if unit.get("past_end")]
        if past:
            undefined_notes.append(
                f"{name}: {sum(units[k]['past_end'] for k in units)} span(s) end past the "
                f"item's text, on {', '.join(past[:10])}"
                f"{' and more' if len(past) > 10 else ''}. They are scored up to the end "
                f"of the text; the item's text may have changed since it was coded.")
        tables = {key: _span_coincidences(unit) for key, unit in units.items()}
        alpha = _alpha_from_coincidences(_merge(t[0] for t in tables.values())) \
            if units else float("nan")
        agree = sum(t[1] for t in tables.values())
        pairs = sum(t[2] for t in tables.values())
        low = high = None
        if reps and len(units) >= 2 and not math.isnan(alpha):
            rng = random.Random(seed)
            keys = sorted(units)
            draws = []
            for _ in range(reps):
                a = _alpha_from_coincidences(_merge(
                    tables[keys[rng.randrange(len(keys))]][0] for _ in keys))
                if not math.isnan(a):
                    draws.append(a)
            if len(draws) < reps:
                undefined_notes.append(
                    f"{name}: alpha was undefined (no variation) in {reps - len(draws)} of "
                    f"{reps} bootstrap resamples; the interval uses the other {len(draws)}")
            if draws:
                draws.sort()
                low = draws[int(0.025 * (len(draws) - 1))]
                high = draws[int(math.ceil(0.975 * (len(draws) - 1)))]
        coders = {c for unit in units.values() for c in unit["coders"]}
        return {"schema": name, "level": "positional", "alpha": _round(alpha),
                "ci95_low": _round(low), "ci95_high": _round(high),
                "percent_agreement": _round(100.0 * agree / pairs) if pairs else "",
                "units": len(units), "coders": len(coders),
                "pairable_values": sum(t[3] for t in tables.values())}

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No question type with a reliability coefficient (radio, likert, number, span, ...)"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        reps = int(options.get("bootstrap", 1000))
        seed = int(options.get("seed", 20261023))
        os.makedirs(output_path, exist_ok=True)
        out_rows = []
        undefined_notes = []
        for scheme in self._schemes(context):
            name, level = scheme["name"], LEVELS[scheme["annotation_type"]]
            if level == "positional":
                out_rows.append(self._span_row(context, scheme, reps, seed, undefined_notes))
                continue
            by_unit: Dict[str, Dict[str, Any]] = defaultdict(dict)
            for ann in context.annotations:
                v = _value(scheme, (ann.get("labels") or {}).get(name))
                if v is not None:
                    by_unit[str(ann.get("instance_id"))][str(ann.get("user_id"))] = v
            units = {u: c for u, c in by_unit.items() if len(c) >= 2}
            coders = {c for codes in units.values() for c in codes}
            long = [(c, u, v) for u, codes in units.items() for c, v in codes.items()]
            alpha = _alpha(long, level) if len(units) >= 2 else float("nan")
            pairs = agree = 0
            for codes in units.values():
                for a, b in itertools.combinations(codes.values(), 2):
                    pairs += 1
                    agree += int(a == b)
            low = high = None
            if reps and len(units) >= 2 and not math.isnan(alpha):
                rng = random.Random(seed)
                keys = sorted(units)
                draws = []
                for _ in range(reps):
                    sample = [keys[rng.randrange(len(keys))] for _ in keys]
                    rows = [(c, f"{u}#{i}", v) for i, u in enumerate(sample)
                            for c, v in units[u].items()]
                    a = _alpha(rows, level)
                    if not math.isnan(a):
                        draws.append(a)
                if len(draws) < reps:
                    undefined_notes.append(
                        f"{name}: alpha was undefined (no variation) in {reps - len(draws)} of "
                        f"{reps} bootstrap resamples; the interval uses the other {len(draws)}")
                if draws:
                    draws.sort()
                    low = draws[int(0.025 * (len(draws) - 1))]
                    high = draws[int(math.ceil(0.975 * (len(draws) - 1)))]
            out_rows.append({"schema": name, "level": level, "alpha": _round(alpha),
                             "ci95_low": _round(low), "ci95_high": _round(high),
                             "percent_agreement": _round(100.0 * agree / pairs) if pairs else "",
                             "units": len(units), "coders": len(coders),
                             "pairable_values": len(long)})
        csv_path = os.path.join(output_path, "reliability.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(out_rows)
        md_path = os.path.join(output_path, "reliability.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("| Variable | Level | Krippendorff's α | 95% CI | % agreement | Units | Coders |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            for r in out_rows:
                ci = f"[{r['ci95_low']}, {r['ci95_high']}]" if r["ci95_low"] != "" else ""
                f.write(f"| {r['schema']} | {r['level']} | {r['alpha']} | {ci} | "
                        f"{r['percent_agreement']} | {r['units']} | {r['coders']} |\n")
            f.write(f"\nIntervals: percentile bootstrap over units, {reps} resamples.\n")
            for note in undefined_notes:
                f.write(f"\n{note}.\n")
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=[csv_path, md_path], warnings=undefined_notes,
                            stats={"num_schemes": len(out_rows)})
