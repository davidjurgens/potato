"""
MySQL storage for annotator state.

An annotator's state is the same object on both backends, an
:class:`~potato.user_state_management.InMemoryUserState`; this backend only
changes where it is kept. ``save()`` writes the document that the file backend
writes to ``user_state.json`` into ``user_state_documents``, and the
annotation history into ``annotation_history_log``.

The backend this replaces stored state as rows, one table per kind of
answer, and reimplemented the state interface on top of them. It could not
have run: on MySQL 8 with utf8mb4 its label table's unique key is longer than
InnoDB allows, so creating the tables failed at boot. Beyond that, saving
raised AttributeError on every request, links, events, training and survey
answers had no table, its annotation count added the label and span tables
together, and nothing loaded its users at boot.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from potato.user_state_management import InMemoryUserState

logger = logging.getLogger(__name__)


class MysqlUserState(InMemoryUserState):
    """An annotator's state, persisted to MySQL instead of the output directory."""

    def __init__(self, user_id: str, max_assignments: int = -1, db_manager=None):
        super().__init__(user_id, max_assignments)
        self.db_manager = db_manager

    # ------------------------------------------------------------------ save
    def save(self, user_dir: Optional[str] = None) -> None:
        """Write the state document and any new history in one transaction.

        ``user_dir`` is accepted for the file backend's signature and ignored.
        """
        document = json.dumps(self.to_json(), default=str)
        with self._history_lock:
            pending = self.annotation_history[self._history_saved:]
            start = self._history_saved
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                # The value is passed twice rather than read back with
                # VALUES(), which MySQL 8 warns is deprecated -- and the pool
                # raises on warnings.
                cursor.execute(
                    "INSERT INTO user_state_documents (user_id, state_json) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE state_json = %s",
                    (self.user_id, document, document))
                if pending:
                    cursor.executemany(
                        "INSERT INTO annotation_history_log (user_id, seq, action_json) "
                        "VALUES (%s, %s, %s)",
                        [(self.user_id, start + i, json.dumps(a.to_dict(), default=str))
                         for i, a in enumerate(pending)])
                conn.commit()
            self._history_saved = start + len(pending)

    # ------------------------------------------------------------------ load
    @classmethod
    def load_from_db(cls, user_id: str, db_manager) -> Optional["MysqlUserState"]:
        """The stored state for ``user_id``, or None when there is none."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT state_json FROM user_state_documents WHERE user_id = %s",
                           (user_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            state = cls.from_json_dict(json.loads(row[0]), db_manager=db_manager)
            cursor.execute("SELECT action_json FROM annotation_history_log "
                           "WHERE user_id = %s ORDER BY seq", (user_id,))
            history = cursor.fetchall()

        from potato.annotation_history import AnnotationAction
        for (action_json,) in history:
            try:
                action = AnnotationAction.from_dict(json.loads(action_json))
            except Exception:
                logger.warning("Skipping unreadable history row for %s", user_id)
                continue
            state.annotation_history.append(action)
            state.instance_action_history[action.instance_id].append(action)
        state._history_saved = len(history)
        state._after_history_loaded()
        return state

    @staticmethod
    def has_stored_state(user_id: str, db_manager) -> bool:
        """True when ``user_id`` has a stored state."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM user_state_documents WHERE user_id = %s",
                           (user_id,))
            return cursor.fetchone() is not None

    @staticmethod
    def stored_user_ids(db_manager) -> List[str]:
        """Every annotator with a stored state."""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM user_state_documents")
            return [r[0] for r in cursor.fetchall()]
