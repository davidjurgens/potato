"""
Typing-session storage.

SQLite-backed persistence for keystroke logging, via the universal persistence
layer (`<task_dir>/project.sqlite`). One row per typing session: the queryable
summary features are denormalized into columns for the admin dashboard and the
detector, the full summary is kept as JSON, and the raw event stream is a single
zlib blob.

Why one row per session rather than one per keystroke: a 500-word response is
roughly 3,000 events, and the stream is only ever read back wholesale (to
recompute features or to replay). Packed, it costs under 2 bytes per event —
about 5 KB for a long response — so a row-per-session keeps the table small
enough to scan while a row-per-keystroke would put tens of millions of rows in
a researcher's project file for no query benefit.

Why not user_state.json: that file is fully re-serialized and atomically
rewritten on every annotation save (`user_state_management.py`), so putting
event streams in it would make every save quadratically more expensive as a
session grows. Only the compact summary goes there, via
`BehavioralData.typing_summaries`.

Why not the MySQL backend: `potato/database/connection.py` declares a
`behavioral_data` table, but `mysql_user_state.py` only ever deletes from it —
there is no write path — so it is not a viable target.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration
from potato.typing_dynamics import TypingEvent, TypingSummary, pack_events, unpack_events

logger = logging.getLogger(__name__)


_TYPING_MIGRATION = Migration(
    name="0001_typing_sessions",
    sql="""
    CREATE TABLE IF NOT EXISTS typing_sessions (
        id           TEXT PRIMARY KEY,
        project      TEXT NOT NULL,
        user_id      TEXT NOT NULL,
        instance_id  TEXT NOT NULL,
        phase        TEXT,
        page         TEXT,
        schema_name  TEXT NOT NULL,
        label_name   TEXT NOT NULL,
        started_at   REAL NOT NULL,
        ended_at     REAL NOT NULL,
        fidelity     TEXT NOT NULL,

        -- Denormalized summary columns. Duplicated from the `summary` JSON so
        -- the admin dashboard and the detector can aggregate in SQL instead of
        -- deserializing every row.
        keystrokes                INTEGER,
        final_chars               INTEGER,
        chars_typed               INTEGER,
        chars_deleted             INTEGER,
        active_ms                 INTEGER,
        iki_median_ms             REAL,
        iki_log_cv                REAL,
        pause_2s                  INTEGER,
        pause_10s                 INTEGER,
        pause_total_ms            INTEGER,
        bursts                    INTEGER,
        burst_mean_chars          REAL,
        revision_ratio            REAL,
        paste_events              INTEGER,
        pasted_chars              INTEGER,
        pasted_fraction           REAL,
        silent_insert_ratio       REAL,
        blur_total_ms             INTEGER,
        max_blur_before_insert_ms INTEGER,
        untrusted_events          INTEGER,
        virtual_keyboard          INTEGER,

        summary      TEXT NOT NULL,   -- full TypingSummary as JSON
        flags        TEXT,            -- detector verdict as JSON
        events       BLOB             -- packed stream; NULL at fidelity='summary'
    );
    CREATE INDEX IF NOT EXISTS idx_typing_instance
        ON typing_sessions (project, instance_id);
    CREATE INDEX IF NOT EXISTS idx_typing_user
        ON typing_sessions (project, user_id);
    CREATE INDEX IF NOT EXISTS idx_typing_field
        ON typing_sessions (project, schema_name, label_name);

    CREATE TABLE IF NOT EXISTS typing_calibration (
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
register_migration(_TYPING_MIGRATION)


def _db(task_dir: str):
    """Connection for the typing store, guaranteeing the migration is registered.

    register_migration is idempotent, so this is a no-op in normal operation. It
    makes the store robust when a test helper (clear_migrations) has wiped the
    process-global registry before the first get_db() for this task_dir.
    """
    register_migration(_TYPING_MIGRATION)
    return get_db(task_dir)


#: Summary attributes mirrored into their own columns, in insert order.
_SUMMARY_COLUMNS = [
    "keystrokes", "final_chars", "chars_typed", "chars_deleted", "active_ms",
    "iki_median_ms", "iki_log_cv", "pause_total_ms", "bursts",
    "burst_mean_chars", "revision_ratio", "paste_events", "pasted_chars",
    "pasted_fraction", "silent_insert_ratio", "blur_total_ms",
    "max_blur_before_insert_ms", "untrusted_events",
]


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    d["summary"] = json.loads(d["summary"]) if d.get("summary") else {}
    d["flags"] = json.loads(d["flags"]) if d.get("flags") else None
    d["virtual_keyboard"] = bool(d.get("virtual_keyboard"))
    # The packed blob is deliberately not decoded here — callers that want the
    # stream ask for it by id via load_events(), so listing many sessions stays
    # cheap.
    d.pop("events", None)
    return d


def record_session(
    task_dir: str,
    *,
    project: str,
    user_id: str,
    instance_id: str,
    schema_name: str,
    label_name: str,
    summary: TypingSummary,
    events: Optional[List[TypingEvent]] = None,
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    phase: Optional[str] = None,
    page: Optional[str] = None,
    fidelity: str = "events",
    flags: Optional[Dict[str, Any]] = None,
) -> str:
    """Insert one typing session and return its id.

    `events` is stored only when `fidelity` is `"events"`. At `"summary"`
    fidelity the stream is still transmitted and summarized, but nothing raw is
    persisted — which is the point of that setting.
    """
    session_id = uuid.uuid4().hex
    now = time.time()
    summary_dict = summary.to_dict()

    blob = pack_events(events) if (events and fidelity == "events") else None

    columns = [
        "id", "project", "user_id", "instance_id", "phase", "page",
        "schema_name", "label_name", "started_at", "ended_at", "fidelity",
        *_SUMMARY_COLUMNS,
        "pause_2s", "pause_10s", "virtual_keyboard",
        "summary", "flags", "events",
    ]
    values = [
        session_id, project, user_id, instance_id, phase, page,
        schema_name, label_name,
        started_at if started_at is not None else now,
        ended_at if ended_at is not None else now,
        fidelity,
        *[summary_dict.get(c) for c in _SUMMARY_COLUMNS],
        (summary.pause_counts or {}).get("2000", 0),
        (summary.pause_counts or {}).get("10000", 0),
        1 if summary.virtual_keyboard else 0,
        json.dumps(summary_dict),
        json.dumps(flags) if flags else None,
        blob,
    ]

    conn = _db(task_dir)
    conn.execute(
        f"INSERT INTO typing_sessions ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' * len(columns))})",
        values,
    )
    conn.commit()
    return session_id


def get_session(task_dir: str, session_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM typing_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def load_events(task_dir: str, session_id: str) -> List[TypingEvent]:
    """Decode one session's raw event stream. Empty when it was not stored."""
    row = _db(task_dir).execute(
        "SELECT events FROM typing_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row or row["events"] is None:
        return []
    return unpack_events(row["events"])


def sessions_for_instance(
    task_dir: str, project: str, instance_id: str,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Sessions on one instance, oldest first, optionally for a single user."""
    sql = ("SELECT * FROM typing_sessions "
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
        """SELECT * FROM typing_sessions
           WHERE project = ? AND user_id = ?
           ORDER BY started_at DESC LIMIT ?""",
        (project, user_id, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def aggregate_by_user(task_dir: str, project: str) -> List[Dict[str, Any]]:
    """Per-annotator writing-process rollup for the admin dashboard.

    Rates are normalized per 100 characters written rather than per session, so
    an annotator who writes a few long responses is comparable to one who writes
    many short ones.
    """
    rows = _db(task_dir).execute(
        """SELECT
             user_id,
             COUNT(*)                          AS sessions,
             COUNT(DISTINCT instance_id)       AS instances,
             SUM(keystrokes)                   AS keystrokes,
             SUM(final_chars)                  AS chars,
             SUM(chars_deleted)                AS chars_deleted,
             SUM(active_ms)                    AS active_ms,
             AVG(iki_median_ms)                AS iki_median_ms,
             AVG(iki_log_cv)                   AS iki_log_cv,
             SUM(pause_2s)                     AS pause_2s,
             SUM(pause_10s)                    AS pause_10s,
             AVG(revision_ratio)               AS revision_ratio,
             SUM(paste_events)                 AS paste_events,
             SUM(pasted_chars)                 AS pasted_chars,
             AVG(pasted_fraction)              AS mean_pasted_fraction,
             AVG(silent_insert_ratio)          AS mean_silent_insert_ratio,
             MAX(max_blur_before_insert_ms)    AS max_blur_before_insert_ms,
             SUM(untrusted_events)             AS untrusted_events,
             MAX(virtual_keyboard)             AS any_virtual_keyboard
           FROM typing_sessions
           WHERE project = ?
           GROUP BY user_id
           ORDER BY mean_pasted_fraction DESC""",
        (project,),
    ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        chars = d.get("chars") or 0
        per100 = (100.0 / chars) if chars else 0.0
        d["pause_2s_per_100_chars"] = (d.get("pause_2s") or 0) * per100
        d["pasted_char_fraction"] = (
            (d.get("pasted_chars") or 0) / chars if chars else 0.0
        )
        d["any_virtual_keyboard"] = bool(d.get("any_virtual_keyboard"))
        out.append(d)
    return out


def feature_matrix(
    task_dir: str, project: str, features: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Session-level feature rows, for calibration and supervised fitting.

    Returns the denormalized columns only. Callers needing the full feature set
    should read `summary` from `sessions_for_user`, or recompute from
    `load_events`.
    """
    cols = features or (_SUMMARY_COLUMNS + ["pause_2s", "pause_10s"])
    selected = ", ".join(["id", "user_id", "instance_id", "schema_name",
                          "label_name", "virtual_keyboard", *cols])
    rows = _db(task_dir).execute(
        f"SELECT {selected} FROM typing_sessions WHERE project = ?", (project,)
    ).fetchall()
    return [dict(r) for r in rows]


def count_sessions(task_dir: str, project: str) -> int:
    row = _db(task_dir).execute(
        "SELECT COUNT(*) AS n FROM typing_sessions WHERE project = ?", (project,)
    ).fetchone()
    return int(row["n"]) if row else 0


def delete_for_user(task_dir: str, project: str, user_id: str) -> int:
    """Remove a user's sessions. Supports data-deletion requests."""
    conn = _db(task_dir)
    cur = conn.execute(
        "DELETE FROM typing_sessions WHERE project = ? AND user_id = ?",
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
    """Persist per-project detector thresholds, replacing any previous fit."""
    conn = _db(task_dir)
    now = time.time()
    payload = json.dumps(detail) if detail else None
    for flag, value in thresholds.items():
        conn.execute(
            """INSERT INTO typing_calibration
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
        "SELECT flag, threshold FROM typing_calibration WHERE project = ?",
        (project,),
    ).fetchall()
    return {r["flag"]: r["threshold"] for r in rows}
