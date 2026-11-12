"""
Storage for data produced by runtime phase pages.

One row per run of a runtime page, in the project's SQLite file
(`<task_dir>/project.sqlite`, via ``potato.persistence``). The trial data is
kept as one zlib-compressed JSON array: it is only ever read back whole, for
export.

Not in user_state.json: that file is rewritten in full on every save, and a
run with a few hundred trials would make every later save pay for it. Only a
short summary (run id, status, trial count) goes on the user state.
"""

from __future__ import annotations

import json
import time
import zlib
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_RUNTIME_MIGRATION = Migration(
    name="0002_runtime_runs",
    sql="""
    CREATE TABLE IF NOT EXISTS runtime_runs (
        run_id       TEXT PRIMARY KEY,
        project      TEXT NOT NULL,
        runtime      TEXT NOT NULL,          -- jspsych | osweb | psychojs | ...
        user_id      TEXT NOT NULL,
        phase        TEXT,
        page         TEXT NOT NULL,
        attempt      INTEGER NOT NULL DEFAULT 1,
        status       TEXT NOT NULL,          -- started | partial | complete
        started_at   REAL NOT NULL,
        finished_at  REAL,
        n_trials     INTEGER NOT NULL DEFAULT 0,
        conditions   TEXT,                   -- JSON {factor: level}
        interaction  TEXT,                   -- JSON runtime interaction data (blur/focus/fullscreen)
        data         BLOB                    -- zlib(JSON array of trial objects)
    );
    CREATE INDEX IF NOT EXISTS idx_runtime_user
        ON runtime_runs (project, user_id);
    CREATE INDEX IF NOT EXISTS idx_runtime_page
        ON runtime_runs (project, page);
    """,
)

register_migration(_RUNTIME_MIGRATION)


_upgraded: set = set()


def _db(task_dir: str):
    register_migration(_RUNTIME_MIGRATION)
    conn = get_db(task_dir)
    if task_dir not in _upgraded:
        _upgraded.add(task_dir)
        _copy_jspsych_runs(conn)
    return conn


def _copy_jspsych_runs(conn) -> None:
    """Runs stored by the jsPsych phase before it became a runtime phase
    (table ``jspsych_runs``) are copied into ``runtime_runs`` once."""
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='jspsych_runs'").fetchone():
            return
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO runtime_runs (run_id, project, runtime, user_id, phase, "
                "page, attempt, status, started_at, finished_at, n_trials, conditions, "
                "interaction, data) SELECT run_id, project, 'jspsych', user_id, phase, page, "
                "attempt, status, started_at, finished_at, n_trials, conditions, interaction, "
                "data FROM jspsych_runs")
    except Exception as e:  # pragma: no cover - a failed copy must not stop the study
        import logging
        logging.getLogger(__name__).warning("Could not copy old jsPsych runs: %s", e)


def _pack(trials: List[Dict[str, Any]]) -> bytes:
    return zlib.compress(json.dumps(trials, separators=(",", ":")).encode("utf-8"))


def _unpack(blob: Optional[bytes]) -> List[Dict[str, Any]]:
    if not blob:
        return []
    return json.loads(zlib.decompress(blob).decode("utf-8"))


def start_run(task_dir: str, *, project: str, runtime: str, user_id: str, phase: str,
              page: str, run_id: str, attempt: int,
              conditions: Optional[Dict[str, Any]] = None) -> None:
    """Record that a run was handed to the browser. Idempotent per run id."""
    conn = _db(task_dir)
    conn.execute(
        "INSERT OR IGNORE INTO runtime_runs (run_id, project, runtime, user_id, phase, page, "
        "attempt, status, started_at, conditions) VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?, ?)",
        (run_id, project, runtime, user_id, phase, page, attempt, time.time(),
         json.dumps(conditions or {})),
    )
    conn.commit()


def get_run(task_dir: str, run_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM runtime_runs WHERE run_id = ?", (run_id,)).fetchone()
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
        "UPDATE runtime_runs SET data = ?, n_trials = ?, status = ?, "
        "finished_at = CASE WHEN ? THEN ? ELSE finished_at END, "
        "interaction = COALESCE(?, interaction) "
        "WHERE run_id = ? AND (? = 1 OR status != 'complete')",
        (_pack(trials), len(trials), "complete" if complete else "partial",
         1 if complete else 0, time.time(),
         json.dumps(interaction) if interaction is not None else None, run_id,
         1 if complete else 0),
    )
    conn.commit()


def list_runs(task_dir: str, project: str, *, runtime: Optional[str] = None,
              with_data: bool = False) -> List[Dict[str, Any]]:
    if runtime:
        rows = _db(task_dir).execute(
            "SELECT * FROM runtime_runs WHERE project = ? AND runtime = ? "
            "ORDER BY user_id, started_at", (project, runtime)).fetchall()
    else:
        rows = _db(task_dir).execute(
            "SELECT * FROM runtime_runs WHERE project = ? ORDER BY user_id, started_at",
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
