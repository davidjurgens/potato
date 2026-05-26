"""
Cases storage (universal).

SQLite-backed CRUD over `cases`, `case_attributes`, and
`case_documents` in `<task_dir>/project.sqlite`. A *case* groups
instances that belong to the same unit of analysis (an interview
participant, a respondent, a document set). Universal — usable in
standard annotation, solo mode, and QDA mode; QDA auto-detects cases
from `participant_id`/`respondent_id`/`case_id` in the item data.

No business rules here (the service layer owns get-or-create,
auto-detection, and attribute lifting). One instance belongs to at most
one case (PK on `project, instance_id`).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration

_CASES_MIGRATION = Migration(
    name="0001_cases",
    sql="""
    CREATE TABLE IF NOT EXISTS cases (
        id          TEXT PRIMARY KEY,
        project     TEXT NOT NULL,
        name        TEXT NOT NULL,
        created_by  TEXT NOT NULL,
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL,
        UNIQUE (project, name)
    );
    CREATE INDEX IF NOT EXISTS idx_cases_project ON cases (project);

    CREATE TABLE IF NOT EXISTS case_attributes (
        case_id  TEXT NOT NULL,
        key      TEXT NOT NULL,
        value    TEXT,
        PRIMARY KEY (case_id, key)
    );

    CREATE TABLE IF NOT EXISTS case_documents (
        project     TEXT NOT NULL,
        instance_id TEXT NOT NULL,
        case_id     TEXT NOT NULL,
        PRIMARY KEY (project, instance_id)
    );
    CREATE INDEX IF NOT EXISTS idx_case_docs_case
        ON case_documents (case_id);
    """,
)

register_migration(_CASES_MIGRATION)


def _db(task_dir: str):
    register_migration(_CASES_MIGRATION)
    return get_db(task_dir)


# ---- cases ---------------------------------------------------------------

def insert_case(
    task_dir: str, *, project: str, name: str, created_by: str,
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    cid = case_id or uuid.uuid4().hex
    now = time.time()
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO cases
           (id, project, name, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (cid, project, name, created_by, now, now),
    )
    conn.commit()
    return get_case(task_dir, cid)


def get_case(task_dir: str, case_id: str) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    return dict(row) if row else None


def find_case(
    task_dir: str, project: str, name: str
) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        "SELECT * FROM cases WHERE project = ? AND name = ?",
        (project, name),
    ).fetchone()
    return dict(row) if row else None


def list_cases(task_dir: str, project: str) -> List[Dict[str, Any]]:
    rows = _db(task_dir).execute(
        "SELECT * FROM cases WHERE project = ? ORDER BY name ASC",
        (project,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- attributes ----------------------------------------------------------

def set_attribute(
    task_dir: str, case_id: str, key: str, value: Optional[str]
) -> None:
    conn = _db(task_dir)
    conn.execute(
        """INSERT OR REPLACE INTO case_attributes (case_id, key, value)
           VALUES (?, ?, ?)""",
        (case_id, key, None if value is None else str(value)),
    )
    conn.commit()


def attributes(task_dir: str, case_id: str) -> Dict[str, Any]:
    rows = _db(task_dir).execute(
        "SELECT key, value FROM case_attributes WHERE case_id = ?",
        (case_id,),
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---- documents (instance <-> case) --------------------------------------

def assign_instance(
    task_dir: str, *, project: str, instance_id: str, case_id: str
) -> None:
    conn = _db(task_dir)
    conn.execute(
        """INSERT OR REPLACE INTO case_documents
           (project, instance_id, case_id) VALUES (?, ?, ?)""",
        (project, instance_id, case_id),
    )
    conn.commit()


def case_for_instance(
    task_dir: str, project: str, instance_id: str
) -> Optional[Dict[str, Any]]:
    row = _db(task_dir).execute(
        """SELECT c.* FROM case_documents d
           JOIN cases c ON c.id = d.case_id
           WHERE d.project = ? AND d.instance_id = ?""",
        (project, instance_id),
    ).fetchone()
    return dict(row) if row else None


def instances_for_case(task_dir: str, case_id: str) -> List[str]:
    rows = _db(task_dir).execute(
        "SELECT instance_id FROM case_documents WHERE case_id = ?",
        (case_id,),
    ).fetchall()
    return [r["instance_id"] for r in rows]
