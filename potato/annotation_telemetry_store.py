"""
Annotation-telemetry storage.

SQLite-backed persistence for drawing telemetry, via the universal persistence
layer (``<task_dir>/project.sqlite``). One row per session: queryable features
are denormalized into columns for the admin dashboard, the full summary is kept
as JSON, and the raw event stream is a single zlib blob.

Why one row per session rather than one per event: a heavily annotated image is
a few hundred events, and the stream is only ever read back wholesale — to
recompute features when a definition changes, or to replay a session. A
row-per-event would put millions of rows in a researcher's project file for no
query benefit.

Why not ``user_state.json``: that file is fully re-serialized and atomically
rewritten on every annotation save, so putting event streams in it would make
every save progressively more expensive as a session grows. Only the compact
summary goes there, via ``BehavioralData``.

This mirrors :mod:`potato.typing_store` closely and deliberately — same table
shape, same accessor names, same reasoning — so the two behavioural subsystems
stay one thing to learn rather than two.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from potato.annotation_telemetry import (
    TelemetryEvent,
    TelemetrySummary,
    pack_events,
    unpack_events,
)
from potato.persistence import Migration, get_db, register_migration

logger = logging.getLogger(__name__)


_TELEMETRY_MIGRATION = Migration(
    name="0001_annotation_telemetry",
    sql="""
    CREATE TABLE IF NOT EXISTS annotation_telemetry (
        id           TEXT PRIMARY KEY,
        project      TEXT NOT NULL,
        user_id      TEXT NOT NULL,
        instance_id  TEXT NOT NULL,
        phase        TEXT,
        page         TEXT,
        schema_name  TEXT NOT NULL,
        started_at   REAL NOT NULL,
        ended_at     REAL NOT NULL,
        fidelity     TEXT NOT NULL,

        -- Denormalized summary columns. Duplicated from the `summary` JSON so
        -- the admin dashboard and calibration can aggregate in SQL instead of
        -- deserializing every row.
        events                       INTEGER,
        shapes_added                 INTEGER,
        shapes_from_ai               INTEGER,
        shapes_drawn                 INTEGER,
        shapes_edited                INTEGER,
        shapes_removed               INTEGER,
        strokes                      INTEGER,
        fills                        INTEGER,
        vertices_total               INTEGER,
        vertices_median              REAL,
        stroke_px_total              INTEGER,
        duration_ms                  INTEGER,
        active_ms                    INTEGER,
        idle_ms                      INTEGER,
        time_to_first_shape_ms       INTEGER,
        shape_interval_median_ms     REAL,
        shape_interval_min_ms        INTEGER,
        zoom_events                  INTEGER,
        pan_events                   INTEGER,
        max_zoom                     REAL,
        zoomed_ms                    INTEGER,
        zoomed_fraction              REAL,
        undo_count                   INTEGER,
        redo_count                   INTEGER,
        tool_switches                INTEGER,
        revision_ratio               REAL,
        ai_suggested                 INTEGER,
        ai_accepted                  INTEGER,
        ai_rejected                  INTEGER,
        ai_accept_latency_median_ms  REAL,
        ai_accept_latency_min_ms     INTEGER,
        ai_accepted_then_edited      INTEGER,
        ai_accept_rate               REAL,

        summary      TEXT NOT NULL,   -- full TelemetrySummary as JSON
        flags        TEXT,            -- screening verdict as JSON
        events_blob  BLOB             -- packed stream; NULL at fidelity='summary'
    );
    CREATE INDEX IF NOT EXISTS idx_telemetry_instance
        ON annotation_telemetry (project, instance_id);
    CREATE INDEX IF NOT EXISTS idx_telemetry_user
        ON annotation_telemetry (project, user_id);
    CREATE INDEX IF NOT EXISTS idx_telemetry_schema
        ON annotation_telemetry (project, schema_name);

    CREATE TABLE IF NOT EXISTS annotation_telemetry_calibration (
        project     TEXT NOT NULL,
        flag        TEXT NOT NULL,
        threshold   REAL NOT NULL,
        n_sessions  INTEGER NOT NULL,
        fitted_at   REAL NOT NULL,
        detail      TEXT,
        PRIMARY KEY (project, flag)
    );
    """,
)

# Registered at import so the tables exist on the first get_db() call.
register_migration(_TELEMETRY_MIGRATION)


def _db(task_dir: str):
    """Connection for the telemetry store, guaranteeing the migration is registered.

    register_migration is idempotent, so this is a no-op in normal operation. It
    makes the store robust when a test helper (clear_migrations) has wiped the
    process-global registry before the first get_db() for this task_dir.
    """
    register_migration(_TELEMETRY_MIGRATION)
    return get_db(task_dir)


#: Summary attributes mirrored into their own columns, in insert order. The
#: names match the column names exactly so the insert cannot drift from the
#: schema without a KeyError rather than a silent NULL.
_SUMMARY_COLUMNS = [
    "events", "shapes_added", "shapes_from_ai", "shapes_drawn",
    "shapes_edited", "shapes_removed", "strokes",
    "fills", "vertices_total", "vertices_median", "stroke_px_total",
    "duration_ms", "active_ms", "idle_ms", "time_to_first_shape_ms",
    "shape_interval_median_ms", "shape_interval_min_ms", "zoom_events",
    "pan_events", "max_zoom", "zoomed_ms", "zoomed_fraction", "undo_count",
    "redo_count", "tool_switches", "revision_ratio", "ai_suggested",
    "ai_accepted", "ai_rejected", "ai_accept_latency_median_ms",
    "ai_accept_latency_min_ms", "ai_accepted_then_edited", "ai_accept_rate",
]


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    d["summary"] = json.loads(d["summary"]) if d.get("summary") else {}
    d["flags"] = json.loads(d["flags"]) if d.get("flags") else None
    # The packed blob is deliberately not decoded here — callers that want the
    # stream ask for it by id via load_events(), so listing many sessions stays
    # cheap.
    d.pop("events_blob", None)
    return d


def record_session(
    task_dir: str,
    *,
    project: str,
    user_id: str,
    instance_id: str,
    schema_name: str,
    summary: TelemetrySummary,
    events: Optional[List[TelemetryEvent]] = None,
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    phase: Optional[str] = None,
    page: Optional[str] = None,
    fidelity: str = "events",
    flags: Optional[Dict[str, Any]] = None,
) -> str:
    """Insert one telemetry session and return its id.

    ``events`` is stored only when ``fidelity`` is ``"events"``. At
    ``"summary"`` fidelity the stream is still transmitted and summarized, but
    nothing raw is persisted — which is the point of that setting.
    """
    session_id = uuid.uuid4().hex
    now = time.time()
    summary_dict = summary.to_dict()

    blob = pack_events(events) if (events and fidelity == "events") else None

    columns = [
        "id", "project", "user_id", "instance_id", "phase", "page",
        "schema_name", "started_at", "ended_at", "fidelity",
        *_SUMMARY_COLUMNS,
        "summary", "flags", "events_blob",
    ]
    values = [
        session_id, project, user_id, instance_id, phase, page,
        schema_name,
        started_at if started_at is not None else now,
        ended_at if ended_at is not None else now,
        fidelity,
        *[summary_dict.get(c) for c in _SUMMARY_COLUMNS],
        json.dumps(summary_dict),
        json.dumps(flags) if flags else None,
        blob,
    ]

    conn = _db(task_dir)
    conn.execute(
        f"INSERT INTO annotation_telemetry ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        values,
    )
    conn.commit()
    return session_id


def get_session(task_dir: str, session_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM annotation_telemetry WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def load_events(task_dir: str, session_id: str) -> List[TelemetryEvent]:
    """Decode one session's raw event stream. Empty when it was not stored."""
    row = _db(task_dir).execute(
        "SELECT events_blob FROM annotation_telemetry WHERE id = ?", (session_id,)
    ).fetchone()
    if not row or row["events_blob"] is None:
        return []
    return unpack_events(row["events_blob"])


def sessions_for_instance(
    task_dir: str, project: str, instance_id: str,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Sessions on one instance, oldest first, optionally for a single user."""
    sql = ("SELECT * FROM annotation_telemetry "
           "WHERE project = ? AND instance_id = ?")
    params: List[Any] = [project, instance_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    sql += " ORDER BY started_at ASC"
    return [_row_to_dict(r) for r in _db(task_dir).execute(sql, params).fetchall()]


def sessions_for_user(
    task_dir: str, project: str, user_id: str, limit: int = 1000
) -> List[Dict[str, Any]]:
    """A user's sessions, newest first."""
    rows = _db(task_dir).execute(
        """SELECT * FROM annotation_telemetry
           WHERE project = ? AND user_id = ?
           ORDER BY started_at DESC LIMIT ?""",
        (project, user_id, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def aggregate_by_user(task_dir: str, project: str) -> List[Dict[str, Any]]:
    """Per-annotator drawing-process rollup for the admin dashboard.

    Ordered by AI-accept latency ascending with NULLs last, so the annotators
    worth looking at first are at the top and the ones who never used AI
    assistance do not crowd them out.
    """
    rows = _db(task_dir).execute(
        """SELECT
             user_id,
             COUNT(*)                            AS sessions,
             COUNT(DISTINCT instance_id)         AS instances,
             SUM(shapes_added)                   AS shapes,
             SUM(shapes_drawn)                   AS shapes_drawn,
             SUM(shapes_from_ai)                 AS shapes_from_ai,
             SUM(shapes_edited)                  AS shapes_edited,
             SUM(shapes_removed)                 AS shapes_removed,
             SUM(strokes)                        AS strokes,
             SUM(active_ms)                      AS active_ms,
             SUM(idle_ms)                        AS idle_ms,
             AVG(vertices_median)                AS vertices_median,
             AVG(shape_interval_median_ms)       AS shape_interval_median_ms,
             MIN(shape_interval_min_ms)          AS shape_interval_min_ms,
             AVG(revision_ratio)                 AS revision_ratio,
             SUM(undo_count)                     AS undo_count,
             MAX(max_zoom)                       AS max_zoom,
             AVG(zoomed_fraction)                AS zoomed_fraction,
             SUM(ai_suggested)                   AS ai_suggested,
             SUM(ai_accepted)                    AS ai_accepted,
             SUM(ai_rejected)                    AS ai_rejected,
             SUM(ai_accepted_then_edited)        AS ai_accepted_then_edited,
             AVG(ai_accept_latency_median_ms)    AS ai_accept_latency_median_ms,
             MIN(ai_accept_latency_min_ms)       AS ai_accept_latency_min_ms
           FROM annotation_telemetry
           WHERE project = ?
           GROUP BY user_id
           ORDER BY ai_accept_latency_median_ms IS NULL,
                    ai_accept_latency_median_ms ASC""",
        (project,),
    ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        suggested = d.get("ai_suggested") or 0
        accepted = d.get("ai_accepted") or 0
        d["ai_accept_rate"] = (accepted / suggested) if suggested else 0.0
        d["ai_accept_edited_rate"] = (
            (d.get("ai_accepted_then_edited") or 0) / accepted if accepted else 0.0
        )
        shapes = d.get("shapes") or 0
        active = d.get("active_ms") or 0
        # Per-shape rather than per-session, so an annotator with a few busy
        # images is comparable to one with many sparse ones.
        d["active_ms_per_shape"] = (active / shapes) if shapes else 0.0
        out.append(d)
    return out


def feature_matrix(
    task_dir: str, project: str, features: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Session-level feature rows, for calibration and analysis.

    Returns the denormalized columns only. Callers needing the full feature set
    should read ``summary`` from :func:`sessions_for_user`, or recompute from
    :func:`load_events`.
    """
    cols = features or list(_SUMMARY_COLUMNS)
    selected = ", ".join(["id", "user_id", "instance_id", "schema_name", *cols])
    rows = _db(task_dir).execute(
        f"SELECT {selected} FROM annotation_telemetry WHERE project = ?",
        (project,),
    ).fetchall()
    return [dict(r) for r in rows]


def count_sessions(task_dir: str, project: str) -> int:
    row = _db(task_dir).execute(
        "SELECT COUNT(*) AS n FROM annotation_telemetry WHERE project = ?",
        (project,),
    ).fetchone()
    return int(row["n"]) if row else 0


def delete_for_user(task_dir: str, project: str, user_id: str) -> int:
    """Remove a user's sessions. Supports data-deletion requests."""
    conn = _db(task_dir)
    cur = conn.execute(
        "DELETE FROM annotation_telemetry WHERE project = ? AND user_id = ?",
        (project, user_id),
    )
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------
# Calibration thresholds
# --------------------------------------------------------------------------


def save_calibration(
    task_dir: str, project: str, thresholds: Dict[str, float],
    n_sessions: int, detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist per-project screening thresholds, replacing any previous fit."""
    conn = _db(task_dir)
    now = time.time()
    payload = json.dumps(detail) if detail else None
    for flag, value in thresholds.items():
        conn.execute(
            """INSERT INTO annotation_telemetry_calibration
                   (project, flag, threshold, n_sessions, fitted_at, detail)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(project, flag) DO UPDATE SET
                   threshold = excluded.threshold,
                   n_sessions = excluded.n_sessions,
                   fitted_at = excluded.fitted_at,
                   detail = excluded.detail""",
            (project, flag, float(value), n_sessions, now, payload),
        )
    conn.commit()


def load_calibration(task_dir: str, project: str) -> Dict[str, float]:
    """Fitted thresholds for a project. Empty when calibration has not run."""
    rows = _db(task_dir).execute(
        "SELECT flag, threshold FROM annotation_telemetry_calibration "
        "WHERE project = ?",
        (project,),
    ).fetchall()
    return {r["flag"]: r["threshold"] for r in rows}


def calibrate(task_dir: str, project: str, percentile: float = 5.0) -> Dict[str, float]:
    """Fit and persist thresholds from this project's own sessions.

    Returns the fitted thresholds, or ``{}`` when there is not enough data —
    see :func:`potato.annotation_telemetry.calibrate_thresholds` for why a
    threshold fitted on a handful of sessions is worse than the default.
    """
    from potato.annotation_telemetry import calibrate_thresholds

    rows = feature_matrix(task_dir, project)
    fitted = calibrate_thresholds(rows, percentile=percentile)
    if fitted:
        save_calibration(task_dir, project, fitted, len(rows),
                         detail={"percentile": percentile})
    return fitted
