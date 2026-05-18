"""Unit tests for potato.persistence.sqlite."""

import os
import sqlite3
import tempfile
import threading

import pytest

from potato.persistence import (
    Migration,
    clear_db_cache,
    close_db,
    get_db,
    register_migration,
    registered_migrations,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    """Each test starts with an empty connection cache."""
    clear_db_cache()
    yield
    clear_db_cache()


@pytest.fixture
def task_dir(tmp_path):
    """Yield an isolated task_dir for each test."""
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


class TestGetDb:
    def test_creates_project_sqlite(self, task_dir):
        conn = get_db(task_dir)
        assert os.path.exists(os.path.join(task_dir, "project.sqlite"))
        assert isinstance(conn, sqlite3.Connection)

    def test_caches_connection_per_task_dir(self, task_dir):
        c1 = get_db(task_dir)
        c2 = get_db(task_dir)
        assert c1 is c2

    def test_wal_mode_enabled(self, task_dir):
        conn = get_db(task_dir)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_foreign_keys_on(self, task_dir):
        conn = get_db(task_dir)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_row_factory_is_row(self, task_dir):
        conn = get_db(task_dir)
        conn.execute("CREATE TABLE t (a INT, b TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'x')")
        row = conn.execute("SELECT a, b FROM t").fetchone()
        assert row["a"] == 1 and row["b"] == "x"

    def test_creates_task_dir_if_missing(self, tmp_path):
        new_dir = tmp_path / "does_not_exist_yet"
        assert not new_dir.exists()
        get_db(str(new_dir))
        assert (new_dir / "project.sqlite").exists()

    def test_different_task_dirs_get_separate_dbs(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        ca = get_db(str(a))
        cb = get_db(str(b))
        assert ca is not cb


class TestMigrations:
    def test_pending_migration_runs_on_first_get_db(self, task_dir):
        register_migration(Migration(
            name="test_persistence_create_widgets",
            sql="CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);",
        ))
        conn = get_db(task_dir)
        # Table exists
        names = [
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "widgets" in names
        # Recorded in schema_migrations
        applied = {
            r["name"] for r in conn.execute(
                "SELECT name FROM schema_migrations"
            ).fetchall()
        }
        assert "test_persistence_create_widgets" in applied

    def test_register_migration_is_idempotent(self):
        register_migration(Migration(
            name="test_persistence_idempotent_one",
            sql="CREATE TABLE foo_one (a INT);",
        ))
        register_migration(Migration(
            name="test_persistence_idempotent_one",
            sql="CREATE TABLE foo_one_DIFFERENT (b INT);",
        ))
        names = [m.name for m in registered_migrations()]
        # Second registration ignored
        assert names.count("test_persistence_idempotent_one") == 1

    def test_migration_does_not_re_run_on_second_get_db(self, task_dir):
        register_migration(Migration(
            name="test_persistence_run_once",
            sql="CREATE TABLE run_once_t (n INT);",
        ))
        conn1 = get_db(task_dir)
        conn1.execute("INSERT INTO run_once_t (n) VALUES (42)")
        # Drop the cached conn, reopen — the data should still be there,
        # and the CREATE TABLE shouldn't fail (migration is recorded).
        close_db(task_dir)
        conn2 = get_db(task_dir)
        row = conn2.execute("SELECT n FROM run_once_t").fetchone()
        assert row["n"] == 42


class TestClose:
    def test_close_db_evicts_from_cache(self, task_dir):
        c1 = get_db(task_dir)
        close_db(task_dir)
        c2 = get_db(task_dir)
        assert c1 is not c2

    def test_close_db_on_unknown_dir_is_noop(self, tmp_path):
        close_db(str(tmp_path / "never_opened"))  # should not raise


class TestThreadSafety:
    def test_concurrent_get_db_returns_same_connection(self, task_dir):
        """Multiple threads asking for the same task_dir get the same conn."""
        results = []

        def grab():
            results.append(get_db(task_dir))

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()

        first = results[0]
        assert all(r is first for r in results)
