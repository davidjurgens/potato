"""
Annotation Telemetry Exporter

Exports raw content-blind drawing event streams for offline annotation-process
analysis. Like :mod:`potato.export.keystroke_exporter`, this reads the project's
SQLite database rather than ``user_state.json``, because the streams are too
large to live in the user state (see potato/annotation_telemetry_store.py).

Output files:
    annotation_sessions.parquet - one row per drawing session, with its features
    annotation_events.parquet   - one row per interaction (the long form)

Falls back to JSONL when pyarrow is unavailable.

What is in the stream: a timestamp, an action (shape committed / edited /
removed, stroke, fill, zoom, pan, undo, AI accept), a geometry kind, and one
integer of context. What is not in it: coordinates. A stream reconstructs how an
annotation was produced; it does not reconstruct the annotation.

Because these are behavioural measurements of identifiable annotators, exporting
them is deliberately not part of the default annotation export. Read
``docs/administration/annotation_telemetry.md`` before distributing them.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseExporter, ExportContext, ExportResult

logger = logging.getLogger(__name__)


def _check_pyarrow():
    """Try to import pyarrow and return (pa, pq) or raise ImportError."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    return pa, pq


SESSION_COLUMNS = [
    "session_id", "user_id", "instance_id", "phase", "page", "schema_name",
    "started_at", "ended_at", "fidelity",
    "events", "shapes_added", "shapes_from_ai", "shapes_drawn",
    "shapes_edited", "shapes_removed", "strokes",
    "fills", "vertices_total", "vertices_median", "stroke_px_total",
    "duration_ms", "active_ms", "idle_ms", "time_to_first_shape_ms",
    "shape_interval_median_ms", "shape_interval_min_ms", "zoom_events",
    "pan_events", "max_zoom", "zoomed_ms", "zoomed_fraction", "undo_count",
    "redo_count", "tool_switches", "revision_ratio", "ai_suggested",
    "ai_accepted", "ai_rejected", "ai_accept_latency_median_ms",
    "ai_accept_latency_min_ms", "ai_accepted_then_edited", "ai_accept_rate",
    "flags",
]

EVENT_COLUMNS = [
    "session_id", "user_id", "instance_id", "schema_name",
    "event_index", "t_ms", "action", "shape", "value", "suggestion_id", "tool",
]


class AnnotationTelemetryExporter(BaseExporter):
    """Exports drawing sessions and their raw event streams."""

    format_name = "annotation_telemetry"
    description = (
        "Content-blind drawing event streams and annotation-process features "
        "for labelling-quality analysis"
    )
    file_extensions = [".parquet", ".jsonl"]

    def _task_dir_and_project(self, context: ExportContext) -> Tuple[str, str]:
        config = context.config or {}
        task_dir = config.get("task_dir") or "."
        project = config.get("annotation_task_name") or "potato"
        return task_dir, project

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        config = context.config or {}
        at = config.get("annotation_telemetry") or {}
        if not at.get("enabled"):
            return False, (
                "annotation_telemetry is not enabled for this project, so there "
                "are no drawing sessions to export."
            )
        try:
            from potato import annotation_telemetry_store as store
            task_dir, project = self._task_dir_and_project(context)
            if store.count_sessions(task_dir, project) == 0:
                return False, "No drawing sessions recorded yet."
        except Exception as e:
            return False, f"Could not open the telemetry session store: {e}"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato import annotation_telemetry_store as store

        options = options or {}
        include_events = options.get("include_events", True)
        if isinstance(include_events, str):
            include_events = include_events.lower() not in ("false", "0", "no")

        task_dir, project = self._task_dir_and_project(context)
        files_written: List[str] = []
        warnings: List[str] = []

        try:
            rows = store.feature_matrix(task_dir, project)
        except Exception as e:
            return ExportResult(
                success=False, format_name=self.format_name,
                errors=[f"Could not read telemetry sessions: {e}"])

        # feature_matrix returns the denormalized columns; re-read the full rows
        # so phase/page and the screening verdict come along too.
        session_rows: List[Dict[str, Any]] = []
        event_rows: List[Dict[str, Any]] = []
        users = {r["user_id"] for r in rows}

        for user_id in sorted(users):
            for s in store.sessions_for_user(task_dir, project, user_id):
                verdict = s.get("flags") or {}
                row = {
                    "session_id": s["id"],
                    "user_id": s["user_id"],
                    "instance_id": s["instance_id"],
                    "phase": s.get("phase") or "",
                    "page": s.get("page") or "",
                    "schema_name": s["schema_name"],
                    "started_at": s.get("started_at"),
                    "ended_at": s.get("ended_at"),
                    "fidelity": s.get("fidelity"),
                    "flags": "|".join(verdict.get("flags") or []),
                }
                # Every remaining column is a summary feature with the same name
                # in the store, so copying by name keeps this list and the schema
                # from drifting apart.
                for column in SESSION_COLUMNS:
                    if column not in row:
                        row[column] = s.get(column)
                session_rows.append(row)

                if not include_events:
                    continue
                try:
                    events = store.load_events(task_dir, s["id"])
                except Exception as e:
                    warnings.append(
                        f"Could not decode events for session {s['id']}: {e}")
                    continue
                for i, e in enumerate(events):
                    meta = e.meta or {}
                    event_rows.append({
                        "session_id": s["id"],
                        "user_id": s["user_id"],
                        "instance_id": s["instance_id"],
                        "schema_name": s["schema_name"],
                        "event_index": i,
                        "t_ms": e.t_ms,
                        "action": e.action,
                        "shape": e.shape,
                        "value": e.value,
                        # Promoted out of meta because pairing suggest to accept
                        # is the single most common thing anyone will do with
                        # this table, and digging it out of a JSON blob per row
                        # would make that a chore.
                        "suggestion_id": meta.get("sid") or "",
                        "tool": meta.get("tool") or "",
                    })

        if not session_rows:
            return ExportResult(
                success=False, format_name=self.format_name,
                errors=["No drawing sessions found to export."])

        if include_events and not event_rows:
            warnings.append(
                "No raw event streams were stored (fidelity is 'summary' or "
                "store_events is false); exported session features only."
            )

        try:
            pa, pq = _check_pyarrow()
            use_parquet = True
        except ImportError:
            use_parquet = False
            warnings.append(
                "pyarrow not installed; wrote JSONL instead of Parquet. "
                "Install with: pip install pyarrow>=12.0.0"
            )

        def write_table(rows_: List[Dict[str, Any]], columns: List[str],
                        stem: str) -> str:
            if use_parquet:
                path = os.path.join(output_path, f"{stem}.parquet")
                table = pa.table({c: [r.get(c) for r in rows_] for c in columns})
                pq.write_table(table, path, compression="snappy")
            else:
                path = os.path.join(output_path, f"{stem}.jsonl")
                with open(path, "w", encoding="utf-8") as f:
                    for r in rows_:
                        f.write(json.dumps({c: r.get(c) for c in columns},
                                           ensure_ascii=False) + "\n")
            return path

        os.makedirs(output_path, exist_ok=True)
        files_written.append(
            write_table(session_rows, SESSION_COLUMNS, "annotation_sessions"))
        if event_rows:
            files_written.append(
                write_table(event_rows, EVENT_COLUMNS, "annotation_events"))

        return ExportResult(
            success=True,
            format_name=self.format_name,
            files_written=files_written,
            warnings=warnings,
            stats={
                "num_sessions": len(session_rows),
                "num_events": len(event_rows),
                "num_users": len(users),
                "num_flagged": sum(1 for r in session_rows if r["flags"]),
            },
        )
