"""Where training runs are recorded.

Every run leaves three kinds of trace, and they are separated because they have
different lifetimes:

``training_runs``
    One row per run: what was trained, on how much, how it scored, where the
    artifacts landed. This is a provenance ledger, not an experiment tracker --
    it answers "where did this prediction come from", not "which hyperparameters
    win".

``training_run_items``
    Which instance went into which split. This is the leak guard. Without it
    there is no way to refuse to prelabel an item the model was fitted on, and
    no way to tell whether round two's metrics were computed on data round one
    already saw.

``training_predictions``
    The durable copy of what a run predicted. Predictions written into item data
    at runtime do not survive a restart -- under the default in-memory store,
    ``item_data["predictions"]`` is populated from the input file at load time
    and nothing re-persists it. This table is what gets replayed at boot.

The subsystem that replaced this one -- ``DatabaseStateManager`` in
``active_learning_manager`` -- was a stub that logged "initialized successfully"
while creating no tables and saving no metrics. Nothing here should be able to
fail that quietly: every write commits or raises.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "TrainingRun",
    "RUN_STATES",
    "TERMINAL_STATES",
    "new_run_id",
    "record_run",
    "load_run",
    "list_runs",
    "latest_run",
    "delete_run",
    "prune_runs",
    "record_run_items",
    "run_item_splits",
    "training_split_ids",
    "record_predictions",
    "load_predictions",
    "predictions_for_instance",
    "delete_predictions_for_run",
]


#: Run lifecycle. ``building`` covers bundle construction, which happens in the
#: parent and can take a while on a large corpus, so it is worth showing.
RUN_STATES = (
    "queued", "building", "running", "evaluating",
    "success", "error", "cancelled",
)

#: States after which no further progress events are expected.
TERMINAL_STATES = frozenset({"success", "error", "cancelled"})


def new_run_id() -> str:
    """A sortable run id.

    Timestamp first so a directory listing is chronological, with a short
    random tail because two runs can start inside the same second.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return "%s-%s" % (stamp, uuid.uuid4().hex[:6])


@dataclass
class TrainingRun:
    """One training run, from queued to terminal."""

    run_id: str
    trainer: str
    #: ``"local"`` for the subprocess worker, ``"external:<name>"`` otherwise.
    backend: str = "local"
    schema_names: List[str] = field(default_factory=list)
    kinds: List[str] = field(default_factory=list)
    status: str = "queued"
    #: ``manual`` | ``auto`` | ``api`` -- worth keeping, because "did a human
    #: ask for this run" changes how you read a sudden metric drop.
    trigger: str = "manual"
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    n_train: int = 0
    n_val: int = 0
    n_test: int = 0
    split_seed: int = 0
    params: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    artifact_dir: str = ""
    model_version: str = ""
    bundle_digest: str = ""
    error: str = ""
    error_code: str = ""
    pid: Optional[int] = None
    host: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()
        if not self.host:
            self.host = os.uname().nodename if hasattr(os, "uname") else ""

    @property
    def duration(self) -> Optional[float]:
        """Wall-clock seconds, or ``None`` while still running."""
        if self.started_at is None or self.finished_at is None:
            return None
        return self.finished_at - self.started_at

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["duration"] = self.duration
        return out


# --------------------------------------------------------------- persistence

_MIGRATION = None


def _db(task_dir: str):
    from potato.persistence import Migration, get_db, register_migration

    global _MIGRATION
    if _MIGRATION is None:
        _MIGRATION = Migration(
            name="0001_training_runs",
            sql="""
            CREATE TABLE IF NOT EXISTS training_runs (
                project       TEXT NOT NULL,
                run_id        TEXT NOT NULL,
                trainer       TEXT NOT NULL,
                backend       TEXT NOT NULL DEFAULT 'local',
                schema_names  TEXT NOT NULL DEFAULT '[]',
                kinds         TEXT NOT NULL DEFAULT '[]',
                status        TEXT NOT NULL,
                trigger       TEXT NOT NULL DEFAULT 'manual',
                created_at    REAL NOT NULL,
                started_at    REAL,
                finished_at   REAL,
                n_train       INTEGER NOT NULL DEFAULT 0,
                n_val         INTEGER NOT NULL DEFAULT 0,
                n_test        INTEGER NOT NULL DEFAULT 0,
                split_seed    INTEGER NOT NULL DEFAULT 0,
                params        TEXT NOT NULL DEFAULT '{}',
                metrics       TEXT NOT NULL DEFAULT '{}',
                artifact_dir  TEXT NOT NULL DEFAULT '',
                model_version TEXT NOT NULL DEFAULT '',
                bundle_digest TEXT NOT NULL DEFAULT '',
                error         TEXT NOT NULL DEFAULT '',
                error_code    TEXT NOT NULL DEFAULT '',
                pid           INTEGER,
                host          TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (project, run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_training_runs_recent
                ON training_runs (project, created_at DESC);

            CREATE TABLE IF NOT EXISTS training_run_items (
                project     TEXT NOT NULL,
                run_id      TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                split       TEXT NOT NULL,
                PRIMARY KEY (project, run_id, instance_id)
            );
            CREATE INDEX IF NOT EXISTS idx_training_run_items_split
                ON training_run_items (project, run_id, split);

            CREATE TABLE IF NOT EXISTS training_predictions (
                project     TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                schema_name TEXT NOT NULL,
                run_id      TEXT NOT NULL,
                payload     TEXT NOT NULL,
                confidence  REAL,
                created_at  REAL NOT NULL,
                PRIMARY KEY (project, instance_id, schema_name)
            );
            CREATE INDEX IF NOT EXISTS idx_training_predictions_run
                ON training_predictions (project, run_id);
            """,
        )
    register_migration(_MIGRATION)
    return get_db(task_dir)


def _project(config: Dict[str, Any]) -> str:
    return config.get("annotation_task_name", "default")


def _task_dir(config: Dict[str, Any]) -> str:
    return config.get("task_dir", ".")


# ------------------------------------------------------------------ runs

def record_run(config: Dict[str, Any], run: TrainingRun) -> None:
    """Insert or update one run.

    Called repeatedly as a run progresses, so it is an upsert rather than an
    insert. Raises on failure: a run that trained for an hour and then vanished
    because the write was swallowed is worse than a loud error.
    """
    if run.status not in RUN_STATES:
        raise ValueError(
            "Unknown run status %r; expected one of %s"
            % (run.status, ", ".join(RUN_STATES)))

    conn = _db(_task_dir(config))
    conn.execute(
        """INSERT INTO training_runs
               (project, run_id, trainer, backend, schema_names, kinds,
                status, trigger, created_at, started_at, finished_at,
                n_train, n_val, n_test, split_seed, params, metrics,
                artifact_dir, model_version, bundle_digest, error, error_code,
                pid, host)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(project, run_id) DO UPDATE SET
               trainer=excluded.trainer, backend=excluded.backend,
               schema_names=excluded.schema_names, kinds=excluded.kinds,
               status=excluded.status, trigger=excluded.trigger,
               started_at=excluded.started_at,
               finished_at=excluded.finished_at,
               n_train=excluded.n_train, n_val=excluded.n_val,
               n_test=excluded.n_test, split_seed=excluded.split_seed,
               params=excluded.params, metrics=excluded.metrics,
               artifact_dir=excluded.artifact_dir,
               model_version=excluded.model_version,
               bundle_digest=excluded.bundle_digest,
               error=excluded.error, error_code=excluded.error_code,
               pid=excluded.pid, host=excluded.host""",
        (_project(config), run.run_id, run.trainer, run.backend,
         json.dumps(run.schema_names), json.dumps(run.kinds),
         run.status, run.trigger, run.created_at, run.started_at,
         run.finished_at, run.n_train, run.n_val, run.n_test, run.split_seed,
         json.dumps(run.params), json.dumps(run.metrics), run.artifact_dir,
         run.model_version, run.bundle_digest, run.error, run.error_code,
         run.pid, run.host),
    )
    conn.commit()


def _row_to_run(row) -> TrainingRun:
    return TrainingRun(
        run_id=row["run_id"], trainer=row["trainer"], backend=row["backend"],
        schema_names=json.loads(row["schema_names"] or "[]"),
        kinds=json.loads(row["kinds"] or "[]"),
        status=row["status"], trigger=row["trigger"],
        created_at=row["created_at"], started_at=row["started_at"],
        finished_at=row["finished_at"], n_train=row["n_train"],
        n_val=row["n_val"], n_test=row["n_test"],
        split_seed=row["split_seed"],
        params=json.loads(row["params"] or "{}"),
        metrics=json.loads(row["metrics"] or "{}"),
        artifact_dir=row["artifact_dir"], model_version=row["model_version"],
        bundle_digest=row["bundle_digest"], error=row["error"],
        error_code=row["error_code"], pid=row["pid"], host=row["host"])


def load_run(config: Dict[str, Any], run_id: str) -> Optional[TrainingRun]:
    """One run by id, or ``None``."""
    try:
        row = _db(_task_dir(config)).execute(
            "SELECT * FROM training_runs WHERE project = ? AND run_id = ?",
            (_project(config), run_id)).fetchone()
    except Exception:
        logger.debug("Could not read training run %s", run_id, exc_info=True)
        return None
    return _row_to_run(row) if row else None


def list_runs(config: Dict[str, Any], limit: int = 50,
              trainer: Optional[str] = None,
              status: Optional[str] = None) -> List[TrainingRun]:
    """Runs for this project, newest first."""
    sql = "SELECT * FROM training_runs WHERE project = ?"
    params: List[Any] = [_project(config)]
    if trainer:
        sql += " AND trainer = ?"
        params.append(trainer)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))

    try:
        rows = _db(_task_dir(config)).execute(sql, params).fetchall()
    except Exception:
        logger.debug("Could not list training runs", exc_info=True)
        return []
    return [_row_to_run(r) for r in rows]


def latest_run(config: Dict[str, Any], trainer: Optional[str] = None,
               schema_name: Optional[str] = None,
               status: str = "success") -> Optional[TrainingRun]:
    """The newest run matching the filters.

    This is how a consumer asks "what model do we currently have for this
    schema" without knowing any run ids.
    """
    for run in list_runs(config, limit=200, trainer=trainer, status=status):
        if schema_name is None or schema_name in run.schema_names:
            return run
    return None


def delete_run(config: Dict[str, Any], run_id: str) -> None:
    """Forget a run and everything keyed to it, except its predictions.

    Predictions outlive their run deliberately -- see :func:`prune_runs`.
    """
    conn = _db(_task_dir(config))
    project = _project(config)
    conn.execute("DELETE FROM training_run_items WHERE project = ? "
                 "AND run_id = ?", (project, run_id))
    conn.execute("DELETE FROM training_runs WHERE project = ? AND run_id = ?",
                 (project, run_id))
    conn.commit()


def prune_runs(config: Dict[str, Any], retain: int = 5) -> List[str]:
    """Drop old runs, keeping the newest *retain* and anything still cited.

    A run whose predictions are live is never pruned however old it is.
    Deleting it would strand every one of those predictions with a run id that
    resolves to nothing, and "where did this prelabel come from" is the whole
    reason the ledger exists. Retention by record rather than by file mtime is
    the difference; mtime-based cleanup cannot see the citation.

    Returns the run ids actually deleted.
    """
    runs = list_runs(config, limit=10_000)
    if len(runs) <= retain:
        return []

    conn = _db(_task_dir(config))
    project = _project(config)
    try:
        cited = {r["run_id"] for r in conn.execute(
            "SELECT DISTINCT run_id FROM training_predictions "
            "WHERE project = ?", (project,)).fetchall()}
    except Exception:
        logger.debug("Could not read cited runs; pruning nothing",
                     exc_info=True)
        return []

    deleted = []
    for run in runs[retain:]:
        if run.run_id in cited:
            continue
        # An in-flight run is not old, it is just slow.
        if not run.is_terminal:
            continue
        delete_run(config, run.run_id)
        deleted.append(run.run_id)

    if deleted:
        logger.info("Pruned %d training run(s): %s",
                    len(deleted), ", ".join(deleted))
    return deleted


# ------------------------------------------------------------- run items

def record_run_items(config: Dict[str, Any], run_id: str,
                     splits: Dict[str, Iterable[str]]) -> int:
    """Record which instance landed in which split.

    *splits* maps a split name to its instance ids, e.g.
    ``{"train": [...], "val": [...]}``. Returns the number of rows written.
    """
    conn = _db(_task_dir(config))
    project = _project(config)
    rows = [(project, run_id, iid, split)
            for split, ids in splits.items() for iid in ids]
    if not rows:
        return 0
    conn.executemany(
        """INSERT INTO training_run_items (project, run_id, instance_id, split)
           VALUES (?,?,?,?)
           ON CONFLICT(project, run_id, instance_id)
           DO UPDATE SET split = excluded.split""", rows)
    conn.commit()
    return len(rows)


def run_item_splits(config: Dict[str, Any], run_id: str) -> Dict[str, str]:
    """``{instance_id: split}`` for one run."""
    try:
        rows = _db(_task_dir(config)).execute(
            "SELECT instance_id, split FROM training_run_items "
            "WHERE project = ? AND run_id = ?",
            (_project(config), run_id)).fetchall()
    except Exception:
        logger.debug("Could not read run items for %s", run_id, exc_info=True)
        return {}
    return {r["instance_id"]: r["split"] for r in rows}


def training_split_ids(config: Dict[str, Any], run_id: str) -> set:
    """Instance ids this run *fitted on*.

    The write-back layer's leak guard. Predicting onto an item the model was
    trained on produces a confident, meaningless prelabel, and if a human then
    accepts it the error is laundered into the next round's training data.
    """
    try:
        rows = _db(_task_dir(config)).execute(
            "SELECT instance_id FROM training_run_items "
            "WHERE project = ? AND run_id = ? AND split = 'train'",
            (_project(config), run_id)).fetchall()
    except Exception:
        logger.debug("Could not read train split for %s", run_id,
                     exc_info=True)
        return set()
    return {r["instance_id"] for r in rows}


# ----------------------------------------------------------- predictions

def record_predictions(
    config: Dict[str, Any], run_id: str,
    predictions: Sequence[Tuple[str, str, Any, Optional[float]]],
) -> int:
    """Store predictions as ``(instance_id, schema_name, payload, confidence)``.

    One prediction per (instance, schema): a newer run supersedes an older
    one rather than accumulating, because item data has room for exactly one
    prelabel per schema and a table that disagreed with it would be a second
    source of truth.
    """
    if not predictions:
        return 0
    now = time.time()
    conn = _db(_task_dir(config))
    project = _project(config)
    conn.executemany(
        """INSERT INTO training_predictions
               (project, instance_id, schema_name, run_id, payload,
                confidence, created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(project, instance_id, schema_name) DO UPDATE SET
               run_id=excluded.run_id, payload=excluded.payload,
               confidence=excluded.confidence,
               created_at=excluded.created_at""",
        [(project, iid, schema, run_id, json.dumps(payload), conf, now)
         for iid, schema, payload, conf in predictions])
    conn.commit()
    return len(predictions)


def load_predictions(config: Dict[str, Any], run_id: Optional[str] = None
                     ) -> List[Dict[str, Any]]:
    """Every stored prediction, optionally filtered to one run.

    Replayed into item data at boot, because runtime-written predictions are
    not durable on their own.
    """
    sql = ("SELECT instance_id, schema_name, run_id, payload, confidence, "
           "created_at FROM training_predictions WHERE project = ?")
    params: List[Any] = [_project(config)]
    if run_id:
        sql += " AND run_id = ?"
        params.append(run_id)

    try:
        rows = _db(_task_dir(config)).execute(sql, params).fetchall()
    except Exception:
        logger.debug("Could not read training predictions", exc_info=True)
        return []

    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            logger.warning("Skipping unparseable prediction for %s/%s",
                           row["instance_id"], row["schema_name"])
            continue
        out.append({
            "instance_id": row["instance_id"],
            "schema_name": row["schema_name"],
            "run_id": row["run_id"],
            "payload": payload,
            "confidence": row["confidence"],
            "created_at": row["created_at"],
        })
    return out


def predictions_for_instance(config: Dict[str, Any], instance_id: str
                             ) -> Dict[str, Any]:
    """``{schema_name: payload}`` for one instance."""
    try:
        rows = _db(_task_dir(config)).execute(
            "SELECT schema_name, payload FROM training_predictions "
            "WHERE project = ? AND instance_id = ?",
            (_project(config), instance_id)).fetchall()
    except Exception:
        return {}

    out = {}
    for row in rows:
        try:
            out[row["schema_name"]] = json.loads(row["payload"])
        except (TypeError, ValueError):
            continue
    return out


def delete_predictions_for_run(config: Dict[str, Any], run_id: str) -> int:
    """Retract a run's predictions -- the undo for a bad write-back."""
    conn = _db(_task_dir(config))
    cur = conn.execute(
        "DELETE FROM training_predictions WHERE project = ? AND run_id = ?",
        (_project(config), run_id))
    conn.commit()
    return cur.rowcount or 0
