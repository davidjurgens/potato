"""
Keystroke Exporter

Exports raw content-blind keystroke event streams for offline writing-process
analysis. This is the only exporter that reaches into the project's SQLite
database rather than reading `user_state.json`, because the streams are far too
large to live in the user state (see potato/typing_store.py).

Output files:
    keystroke_sessions.parquet - one row per typing session, with its features
    keystroke_events.parquet   - one row per keystroke event (the long form)

Falls back to JSONL when pyarrow is unavailable.

What is in the stream: a timestamp, the input type (typed / pasted / dropped /
IME / undo), a key *class* (letter, digit, punct, space, backspace, nav), the
caret position, and the change in field length. What is not in it: the
characters. A stream reconstructs the writing process; it does not reconstruct
the text.

Because these are behavioural measurements of identifiable annotators, exporting
them is deliberately not part of the default annotation export. Read
``docs/advanced/keystroke_logging.md`` before distributing them.
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
    "session_id", "user_id", "instance_id", "phase", "page",
    "schema_name", "label_name", "started_at", "ended_at", "fidelity",
    "keystrokes", "final_chars", "chars_typed", "chars_deleted", "active_ms",
    "iki_median_ms", "iki_log_cv", "pause_2s", "pause_10s", "pause_total_ms",
    "bursts", "burst_mean_chars", "revision_ratio", "paste_events",
    "pasted_chars", "pasted_fraction", "silent_insert_ratio", "blur_total_ms",
    "max_blur_before_insert_ms", "untrusted_events", "virtual_keyboard",
    "verdict_level", "flags",
]

EVENT_COLUMNS = [
    "session_id", "user_id", "instance_id", "schema_name", "label_name",
    "event_index", "t_ms", "input_type", "key_class", "pos", "delta",
    "paste_source", "blur_ms", "is_trusted",
]


class KeystrokeExporter(BaseExporter):
    """Exports keystroke sessions and their raw event streams."""

    format_name = "keystrokes"
    description = (
        "Content-blind keystroke event streams and typing-dynamics features "
        "for writing-process analysis"
    )
    file_extensions = [".parquet", ".jsonl"]

    def _task_dir_and_project(self, context: ExportContext) -> Tuple[str, str]:
        config = context.config or {}
        task_dir = config.get("task_dir") or "."
        project = config.get("annotation_task_name") or "potato"
        return task_dir, project

    def can_export(self, context: ExportContext) -> Tuple[bool, str]:
        config = context.config or {}
        ks = config.get("keystroke_logging") or {}
        if not ks.get("enabled"):
            return False, (
                "keystroke_logging is not enabled for this project, so there are "
                "no typing sessions to export."
            )
        try:
            from potato import typing_store
            task_dir, project = self._task_dir_and_project(context)
            if typing_store.count_sessions(task_dir, project) == 0:
                return False, "No keystroke sessions recorded yet."
        except Exception as e:
            return False, f"Could not open the typing session store: {e}"
        return True, ""

    def export(self, context: ExportContext, output_path: str,
               options: Optional[dict] = None) -> ExportResult:
        from potato import typing_store
        from potato.typing_dynamics import unpack_events

        options = options or {}
        include_events = options.get("include_events", True)
        if isinstance(include_events, str):
            include_events = include_events.lower() not in ("false", "0", "no")

        task_dir, project = self._task_dir_and_project(context)
        files_written: List[str] = []
        warnings: List[str] = []

        try:
            rows = typing_store.feature_matrix(task_dir, project)
        except Exception as e:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=[f"Could not read typing sessions: {e}"])

        # feature_matrix returns the denormalized columns; re-read the full rows
        # so phase/page and the detector verdict come along too.
        session_rows: List[Dict[str, Any]] = []
        event_rows: List[Dict[str, Any]] = []
        users = {r["user_id"] for r in rows}

        for user_id in sorted(users):
            for s in typing_store.sessions_for_user(task_dir, project, user_id):
                summary = s.get("summary") or {}
                pauses = summary.get("pause_counts") or {}
                verdict = s.get("flags") or {}
                session_rows.append({
                    "session_id": s["id"],
                    "user_id": s["user_id"],
                    "instance_id": s["instance_id"],
                    "phase": s.get("phase") or "",
                    "page": s.get("page") or "",
                    "schema_name": s["schema_name"],
                    "label_name": s["label_name"],
                    "started_at": s.get("started_at"),
                    "ended_at": s.get("ended_at"),
                    "fidelity": s.get("fidelity"),
                    "keystrokes": s.get("keystrokes") or 0,
                    "final_chars": s.get("final_chars") or 0,
                    "chars_typed": s.get("chars_typed") or 0,
                    "chars_deleted": s.get("chars_deleted") or 0,
                    "active_ms": s.get("active_ms") or 0,
                    "iki_median_ms": s.get("iki_median_ms") or 0.0,
                    "iki_log_cv": s.get("iki_log_cv") or 0.0,
                    "pause_2s": pauses.get("2000", 0),
                    "pause_10s": pauses.get("10000", 0),
                    "pause_total_ms": s.get("pause_total_ms") or 0,
                    "bursts": s.get("bursts") or 0,
                    "burst_mean_chars": s.get("burst_mean_chars") or 0.0,
                    "revision_ratio": s.get("revision_ratio") or 0.0,
                    "paste_events": s.get("paste_events") or 0,
                    "pasted_chars": s.get("pasted_chars") or 0,
                    "pasted_fraction": s.get("pasted_fraction") or 0.0,
                    "silent_insert_ratio": s.get("silent_insert_ratio") or 0.0,
                    "blur_total_ms": s.get("blur_total_ms") or 0,
                    "max_blur_before_insert_ms": s.get("max_blur_before_insert_ms") or 0,
                    "untrusted_events": s.get("untrusted_events") or 0,
                    "virtual_keyboard": int(bool(s.get("virtual_keyboard"))),
                    "verdict_level": verdict.get("level", ""),
                    "flags": "|".join(verdict.get("flag_names") or []),
                })

                if not include_events:
                    continue
                try:
                    events = typing_store.load_events(task_dir, s["id"])
                except Exception as e:
                    warnings.append(f"Could not decode events for session {s['id']}: {e}")
                    continue
                for i, e in enumerate(events):
                    meta = e.meta or {}
                    event_rows.append({
                        "session_id": s["id"],
                        "user_id": s["user_id"],
                        "instance_id": s["instance_id"],
                        "schema_name": s["schema_name"],
                        "label_name": s["label_name"],
                        "event_index": i,
                        "t_ms": e.t_ms,
                        "input_type": e.input_type,
                        "key_class": e.key_class,
                        "pos": e.pos,
                        "delta": e.delta,
                        "paste_source": meta.get("paste_source") or "",
                        "blur_ms": meta.get("blur_ms") or 0,
                        "is_trusted": int(meta.get("is_trusted", True) is not False),
                    })

        if not session_rows:
            return ExportResult(success=False, format_name=self.format_name,
                                errors=["No keystroke sessions found to export."])

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
            write_table(session_rows, SESSION_COLUMNS, "keystroke_sessions"))
        if event_rows:
            files_written.append(
                write_table(event_rows, EVENT_COLUMNS, "keystroke_events"))

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
