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
that overlap count as partial agreement). Alpha comes from ``potato.server_utils.iaa.alpha``. The interval
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
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

LEVELS = {"radio": "nominal", "select": "nominal", "likert": "ordinal", "number": "interval",
          "slider": "interval", "vas": "interval", "multiselect": "masi",
          "hierarchical_multiselect": "masi"}
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


def _round(x):
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 3)


class ReliabilityExporter(BaseExporter):
    format_name = "reliability"
    description = "Intercoder reliability per question: Krippendorff's alpha with bootstrap CI"
    file_extensions = [".csv", ".md"]

    def _schemes(self, context):
        return [s for s in context.schemas or [] if s.get("annotation_type") in LEVELS]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No question type with a reliability coefficient (radio, likert, number, ...)"
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
        for scheme in self._schemes(context):
            name, level = scheme["name"], LEVELS[scheme["annotation_type"]]
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
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=[csv_path, md_path], stats={"num_schemes": len(out_rows)})
