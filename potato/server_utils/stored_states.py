"""
Every annotator's saved state, from wherever the study keeps it.

The file backend writes ``<output_annotation_dir>/<user>/user_state.json``; the
MySQL backend writes the same document to the ``user_state_documents`` table.
Export, paper mode, auto-export and model training read the saved states
rather than the running server's memory, and they used to read only the
files, so on a MySQL study each of them found no annotations and said
nothing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Iterator, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

USER_STATE_FILE = "user_state.json"


def uses_mysql(config: Optional[Mapping]) -> bool:
    """True when ``config`` stores annotator state in MySQL."""
    db = (config or {}).get("database")
    return isinstance(db, Mapping) and db.get("type") == "mysql"


def _db_manager(config: Mapping):
    """The running server's connection pool, or a new one for an offline tool."""
    try:
        from potato.user_state_management import get_user_state_manager
        usm = get_user_state_manager()
        if getattr(usm, "use_database", False) and usm.db_manager is not None:
            return usm.db_manager
    except Exception:
        pass
    # An offline tool reads the YAML itself, so ``password: ${VAR}`` has not
    # been expanded the way the server's config loader expands it.
    import copy
    from potato.database import DatabaseManager
    from potato.server_utils.config_module import _substitute_secret_references
    config = copy.deepcopy(dict(config))
    _substitute_secret_references(config["database"])
    return DatabaseManager(config)


def iter_stored_states(output_dir: str, config: Optional[Mapping] = None,
                       skip_unreadable: bool = False) -> Iterator[Tuple[str, dict]]:
    """Yield ``(name, state)`` for every saved annotator state.

    ``name`` is the user directory on the file backend and the user id on
    MySQL; callers use it only when the state carries no ``user_id``. With
    ``skip_unreadable`` a state that is not valid JSON is logged and skipped;
    otherwise the error propagates. A database error always propagates: an
    export that silently came back empty is the failure this module exists to
    stop.
    """
    if uses_mysql(config):
        db = _db_manager(config)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, state_json FROM user_state_documents "
                           "ORDER BY user_id")
            rows = cursor.fetchall()
        for user_id, document in rows:
            try:
                state = json.loads(document)
            except ValueError:
                if not skip_unreadable:
                    raise
                logger.warning("Skipping unreadable stored state for %s", user_id)
                continue
            yield user_id, state
        return

    if not os.path.isdir(output_dir):
        return
    for entry in sorted(os.listdir(output_dir)):
        state_file = os.path.join(output_dir, entry, USER_STATE_FILE)
        if not os.path.isfile(state_file):
            continue
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            if not skip_unreadable:
                raise
            logger.warning("Skipping unreadable state file %s", state_file)
            continue
        yield entry, state


HISTORY_FILE = "annotation_history.jsonl"


def has_stored_state(output_dir: str, config: Optional[Mapping] = None) -> bool:
    """True when any annotator's state has been saved."""
    if uses_mysql(config):
        db = _db_manager(config)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM information_schema.tables "
                           "WHERE table_schema = DATABASE() "
                           "AND table_name = 'user_state_documents'")
            if cursor.fetchone() is None:
                return False
            cursor.execute("SELECT 1 FROM user_state_documents LIMIT 1")
            return cursor.fetchone() is not None
    for _name, _state in iter_stored_states(output_dir, None, skip_unreadable=True):
        return True
    return False


def write_stored_state(output_dir: str, name: str, state: dict,
                       config: Optional[Mapping] = None) -> None:
    """Replace one annotator's saved state document.

    ``name`` is what :func:`iter_stored_states` yielded for that annotator. The
    history is left alone on both backends.
    """
    document = json.dumps(state)
    if uses_mysql(config):
        db = _db_manager(config)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE user_state_documents SET state_json = %s "
                           "WHERE user_id = %s", (document, name))
            conn.commit()
        return
    state_file = os.path.join(output_dir, name, USER_STATE_FILE)
    # Written beside the target and renamed, as UserState.save() does, so an
    # interruption cannot leave a truncated state file.
    tmp = state_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(document)
    os.replace(tmp, state_file)


def dump_mysql_states(config: Mapping, dest_root: str) -> int:
    """Write every MySQL annotator into ``dest_root`` in the file backend's layout.

    ``<dest_root>/<user>/user_state.json`` and ``annotation_history.jsonl``,
    exactly what the file backend would have written, so archives, pulls and
    backups carry the work and :func:`import_file_states_into_mysql` can load
    it back. Each file is written beside its target and renamed. Returns the
    number of annotators written.
    """
    from potato.server_utils.usernames import user_dir

    db = _db_manager(config)
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, state_json FROM user_state_documents "
                       "ORDER BY user_id")
        documents = cursor.fetchall()
        cursor.execute("SELECT user_id, action_json FROM annotation_history_log "
                       "ORDER BY user_id, seq")
        history = {}
        for user_id, action_json in cursor.fetchall():
            history.setdefault(user_id, []).append(action_json)

    written = 0
    for user_id, document in documents:
        try:
            directory = user_dir(dest_root, user_id)
        except ValueError as exc:
            logger.error("Not writing %r out of the database: %s", user_id, exc)
            continue
        os.makedirs(directory, exist_ok=True)
        _write_atomically(os.path.join(directory, USER_STATE_FILE), document)
        lines = history.get(user_id, [])
        _write_atomically(os.path.join(directory, HISTORY_FILE),
                          "".join(line + "\n" for line in lines))
        written += 1
    return written


def _write_atomically(path: str, text: str) -> None:
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(partial, path)


def import_file_states_into_mysql(output_dir: str, usm) -> int:
    """Copy file-backend annotators that the database does not hold into it.

    A file study switched to MySQL, a project made by ``potato import
    --seed-user``, and a backup restored onto an empty database all leave
    ``user_state.json`` files the MySQL backend never reads, so their work
    vanished. The database copy wins when both exist; the files are left in
    place. Returns the number of annotators imported.
    """
    from potato.database import MysqlUserState

    if not os.path.isdir(output_dir):
        return 0
    stored = set(MysqlUserState.stored_user_ids(usm.db_manager))
    imported = 0
    for entry in sorted(os.listdir(output_dir)):
        directory = os.path.join(output_dir, entry)
        state_file = os.path.join(directory, USER_STATE_FILE)
        if not os.path.isfile(state_file):
            continue
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                document = json.load(f)
            user_id = document["user_id"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("Not importing %s into the database: %s", state_file, exc)
            continue
        if user_id in stored:
            continue
        state = MysqlUserState.from_json_dict(document, db_manager=usm.db_manager)
        state._load_history(directory)
        state._after_history_loaded()
        # Every history row is new to the database.
        state._history_saved = 0
        state.save()
        stored.add(user_id)
        imported += 1
        logger.warning("Imported %s's state from %s into the MySQL database",
                       user_id, state_file)
    return imported
