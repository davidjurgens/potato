"""
Agent-chat transcript storage.

The conversation an annotator has with an ``agent_proxy`` agent through an
``interactive_chat`` display, kept per (user, instance) in the project's SQLite
database (``<task_dir>/project.sqlite``) via the universal persistence layer.

Why not the item: ``/agent_chat/finish`` used to write the transcript into the
shared item's in-memory data. Every other annotator assigned that item was then
shown that conversation instead of a chat panel of their own, and since item
data is rebuilt from the data files at boot, the transcript was gone after a
restart and never reached an export.

Why not user_state.json: that file is re-serialized and rewritten in full on
every annotation save (``user_state_management.py``). A chat runs to
``sandbox.max_steps`` turns, and a coding-agent proxy's turns carry tool output
and diffs, so keeping transcripts there would make every later save of that
annotator's state pay for them. The same reasoning put keystroke streams in
``typing_store`` and runtime trials in ``runtimes/store``.

Kept import-light (no proxy modules) so the export loader can read it without
pulling in the agent proxies.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from potato.persistence import Migration, get_db, register_migration


_MIGRATION = Migration(
    name="0001_agent_chat_transcripts",
    sql="""
    CREATE TABLE IF NOT EXISTS agent_chat_transcripts (
        project      TEXT NOT NULL,
        user_id      TEXT NOT NULL,
        instance_id  TEXT NOT NULL,
        field_key    TEXT NOT NULL,
        proxy_type   TEXT,
        step_count   INTEGER NOT NULL DEFAULT 0,
        started_at   REAL,
        finished_at  REAL NOT NULL,
        conversation TEXT NOT NULL,   -- JSON list of {speaker, text, timestamp}
        PRIMARY KEY (project, user_id, instance_id)
    );
    CREATE INDEX IF NOT EXISTS idx_agent_chat_instance
        ON agent_chat_transcripts (project, instance_id);
    """,
)

register_migration(_MIGRATION)


def _db(task_dir: str):
    # Idempotent; survives a test helper having cleared the global registry.
    register_migration(_MIGRATION)
    return get_db(task_dir)


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["conversation"] = json.loads(d.get("conversation") or "[]")
    except (TypeError, ValueError):
        d["conversation"] = []
    return d


def save_transcript(
    task_dir: str,
    *,
    project: str,
    user_id: str,
    instance_id: str,
    field_key: str,
    conversation: List[Dict[str, Any]],
    step_count: int = 0,
    started_at: Optional[float] = None,
    finished_at: Optional[float] = None,
    proxy_type: Optional[str] = None,
) -> None:
    """Store one user's finished conversation on one instance.

    A second save for the same (user, instance) replaces the first.
    """
    conn = _db(task_dir)
    conn.execute(
        """INSERT INTO agent_chat_transcripts
               (project, user_id, instance_id, field_key, proxy_type,
                step_count, started_at, finished_at, conversation)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(project, user_id, instance_id) DO UPDATE SET
               field_key = excluded.field_key,
               proxy_type = excluded.proxy_type,
               step_count = excluded.step_count,
               started_at = excluded.started_at,
               finished_at = excluded.finished_at,
               conversation = excluded.conversation""",
        (project, str(user_id), str(instance_id), field_key, proxy_type,
         int(step_count or 0), started_at,
         finished_at if finished_at is not None else time.time(),
         json.dumps(conversation, ensure_ascii=False)),
    )
    conn.commit()


def get_transcript(task_dir: str, project: str, user_id: str,
                   instance_id: str) -> Optional[Dict[str, Any]]:
    """This user's stored transcript for this instance, or None."""
    row = _db(task_dir).execute(
        """SELECT * FROM agent_chat_transcripts
           WHERE project = ? AND user_id = ? AND instance_id = ?""",
        (project, str(user_id), str(instance_id)),
    ).fetchone()
    return _row_to_dict(row) if row else None


def transcripts_for_project(task_dir: str, project: str) -> List[Dict[str, Any]]:
    """Every stored transcript in the project, ordered by user then instance."""
    rows = _db(task_dir).execute(
        """SELECT * FROM agent_chat_transcripts WHERE project = ?
           ORDER BY user_id, instance_id""",
        (project,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_for_user(task_dir: str, project: str, user_id: str) -> int:
    """Remove a user's transcripts. Supports data-deletion requests."""
    conn = _db(task_dir)
    cur = conn.execute(
        "DELETE FROM agent_chat_transcripts WHERE project = ? AND user_id = ?",
        (project, str(user_id)),
    )
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------
# Config helpers shared by the routes, the page render and the exporters
# --------------------------------------------------------------------------


def chat_field_key(config: Dict[str, Any]) -> Optional[str]:
    """The data key of the config's ``interactive_chat`` display field.

    None when the display has no such field.
    """
    fields = ((config or {}).get("instance_display") or {}).get("fields") or []
    for field in fields:
        if isinstance(field, dict) and field.get("type") == "interactive_chat":
            return field.get("key") or "conversation"
    return None


def store_location(config: Dict[str, Any]):
    """(task_dir, project) for this config, matching the other stores."""
    config = config or {}
    return (config.get("task_dir") or "."), (config.get("annotation_task_name") or "potato")


def with_user_transcript(config: Dict[str, Any], item_data: Any,
                         user_id: str, instance_id: str) -> Any:
    """``item_data`` as ``user_id`` should see it.

    When the config has an ``interactive_chat`` field and this user has
    finished a chat on this instance, returns a shallow copy of the item data
    with that field set to the user's own conversation. Otherwise returns
    ``item_data`` itself. The shared item is never modified.
    """
    if not isinstance(item_data, dict):
        return item_data
    key = chat_field_key(config)
    if not key:
        return item_data
    try:
        task_dir, project = store_location(config)
        record = get_transcript(task_dir, project, user_id, instance_id)
    except Exception:
        return item_data
    if not record or not record.get("conversation"):
        return item_data
    view = dict(item_data)
    view[key] = record["conversation"]
    return view


def transcripts_by_user_instance(config: Dict[str, Any]) -> Dict[tuple, Dict[str, Any]]:
    """All of a project's transcripts keyed by (user_id, instance_id).

    Empty, without opening the database, when the config has no
    ``interactive_chat`` field.
    """
    if not chat_field_key(config):
        return {}
    task_dir, project = store_location(config)
    return {(r["user_id"], r["instance_id"]): r
            for r in transcripts_for_project(task_dir, project)}
