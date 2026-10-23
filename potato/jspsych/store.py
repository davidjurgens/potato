"""
Storage for data produced by embedded jsPsych timelines.

One row per run of a `type: jspsych` phase page, in the project's SQLite file
(`<task_dir>/project.sqlite`, via ``potato.persistence``). The trial data is
kept as one zlib-compressed JSON array: it is only ever read back whole, for
export.

Not in user_state.json: that file is rewritten in full on every save, and a
jsPsych run with a few hundred trials would make every later save pay for it.
Only a short summary (run id, status, trial count) goes on the user state.
"""

from __future__ import annotations

import json
import time
import zlib
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_JSPSYCH_MIGRATION = Migration(
    name="0001_jspsych_runs",
    sql="""
    CREATE TABLE IF NOT EXISTS jspsych_runs (
        run_id       TEXT PRIMARY KEY,
        project      TEXT NOT NULL,
        user_id      TEXT NOT NULL,
        phase        TEXT,
        page         TEXT NOT NULL,
        attempt      INTEGER NOT NULL DEFAULT 1,
        status       TEXT NOT NULL,          -- started | partial | complete
        started_at   REAL NOT NULL,
        finished_at  REAL,
        n_trials     INTEGER NOT NULL DEFAULT 0,
        conditions   TEXT,                   -- JSON {factor: level}
        interaction  TEXT,                   -- JSON jsPsych interaction data (blur/focus/fullscreen)
        data         BLOB                    -- zlib(JSON array of trial objects)
    );
    CREATE INDEX IF NOT EXISTS idx_jspsych_user
        ON jspsych_runs (project, user_id);
    CREATE INDEX IF NOT EXISTS idx_jspsych_page
        ON jspsych_runs (project, page);
    """,
)

register_migration(_JSPSYCH_MIGRATION)


def _db(task_dir: str):
    register_migration(_JSPSYCH_MIGRATION)
    return get_db(task_dir)


def _pack(trials: List[Dict[str, Any]]) -> bytes:
    return zlib.compress(json.dumps(trials, separators=(",", ":")).encode("utf-8"))


def _unpack(blob: Optional[bytes]) -> List[Dict[str, Any]]:
    if not blob:
        return []
    return json.loads(zlib.decompress(blob).decode("utf-8"))


def start_run(task_dir: str, *, project: str, user_id: str, phase: str, page: str,
              run_id: str, attempt: int, conditions: Optional[Dict[str, Any]] = None) -> None:
    """Record that a run was handed to the browser. Idempotent per run id."""
    conn = _db(task_dir)
    conn.execute(
        "INSERT OR IGNORE INTO jspsych_runs (run_id, project, user_id, phase, page, "
        "attempt, status, started_at, conditions) VALUES (?, ?, ?, ?, ?, ?, 'started', ?, ?)",
        (run_id, project, user_id, phase, page, attempt, time.time(),
         json.dumps(conditions or {})),
    )
    conn.commit()


def get_run(task_dir: str, run_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM jspsych_runs WHERE run_id = ?", (run_id,)).fetchone()
    return _row(row) if row else None


def save_trials(task_dir: str, run_id: str, trials: List[Dict[str, Any]], *,
                complete: bool, interaction: Optional[List[Dict[str, Any]]] = None) -> None:
    """Replace the run's trial data. ``complete`` marks the run finished.

    A finished run is never written back to partial: with ``save:
    incremental`` the last trial's POST can arrive after the finish, and
    without the guard it overwrote the complete data with a shorter list.
    """
    conn = _db(task_dir)
    conn.execute(
        "UPDATE jspsych_runs SET data = ?, n_trials = ?, status = ?, "
        "finished_at = CASE WHEN ? THEN ? ELSE finished_at END, "
        "interaction = COALESCE(?, interaction) "
        "WHERE run_id = ? AND (? = 1 OR status != 'complete')",
        (_pack(trials), len(trials), "complete" if complete else "partial",
         1 if complete else 0, time.time(),
         json.dumps(interaction) if interaction is not None else None, run_id,
         1 if complete else 0),
    )
    conn.commit()


def list_runs(task_dir: str, project: str, *, with_data: bool = False) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        "SELECT * FROM jspsych_runs WHERE project = ? ORDER BY user_id, started_at",
        (project,)).fetchall()
    return [_row(r, with_data=with_data) for r in rows]


def _row(row, with_data: bool = True) -> Dict[str, Any]:
    d = dict(row)
    d["conditions"] = json.loads(d["conditions"]) if d.get("conditions") else {}
    d["interaction"] = json.loads(d["interaction"]) if d.get("interaction") else []
    blob = d.pop("data", None)
    if with_data:
        d["trials"] = _unpack(blob)
    return d
