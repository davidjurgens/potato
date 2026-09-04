"""
Adjudication Exporter

The adjudicated label -- one resolved answer per item -- is the deliverable of
an adjudicated workflow, and until this existed no format reachable from
``/admin/api/export`` or ``potato export`` carried it. csv, jsonl and parquet
all read per-annotator state, so a researcher who exported and handed the
result over shipped the disagreements and not the resolution. The decisions were
on disk the whole time, in ``annotation_output/adjudication/decisions.json``,
reachable only through the separate ``python -m potato.adjudication_export`` CLI.

Two files, because they answer different questions:

``adjudicated.csv``      one row per (item, schema): the final value, who it came
                         from, and the adjudicator's confidence. This is the
                         dataset.
``adjudication_log.jsonl`` one record per decision, with notes, error taxonomy,
                         span decisions, guideline flags and time spent. This is
                         the audit trail.
"""

import csv
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _decisions_path(context: ExportContext) -> str:
    """Where the adjudication manager writes its decisions.

    ``context.output_dir`` first, because the export CLI has already resolved
    it against ``task_dir`` and made it absolute. The raw config value is
    usually relative -- "annotation_output" -- and reading that one resolved
    against the *caller's* working directory instead, so exporting a project
    from the repo root picked up whatever unrelated ``./annotation_output``
    happened to be sitting there and exported another study's decisions under
    this study's name.
    """
    output_dir = (context.output_dir
                  or context.config.get("output_annotation_dir") or "")
    return os.path.join(output_dir, "adjudication", "decisions.json")


def _load_decisions(context: ExportContext) -> List[dict]:
    path = _decisions_path(context)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("Could not read adjudication decisions at %s: %s", path, e)
        return []
    decisions = payload.get("decisions") if isinstance(payload, dict) else payload
    return decisions if isinstance(decisions, list) else []


def _flatten(value: Any) -> str:
    """One cell for one adjudicated answer.

    Composite schemes resolve to a whole allocation or a taxonomy path list, and
    those have no scalar reading -- json is the honest cell for them, and it
    round-trips. Scalars stay scalar so the common case reads as a plain value.
    """
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


class AdjudicationExporter(BaseExporter):
    format_name = "adjudication"
    description = ("Adjudicated final labels (CSV) plus the full decision log "
                   "(JSONL) with notes, sources and error taxonomy")
    file_extensions = [".csv", ".jsonl"]

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        if not (context.config.get("adjudication") or {}):
            return False, "Adjudication is not configured for this project"
        if not _load_decisions(context):
            return False, (
                "No adjudication decisions have been recorded yet "
                f"({_decisions_path(context)} is missing or empty)")
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        options = options or {}
        os.makedirs(output_path, exist_ok=True)

        decisions = _load_decisions(context)
        warnings: List[str] = []

        # Every schema any decision touched, in config order first so the
        # columns read down the task, then anything left over.
        schema_order: List[str] = []
        seen = set()
        for scheme in context.schemas:
            name = scheme.get("name")
            if isinstance(name, str) and name not in seen:
                seen.add(name)
                schema_order.append(name)
        for d in decisions:
            for name in (d.get("label_decisions") or {}):
                if name not in seen:
                    seen.add(name)
                    schema_order.append(name)

        rows: List[Dict[str, Any]] = []
        n_span_decisions = 0
        for d in decisions:
            iid = str(d.get("instance_id", ""))
            sources = d.get("source") or {}
            label_decisions = d.get("label_decisions") or {}
            n_span_decisions += len(d.get("span_decisions") or [])
            for name in schema_order:
                if name not in label_decisions:
                    continue
                rows.append({
                    "instance_id": iid,
                    "schema": name,
                    "value": _flatten(label_decisions[name]),
                    # "adjudicator" when they answered it themselves, an
                    # annotator id when they adopted that annotator's answer.
                    "source": sources.get(name, ""),
                    "adjudicator_id": d.get("adjudicator_id", ""),
                    "confidence": d.get("confidence", ""),
                    "timestamp": d.get("timestamp", ""),
                })

        # An item adjudicated with no schema resolved is worth saying out loud:
        # it is what a task with composite schemes used to produce for every
        # scheme the panel had no control for.
        resolved_items = {r["instance_id"] for r in rows}
        unresolved = [str(d.get("instance_id", "")) for d in decisions
                      if str(d.get("instance_id", "")) not in resolved_items]
        if unresolved:
            warnings.append(
                f"{len(unresolved)} adjudicated item(s) resolved no schema at "
                f"all: {', '.join(sorted(unresolved)[:5])}"
                + ("..." if len(unresolved) > 5 else ""))

        csv_path = os.path.join(output_path, "adjudicated.csv")
        fieldnames = ["instance_id", "schema", "value", "source",
                      "adjudicator_id", "confidence", "timestamp"]
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        log_path = os.path.join(output_path, "adjudication_log.jsonl")
        with open(log_path, "w", encoding="utf-8") as f:
            for d in decisions:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=[csv_path, log_path],
            warnings=warnings,
            stats={
                "n_decisions": len(decisions),
                "n_resolved_labels": len(rows),
                "n_items": len(resolved_items),
                "n_span_decisions": n_span_decisions,
                "n_schemas": len({r["schema"] for r in rows}),
            },
        )
