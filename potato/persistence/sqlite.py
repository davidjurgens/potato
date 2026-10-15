"""
Universal SQLite Helper

Provides a process-wide cache of WAL-mode SQLite connections keyed by task_dir,
plus a migration registry so each feature module declares the tables it owns.

Design choices:
- One database file per project: `<task_dir>/project.sqlite`. A feature with
  enough rows to want its own WAL (the labeling engine's prediction store) can
  name another file through ``Migration.database``; ``get_db(task_dir,
  database="engine")`` then opens `<task_dir>/engine.sqlite` with the same
  settings and runs only the migrations registered for that file.
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
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    """A single, idempotent schema migration.

    Attributes:
        name: Unique identifier (e.g. "0001_memos"). Used as the migration
            key in the `schema_migrations` table — running twice is a no-op.
        sql: SQL statement(s). Multi-statement scripts allowed; runs via
            ``connection.executescript``.
        database: Which file under task_dir the migration belongs to, without
            the ``.sqlite`` suffix. Defaults to the shared ``project`` file.
    """
    name: str
    sql: str
    database: str = "project"


_MIGRATIONS: List[Migration] = []
_MIGRATION_NAMES: set = set()
_REGISTRY_LOCK = threading.Lock()

#: (abs task_dir, database name) -> connection
_DB_CACHE: Dict[Tuple[str, str], sqlite3.Connection] = {}
_DB_CACHE_LOCK = threading.Lock()

#: Migration names known to be applied on each cached connection. Lets the
#: common get_db() call, with nothing pending, return without running any SQL.
_APPLIED: Dict[Tuple[str, str], set] = {}

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


def clear_migrations() -> None:
    """Reset the process-global migration registry. Tests only.

    The registry is process-global and migrations are normally registered
    once at import time. A test that registers an ad-hoc migration would
    otherwise leak it into every later test's `get_db()` in the same
    pytest process. Call this (and `clear_db_cache()`) for isolation.
    """
    with _REGISTRY_LOCK:
        _MIGRATIONS.clear()
        _MIGRATION_NAMES.clear()


def _check_database_name(database: str) -> None:
    # The name becomes a file name under task_dir; refuse anything that could
    # leave it.
    if not database or not database.replace("_", "").isalnum():
        raise ValueError(f"Invalid database name {database!r}")


def get_db(task_dir: str, database: str = "project") -> sqlite3.Connection:
    """Return the cached WAL-mode SQLite connection for this project.

    On first call for a given task_dir and database, opens
    `<task_dir>/<database>.sqlite`, sets WAL + foreign_keys, and runs the
    pending migrations registered for that database.

    Connections are cached per task_dir and reused across requests. They
    are NOT thread-local — SQLite connections created with
    `check_same_thread=False` are safe for serialized access from multiple
    threads, which matches Flask's per-request threading model.
    """
    _check_database_name(database)
    abs_dir = os.path.abspath(task_dir)
    key = (abs_dir, database)
    with _DB_CACHE_LOCK:
        existing = _DB_CACHE.get(key)
        if existing is not None:
            # Apply any migrations registered AFTER this connection was
            # first opened. Without this, a feature whose module is
            # imported/registered later than another feature's first
            # get_db() call would never get its tables created.
            #
            # Nothing runs when nothing is pending. Migrations go through
            # executescript(), which COMMITs whatever transaction is open on
            # the connection, and the connection is shared by every thread:
            # running it on every call committed other threads' half-written
            # batches out from under them. With something pending and a
            # transaction open, the migration waits for the next call.
            applied = _APPLIED.setdefault(key, set())
            with _REGISTRY_LOCK:
                pending = [m for m in _MIGRATIONS
                           if m.database == database and m.name not in applied]
            if pending and not existing.in_transaction:
                _run_pending_migrations(existing, database, applied)
            return existing
        os.makedirs(abs_dir, exist_ok=True)
        db_path = os.path.join(abs_dir, f"{database}.sqlite")
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
        applied: set = set()
        _run_pending_migrations(conn, database, applied)
        _DB_CACHE[key] = conn
        _APPLIED[key] = applied
        logger.info(f"Opened SQLite DB: {db_path}")
        return conn


def close_db(task_dir: str, database: Optional[str] = None) -> None:
    """Close and evict cached connections for one task_dir.

    With ``database`` unset, every database open for that task_dir is closed,
    so a caller releasing a project directory releases all of its files.
    """
    abs_dir = os.path.abspath(task_dir)
    with _DB_CACHE_LOCK:
        keys = [k for k in _DB_CACHE
                if k[0] == abs_dir and (database is None or k[1] == database)]
        conns = [_DB_CACHE.pop(k) for k in keys]
        for k in keys:
            _APPLIED.pop(k, None)
    for conn in conns:
        try:
            conn.close()
        except sqlite3.Error as e:
            logger.warning(f"Error closing DB for {abs_dir}: {e}")


def clear_db_cache() -> None:
    """Close every cached connection. Primarily for tests."""
    with _DB_CACHE_LOCK:
        connections = list(_DB_CACHE.values())
        _DB_CACHE.clear()
        _APPLIED.clear()
    for conn in connections:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def _run_pending_migrations(conn: sqlite3.Connection,
                            database: str = "project",
                            known: Optional[set] = None) -> None:
    """Apply this database's migrations not yet in its schema_migrations.

    ``known`` is the caller's cache of applied names; it is updated with
    everything found applied or applied here.
    """
    conn.executescript(_SCHEMA_MIGRATIONS_DDL)
    applied = {
        row["name"]
        for row in conn.execute("SELECT name FROM schema_migrations").fetchall()
    }
    if known is not None:
        known.update(applied)
    with _REGISTRY_LOCK:
        pending = [m for m in _MIGRATIONS
                   if m.database == database and m.name not in applied]

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
            if known is not None:
                known.add(migration.name)
            logger.info(f"Applied migration: {migration.name}")
        except sqlite3.Error as e:
            logger.error(f"Migration {migration.name} failed: {e}")
            raise
