"""
SQLite dataset storage backend.

A single ``datasets.sqlite`` under ``<base_dir>`` holds all datasets, versions,
tags, and example snapshots. Chosen via ``datasets.storage: sqlite`` for large
dataset/experiment counts and queryability. Implements the same primitives as
the file backend, so versioning semantics are identical (verified by the shared
parametrized test suite).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import List, Optional

from potato.eval_datasets.models import Dataset, DatasetVersion, Example
from potato.eval_datasets.storage_base import BaseVersionedStore


class SQLiteDatasetStore(BaseVersionedStore):
    def __init__(self, base_dir: str = "."):
        os.makedirs(base_dir, exist_ok=True)
        self._db_path = os.path.join(base_dir, "datasets.sqlite")
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    name TEXT PRIMARY KEY,
                    description TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS versions (
                    dataset TEXT,
                    version_id TEXT,
                    created_at TEXT,
                    example_count INTEGER,
                    tags TEXT,
                    note TEXT,
                    seq INTEGER,
                    PRIMARY KEY (dataset, version_id)
                );
                CREATE TABLE IF NOT EXISTS examples (
                    dataset TEXT,
                    version_id TEXT,
                    example_id TEXT,
                    payload TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_examples_ver
                    ON examples (dataset, version_id);
                """
            )

    # ----- primitives -----

    def _load_meta(self, name: str) -> Optional[Dataset]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT name, description, created_at FROM datasets WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return None
            vrows = conn.execute(
                "SELECT version_id, created_at, example_count, tags, note "
                "FROM versions WHERE dataset = ? ORDER BY seq ASC", (name,)
            ).fetchall()
            versions = [
                DatasetVersion(
                    version_id=v["version_id"],
                    created_at=v["created_at"],
                    example_count=v["example_count"],
                    tags=json.loads(v["tags"] or "[]"),
                    note=v["note"] or "",
                )
                for v in vrows
            ]
            return Dataset(
                name=row["name"],
                description=row["description"] or "",
                created_at=row["created_at"] or "",
                versions=versions,
            )

    def _save_meta(self, dataset: Dataset) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO datasets (name, description, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET description=excluded.description",
                (dataset.name, dataset.description, dataset.created_at),
            )
            # Re-upsert version rows (tags/notes may have changed).
            for seq, v in enumerate(dataset.versions, 1):
                conn.execute(
                    "INSERT INTO versions (dataset, version_id, created_at, example_count, tags, note, seq) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(dataset, version_id) DO UPDATE SET "
                    "tags=excluded.tags, note=excluded.note, example_count=excluded.example_count",
                    (dataset.name, v.version_id, v.created_at, v.example_count,
                     json.dumps(v.tags), v.note, seq),
                )
            conn.commit()

    def _load_version_examples(self, name: str, version_id: str) -> List[Example]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM examples WHERE dataset = ? AND version_id = ? "
                "ORDER BY rowid ASC", (name, version_id)
            ).fetchall()
            return [Example.from_dict(json.loads(r["payload"])) for r in rows]

    def _write_version_examples(self, name: str, version_id: str, examples: List[Example]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM examples WHERE dataset = ? AND version_id = ?", (name, version_id)
            )
            conn.executemany(
                "INSERT INTO examples (dataset, version_id, example_id, payload) VALUES (?, ?, ?, ?)",
                [(name, version_id, e.id, json.dumps(e.to_dict(), ensure_ascii=False)) for e in examples],
            )
            conn.commit()

    def _all_dataset_names(self) -> List[str]:
        with self._lock, self._connect() as conn:
            return [r["name"] for r in conn.execute("SELECT name FROM datasets ORDER BY name").fetchall()]

    def _remove_dataset(self, name: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM datasets WHERE name = ?", (name,))
            conn.execute("DELETE FROM versions WHERE dataset = ?", (name,))
            conn.execute("DELETE FROM examples WHERE dataset = ?", (name,))
            conn.commit()
            return cur.rowcount > 0
