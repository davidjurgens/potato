"""
Experiment storage (file + sqlite backends).

Experiments are immutable, write-once records. The file backend writes one JSON
per experiment under ``<base_dir>/experiments/``; the sqlite backend stores them
in an ``experiments`` table in the shared ``datasets.sqlite``. Backend is chosen
to match the datasets backend via ``datasets.storage``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import List, Optional

from potato.experiments.models import Experiment


class ExperimentStore:
    """Abstract-ish base; concrete behavior comes from the two backends below."""

    def save(self, experiment: Experiment) -> None:  # pragma: no cover
        raise NotImplementedError

    def get(self, experiment_id: str) -> Optional[Experiment]:  # pragma: no cover
        raise NotImplementedError

    def list(self, dataset_name: Optional[str] = None) -> List[Experiment]:  # pragma: no cover
        raise NotImplementedError

    def delete(self, experiment_id: str) -> bool:  # pragma: no cover
        raise NotImplementedError


class FileExperimentStore(ExperimentStore):
    def __init__(self, base_dir: str = "."):
        self._root = os.path.join(base_dir, "experiments")
        self._lock = threading.RLock()
        os.makedirs(self._root, exist_ok=True)

    def _path(self, experiment_id: str) -> str:
        return os.path.join(self._root, f"{experiment_id}.json")

    def save(self, experiment: Experiment) -> None:
        with self._lock:
            tmp = self._path(experiment.id) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(experiment.to_dict(), f, indent=2)
            os.replace(tmp, self._path(experiment.id))

    def get(self, experiment_id: str) -> Optional[Experiment]:
        path = self._path(experiment_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return Experiment.from_dict(json.load(f))

    def list(self, dataset_name: Optional[str] = None) -> List[Experiment]:
        if not os.path.isdir(self._root):
            return []
        out = []
        for fn in sorted(os.listdir(self._root)):
            if fn.endswith(".json"):
                exp = self.get(fn[:-5])
                if exp and (dataset_name is None or exp.dataset_name == dataset_name):
                    out.append(exp)
        return out

    def delete(self, experiment_id: str) -> bool:
        path = self._path(experiment_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False


class SQLiteExperimentStore(ExperimentStore):
    def __init__(self, base_dir: str = "."):
        os.makedirs(base_dir, exist_ok=True)
        self._db_path = os.path.join(base_dir, "datasets.sqlite")
        self._lock = threading.RLock()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    dataset_name TEXT,
                    created_at TEXT,
                    payload TEXT
                )"""
            )
            conn.commit()

    def save(self, experiment: Experiment) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO experiments (id, dataset_name, created_at, payload) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (experiment.id, experiment.dataset_name, experiment.created_at,
                 json.dumps(experiment.to_dict(), ensure_ascii=False)),
            )
            conn.commit()

    def get(self, experiment_id: str) -> Optional[Experiment]:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
            return Experiment.from_dict(json.loads(row[0])) if row else None

    def list(self, dataset_name: Optional[str] = None) -> List[Experiment]:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            if dataset_name:
                rows = conn.execute(
                    "SELECT payload FROM experiments WHERE dataset_name = ? ORDER BY created_at",
                    (dataset_name,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT payload FROM experiments ORDER BY created_at").fetchall()
            return [Experiment.from_dict(json.loads(r[0])) for r in rows]

    def delete(self, experiment_id: str) -> bool:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM experiments WHERE id = ?", (experiment_id,))
            conn.commit()
            return cur.rowcount > 0


def create_experiment_store(backend: str = "file", base_dir: str = ".") -> ExperimentStore:
    backend = (backend or "file").lower()
    if backend == "file":
        return FileExperimentStore(base_dir)
    if backend == "sqlite":
        return SQLiteExperimentStore(base_dir)
    raise ValueError(f"Unknown experiment storage backend: {backend!r}")
