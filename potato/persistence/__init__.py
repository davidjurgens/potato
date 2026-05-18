"""
Universal Persistence Layer

SQLite-backed persistence for features that need project-scoped state:
memos, search index, codebook, cases, queries, smart codes.

A single `<task_dir>/project.sqlite` file holds all tables. Modules register
their schemas via the migration registry; on each `get_db()` call any pending
migrations run inside a transaction.

This package is universal — not gated to QDA Mode. Both standard annotation
projects and QDA Mode projects can read/write to the same DB; QDA Mode just
populates more tables.
"""

from .sqlite import (
    Migration,
    get_db,
    close_db,
    clear_db_cache,
    clear_migrations,
    register_migration,
    registered_migrations,
)

__all__ = [
    "Migration",
    "get_db",
    "close_db",
    "clear_db_cache",
    "clear_migrations",
    "register_migration",
    "registered_migrations",
]
