"""
Peak Table Exporter

For ``peak_picking`` schemes on a ``spectrum`` display. Writes one row per
picked peak, integrated region and rejected suggestion:

    peaks.csv / peaks.jsonl
        user_id, instance_id, schema, kind (peak | region | rejected),
        x, y, width, from, to, integral, relative, source (auto | manual),
        label, then one column per configured peak/region field

``source`` is ``auto`` for a suggested peak the annotator accepted and
``manual`` for one they added; ``rejected`` rows are suggestions they turned
down (x only). ``relative`` is a region's integral over the first region's
in the same answer. ``label`` is the item's ``label`` (set by a
``viewer_selection`` scheme) or its fields joined with " / ".

Options: ``{"format": "csv" | "jsonl" | "both"}`` (default both).
"""

from __future__ import annotations

import csv
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

FIXED_COLUMNS = ["user_id", "instance_id", "schema", "kind", "x", "y", "width", "from", "to",
                 "integral", "relative", "source", "label"]


def _decode(labels: Any, schema: str) -> Optional[dict]:
    if not isinstance(labels, dict):
        return None
    raw = labels.get(schema)
    if raw is None and len(labels) == 1:
        raw = next(iter(labels.values()))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def rows_for_answer(answer: Dict[str, Any], base: Dict[str, Any],
                    field_columns: Dict[str, str]) -> List[Dict[str, Any]]:
    """Rows for one stored peak_picking answer (see the module docstring)."""
    items = answer.get("items") if isinstance(answer.get("items"), list) else []
    regions = [it for it in items if isinstance(it, dict) and it.get("kind") == "region"]
    first = _num(regions[0].get("integral")) if regions else None
    rows = []
    for it in items:
        if not isinstance(it, dict) or it.get("kind") not in ("peak", "region"):
            continue
        fields = it.get("fields") if isinstance(it.get("fields"), dict) else {}
        label = it.get("label") if isinstance(it.get("label"), str) else \
            " / ".join(str(v) for v in fields.values() if v not in (None, ""))
        row = {**base, "kind": it["kind"], "label": label}
        if it["kind"] == "peak":
            row.update({"x": _num(it.get("x")), "y": _num(it.get("y")),
                        "width": _num(it.get("width")),
                        "source": it.get("source") if it.get("source") in ("auto", "manual") else "manual"})
        else:
            integral = _num(it.get("integral"))
            row.update({"from": _num(it.get("from")), "to": _num(it.get("to")), "integral": integral,
                        "relative": round(integral / first, 6) if integral is not None and first else None,
                        "source": "manual"})
        for name, column in field_columns.items():
            if name in fields:
                row[column] = fields[name]
        rows.append(row)
    for x in answer.get("rejected") or []:
        if _num(x) is not None:
            rows.append({**base, "kind": "rejected", "x": x, "source": "auto"})
    return rows


class PeakTableExporter(BaseExporter):
    format_name = "peak_table"
    description = "Spectrum peak picking: one row per peak, integral and rejected suggestion (CSV, JSONL)"
    file_extensions = [".csv", ".jsonl"]

    def _schemes(self, context: ExportContext) -> Dict[str, dict]:
        return {s["name"]: s for s in context.schemas or []
                if s.get("annotation_type") == "peak_picking"}

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not self._schemes(context):
            return False, "No peak_picking scheme in this project"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.server_utils.schemas.peak_picking import fields_of
        fmt = str((options or {}).get("format", "both")).lower()
        if fmt not in ("csv", "jsonl", "both"):
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[f"format must be csv, jsonl or both, not '{fmt}'"])
        schemes = self._schemes(context)
        field_columns: Dict[str, str] = {}
        for scheme in schemes.values():
            for f in fields_of(scheme, "peak_fields") + fields_of(scheme, "region_fields"):
                name = f["name"]
                field_columns.setdefault(name, f"field_{name}" if name in FIXED_COLUMNS else name)
        rows: List[Dict[str, Any]] = []
        for ann in context.annotations:
            uid, iid = str(ann.get("user_id", "")), str(ann.get("instance_id", ""))
            for name in schemes:
                answer = _decode((ann.get("labels") or {}).get(name), name)
                if not answer:
                    continue
                rows.extend(rows_for_answer(answer, {"user_id": uid, "instance_id": iid, "schema": name},
                                            field_columns))
        if not rows:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No peak_picking answers to export: no annotator has "
                                        "picked a peak, integrated a region or rejected a suggestion"])
        os.makedirs(output_path, exist_ok=True)
        columns = FIXED_COLUMNS + list(dict.fromkeys(field_columns.values()))
        files: List[str] = []
        if fmt in ("csv", "both"):
            path = os.path.join(output_path, "peaks.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                w.writeheader()
                for r in rows:
                    w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in columns})
            files.append(path)
        if fmt in ("jsonl", "both"):
            path = os.path.join(output_path, "peaks.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps({k: r[k] for k in columns if r.get(k) is not None},
                                       ensure_ascii=False) + "\n")
            files.append(path)
        kinds = [r["kind"] for r in rows]
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            stats={"peaks": kinds.count("peak"), "regions": kinds.count("region"),
                                   "rejected": kinds.count("rejected"),
                                   "accepted_suggestions": sum(1 for r in rows if r["kind"] == "peak"
                                                               and r.get("source") == "auto")})
