"""
Universal SQLite Helper

Provides a process-wide cache of WAL-mode SQLite connections keyed by task_dir,
plus a migration registry so each feature module declares the tables it owns.

Design choices:
- One database file per project: `<task_dir>/project.sqlite`.
- WAL journal mode for concurrent reads alongside writes.
- `foreign_keys = ON` enforced on every connection.
- Migrations are idempotent and tracked in a `schema_migrations` table.
- Modules register migrations at import time via `register_migration()`;
  pending migrations run on first `get_db(task_dir)` call.
- Thread-safe: a per-process lock guards the cache and the migration runner.

Usage:
    from potato.persistence import register_migration, Migration, get_db

    register_migration(Migration(
        name="0001_memos",
        sql=\"""CREATE TABLE IF NOT EXISTS memos (
            id TEXT PRIMARY KEY,
            ...
        );\""",
    ))

    conn = get_db(task_dir)
    conn.execute("INSERT INTO memos ...")
    conn.commit()
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    """A single, idempotent schema migration.

    Attributes:
        name: Unique identifier (e.g. "0001_memos"). Used as the migration
            key in the `schema_migrations` table — running twice is a no-op.
        sql: SQL statement(s). Multi-statement scripts allowed; runs via
            ``connection.executescript``.
    """
    name: str
    sql: str


_MIGRATIONS: List[Migration] = []
_MIGRATION_NAMES: set = set()
_REGISTRY_LOCK = threading.Lock()

_DB_CACHE: Dict[str, sqlite3.Connection] = {}
_DB_CACHE_LOCK = threading.Lock()

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def register_migration(migration: Migration) -> None:
    """Register a migration so it runs on the next `get_db()` call.

    Re-registering a migration with the same name is a no-op; this lets
    modules call `register_migration` unconditionally at import time without
    worrying about double-imports.
    """
    with _REGISTRY_LOCK:
        if migration.name in _MIGRATION_NAMES:
            return
        _MIGRATIONS.append(migration)
        _MIGRATION_NAMES.add(migration.name)
        logger.debug(f"Registered migration: {migration.name}")


def registered_migrations() -> List[Migration]:
    """Return a copy of the current migration registry (in registration order)."""
    with _REGISTRY_LOCK:
        return list(_MIGRATIONS)


def get_db(task_dir: str) -> sqlite3.Connection:
    """Return the cached WAL-mode SQLite connection for this project.

    On first call for a given task_dir, opens `<task_dir>/project.sqlite`,
    sets WAL + foreign_keys, and runs any pending migrations.

    Connections are cached per task_dir and reused across requests. They
    are NOT thread-local — SQLite connections created with
    `check_same_thread=False` are safe for serialized access from multiple
    threads, which matches Flask's per-request threading model.
    """
    abs_dir = os.path.abspath(task_dir)
    with _DB_CACHE_LOCK:
        existing = _DB_CACHE.get(abs_dir)
        if existing is not None:
            return existing
        os.makedirs(abs_dir, exist_ok=True)
        db_path = os.path.join(abs_dir, "project.sqlite")
        conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # autocommit; callers manage transactions
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        _run_pending_migrations(conn)
        _DB_CACHE[abs_dir] = conn
        logger.info(f"Opened SQLite project DB: {db_path}")
        return conn


def close_db(task_dir: str) -> None:
    """Close and evict the cached connection for one task_dir."""
    abs_dir = os.path.abspath(task_dir)
    with _DB_CACHE_LOCK:
        conn = _DB_CACHE.pop(abs_dir, None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error as e:
            logger.warning(f"Error closing DB for {abs_dir}: {e}")


def clear_db_cache() -> None:
    """Close every cached connection. Primarily for tests."""
    with _DB_CACHE_LOCK:
        connections = list(_DB_CACHE.values())
        _DB_CACHE.clear()
    for conn in connections:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def _run_pending_migrations(conn: sqlite3.Connection) -> None:
    """Apply migrations that haven't been recorded in schema_migrations yet."""
    conn.executescript(_SCHEMA_MIGRATIONS_DDL)
    applied = {
        row["name"]
        for row in conn.execute("SELECT name FROM schema_migrations").fetchall()
    }
    with _REGISTRY_LOCK:
        pending = [m for m in _MIGRATIONS if m.name not in applied]

    if not pending:
        return

    # Note on atomicity: Python's `executescript()` issues an implicit COMMIT
    # at the start, which dissolves any transaction (BEGIN/COMMIT *or*
    # SAVEPOINT/RELEASE) we wrap around it. So we don't wrap. The convention
    # is that every migration uses idempotent DDL (`CREATE TABLE IF NOT
    # EXISTS`, `CREATE INDEX IF NOT EXISTS`, etc.); if `executescript()`
    # raises, the migration record is *not* inserted, and the migration will
    # retry cleanly on the next `get_db()` call. `INSERT OR IGNORE` makes the
    # success path safe against double-application from a benign race.
    for migration in pending:
        try:
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)",
                (migration.name,),
            )
            logger.info(f"Applied migration: {migration.name}")
        except sqlite3.Error as e:
            logger.error(f"Migration {migration.name} failed: {e}")
            raise
