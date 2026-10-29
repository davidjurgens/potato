"""
Exporters for ``interval_label`` answers (labels on a ``time_series`` signal).

``interval_label`` (format name)
    ``intervals.csv`` and ``intervals.jsonl``: one row per labelled interval
    or point event, with ``user_id, instance_id, schema, kind, start, end,
    duration, label, channel, source``. A point event has ``kind: event``,
    ``start == end`` and duration 0. Times are seconds from the start of the
    recording (or the recording's own time unit for CSV/Parquet data).

``bids_events`` (format name)
    One BIDS ``events.tsv`` per annotator and item, at
    ``<output>/<user>/<instance>_events.tsv`` (file names made safe), with the
    columns ``onset, duration, trial_type, channel``, plus one
    ``events.json`` sidecar per scheme describing them. Use one per scheme
    when a project has several: the scheme name goes into the folder
    (``<output>/<scheme>/<user>/...``) when there is more than one.

The generic CSV/JSONL exports also carry the answer, as one JSON cell per
scheme; these two give one row per interval instead.
"""

from __future__ import annotations

import csv
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

COLUMNS = ["user_id", "instance_id", "schema", "kind", "start", "end", "duration",
           "label", "channel", "source"]


def _schemes(context: ExportContext) -> Dict[str, dict]:
    return {s["name"]: s for s in context.schemas or []
            if s.get("annotation_type") == "interval_label"}


def decode_answer(labels: Any, schema: str) -> Optional[Dict[str, List[dict]]]:
    """The stored ``{"intervals", "events"}`` for one scheme, or None."""
    from potato.science.signals import normalize_annotations
    if not isinstance(labels, dict):
        return None
    raw = labels.get(schema)
    # {label_name: stored}, unwrapped unless it already is the answer. Tested
    # on the value types: a scheme named "events" stores {"events": "<json>"}.
    is_answer = isinstance(raw, dict) and (isinstance(raw.get("intervals"), list)
                                           or isinstance(raw.get("events"), list))
    if isinstance(raw, dict) and not is_answer and schema in raw:
        raw = raw[schema]
    elif isinstance(raw, dict) and not is_answer and len(raw) == 1:
        raw = next(iter(raw.values()))
    if isinstance(raw, str):
        if not raw.strip():
            return None
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if raw is None:
        return None
    try:
        return normalize_annotations(raw, strict=False)
    except ValueError:
        return None


def _rows(context: ExportContext) -> Tuple[List[Dict[str, Any]], Dict[Tuple[str, str, str], dict]]:
    rows: List[Dict[str, Any]] = []
    answers: Dict[Tuple[str, str, str], dict] = {}
    names = _schemes(context)
    for ann in context.annotations:
        uid, iid = str(ann.get("user_id", "")), str(ann.get("instance_id", ""))
        for name in names:
            answer = decode_answer(ann.get("labels") or {}, name)
            if not answer or not (answer["intervals"] or answer["events"]):
                continue
            answers[(name, uid, iid)] = answer
            for iv in answer["intervals"]:
                rows.append({"user_id": uid, "instance_id": iid, "schema": name, "kind": "interval",
                             "start": iv["start"], "end": iv["end"],
                             "duration": round(iv["end"] - iv["start"], 6), "label": iv["label"],
                             "channel": iv.get("channel") or "", "source": iv.get("source", "annotator")})
            for ev in answer["events"]:
                rows.append({"user_id": uid, "instance_id": iid, "schema": name, "kind": "event",
                             "start": ev["time"], "end": ev["time"], "duration": 0,
                             "label": ev["label"], "channel": ev.get("channel") or "",
                             "source": ev.get("source", "annotator")})
    rows.sort(key=lambda r: (r["schema"], r["user_id"], r["instance_id"], r["start"]))
    return rows, answers


class IntervalLabelExporter(BaseExporter):
    format_name = "interval_label"
    description = "Signal labels: one CSV/JSONL row per interval or point event"
    file_extensions = [".csv", ".jsonl"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not _schemes(context):
            return False, "No interval_label scheme in this project"
        if not context.annotations:
            return False, "No annotations to export"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        rows, _answers = _rows(context)
        if not rows:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No interval_label answers to export"])
        os.makedirs(output_path, exist_ok=True)
        csv_path = os.path.join(output_path, "intervals.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        jsonl_path = os.path.join(output_path, "intervals.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for r in rows:
                r = dict(r)
                r["channel"] = r["channel"] or None
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return ExportResult(success=True, format_name=self.format_name,
                            files_written=[csv_path, jsonl_path],
                            stats={"num_rows": len(rows),
                                   "num_intervals": sum(r["kind"] == "interval" for r in rows),
                                   "num_events": sum(r["kind"] == "event" for r in rows)})


def _safe(name: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._")
    return out or "item"


class BIDSEventsExporter(BaseExporter):
    format_name = "bids_events"
    description = "Signal labels as BIDS events.tsv files (onset, duration, trial_type, channel)"
    file_extensions = [".tsv", ".json"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        return IntervalLabelExporter().can_export(context)

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato.science.converters.bids_events import dumps_sidecar, write_bids_events
        from potato.server_utils.schemas.interval_label import labels_of
        _rows_, answers = _rows(context)
        if not answers:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No interval_label answers to export"])
        schemes = _schemes(context)
        several = len({k[0] for k in answers}) > 1
        files: List[str] = []
        os.makedirs(output_path, exist_ok=True)
        for name in sorted({k[0] for k in answers}):
            base = os.path.join(output_path, _safe(name)) if several else output_path
            os.makedirs(base, exist_ok=True)
            levels = {lab["name"]: (lab["tooltip"] or lab["name"]) for lab in labels_of(schemes[name])}
            for (_n, _u, _i), a in answers.items():
                if _n == name:
                    for x in a["intervals"] + a["events"]:
                        levels.setdefault(x["label"], x["label"])
            side = os.path.join(base, "events.json")
            with open(side, "w", encoding="utf-8") as f:
                f.write(dumps_sidecar(levels))
            files.append(side)
        for (name, uid, iid), answer in sorted(answers.items()):
            base = os.path.join(output_path, _safe(name)) if several else output_path
            folder = os.path.join(base, _safe(uid))
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{_safe(iid)}_events.tsv")
            write_bids_events(answer, path)
            files.append(path)
        return ExportResult(success=True, format_name=self.format_name, files_written=files,
                            stats={"num_files": len(answers)})
