"""
Reads and writes against ``engine.sqlite``.

``EngineStore`` is the only code that writes SQL for the engine. Everything
else passes records from ``labeling_engine.model``.

The connection is the process-wide cached one from ``potato.persistence``,
shared by the runner's worker threads and Flask's request threads. A
connection is safe to use from several threads, but a transaction on it is
not, so every multi-statement write takes ``self._lock``.
"""

from __future__ import annotations

import itertools
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from potato.persistence import get_db, register_migration

from ..model.records import (
    Budget,
    Certificate,
    ContractVersion,
    HumanRequest,
    ModelCall,
    Prediction,
    ResolvedLabel,
    Run,
    SamplingDesign,
    SourceVersion,
    canonical_json,
)
from . import migrations

#: Rows per transaction for bulk writes. Large enough to amortize the commit,
#: small enough that a reader is never blocked for long.
BATCH = 1000

_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(task_dir: str) -> threading.RLock:
    import os
    key = os.path.abspath(task_dir)
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.RLock()
        return _LOCKS[key]


def _dumps(value: Any) -> Optional[str]:
    return None if value is None else canonical_json(value)


def _loads(text: Optional[str], default: Any = None) -> Any:
    if text is None:
        return default
    return json.loads(text)


def _chunks(rows: Sequence[Any], size: int = BATCH) -> Iterator[Sequence[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


class EngineStore:
    """The engine's tables for one study (one ``task_dir``)."""

    #: Distinguishes several lock holders in one process (writer_name).
    _writer_seq = itertools.count(1)

    def __init__(self, task_dir: str):
        self.task_dir = task_dir
        self._lock = _lock_for(task_dir)

    @property
    def conn(self) -> sqlite3.Connection:
        # Looked up each time, so a close_db() between calls reopens cleanly.
        # Re-registering is a no-op normally, and restores the tables' migration
        # after a test has cleared the process-global registry.
        for m in migrations.MIGRATIONS:
            register_migration(m)
        return get_db(self.task_dir, database=migrations.DATABASE)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN ... COMMIT under the store lock; ROLLBACK on error."""
        with self._lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    # === Items ===============================================================

    def upsert_items(self, items: Iterable[Dict[str, Any]]) -> int:
        """Insert or update ``engine_item`` rows.

        Each dict has ``item_id`` and any of ``content_hash``, ``stratum`` and
        ``meta`` (merged into the stored meta, not replacing it). New items get
        the next ``ingest_seq``.
        """
        rows = list(items)
        n = 0
        for chunk in _chunks(rows):
            with self.transaction() as conn:
                seq = conn.execute(
                    "SELECT COALESCE(MAX(ingest_seq), 0) FROM engine_item").fetchone()[0]
                for row in chunk:
                    iid = str(row["item_id"])
                    old = conn.execute(
                        "SELECT meta_json FROM engine_item WHERE item_id = ?",
                        (iid,)).fetchone()
                    if old is None:
                        seq += 1
                        conn.execute(
                            "INSERT INTO engine_item (item_id, content_hash, ingest_seq,"
                            " stratum, meta_json) VALUES (?, ?, ?, ?, ?)",
                            (iid, row.get("content_hash"), seq, row.get("stratum"),
                             canonical_json(row.get("meta") or {})))
                    else:
                        meta = _loads(old["meta_json"], {})
                        meta.update(row.get("meta") or {})
                        conn.execute(
                            "UPDATE engine_item SET"
                            " content_hash = COALESCE(?, content_hash),"
                            " stratum = COALESCE(?, stratum), meta_json = ?"
                            " WHERE item_id = ?",
                            (row.get("content_hash"), row.get("stratum"),
                             canonical_json(meta), iid))
                    n += 1
        return n

    def get_item_meta(self, item_id: str) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT meta_json FROM engine_item WHERE item_id = ?", (item_id,)).fetchone()
        return _loads(row["meta_json"], {}) if row else {}

    def get_items_meta(self, item_ids: Sequence[str], key: Optional[str] = None
                       ) -> Dict[str, Any]:
        """item_id -> meta (or meta[key]) for the given items that exist."""
        out: Dict[str, Any] = {}
        for chunk in _chunks([str(i) for i in item_ids], 500):
            marks = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                    f"SELECT item_id, meta_json FROM engine_item WHERE item_id IN ({marks})",
                    chunk):
                meta = _loads(row["meta_json"], {})
                out[row["item_id"]] = meta if key is None else meta.get(key)
        return out

    def all_item_ids(self) -> List[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT item_id FROM engine_item ORDER BY ingest_seq")]

    def items_with_meta_key(self, key: str) -> Dict[str, Any]:
        """item_id -> meta[key] for every item whose meta has ``key``."""
        return {
            row["item_id"]: _loads(row["meta_json"], {})[key]
            for row in self.conn.execute(
                "SELECT item_id, meta_json FROM engine_item"
                " WHERE json_type(meta_json, ?) IS NOT NULL", (f"$.{key}",))
        }

    def item_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM engine_item").fetchone()[0]

    # === Sources =============================================================

    def register_source_version(self, sv: SourceVersion) -> str:
        """Record a source version (idempotent) and return its id."""
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO source_version (version_id, source_id, kind,"
                " model, endpoint_type, revision, params_json, prompt_template_hash,"
                " code_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sv.version_id, sv.source_id, sv.kind, sv.model, sv.endpoint_type,
                 sv.revision, canonical_json(sv.params), sv.prompt_template_hash,
                 sv.code_version, sv.created_at))
        return sv.version_id

    def get_source_version(self, version_id: str) -> Optional[SourceVersion]:
        row = self.conn.execute(
            "SELECT * FROM source_version WHERE version_id = ?", (version_id,)).fetchone()
        if row is None:
            return None
        return SourceVersion(
            source_id=row["source_id"], kind=row["kind"], model=row["model"] or "",
            endpoint_type=row["endpoint_type"] or "", revision=row["revision"] or "",
            params=_loads(row["params_json"], {}),
            prompt_template_hash=row["prompt_template_hash"] or "",
            code_version=row["code_version"] or "", version_id=row["version_id"],
            created_at=row["created_at"])

    # === Runs ================================================================

    def start_run(self, run: Run) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO run (kind, source_version_id, config_hash, status,"
                " cursor_json, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                (run.kind, run.source_version_id, run.config_hash,
                 run.status if run.status != "pending" else "running",
                 canonical_json(run.cursor), run.started_at))
            run.id = cur.lastrowid
            run.status = "running" if run.status == "pending" else run.status
        return run.id

    def update_run(self, run_id: int, status: Optional[str] = None,
                   cursor: Optional[Dict[str, Any]] = None,
                   error: Optional[str] = None) -> None:
        sets, args = [], []
        if status is not None:
            sets.append("status = ?")
            args.append(status)
            if status in ("done", "failed", "cancelled"):
                sets.append("finished_at = ?")
                args.append(time.time())
        if cursor is not None:
            sets.append("cursor_json = ?")
            args.append(canonical_json(cursor))
        if error is not None:
            sets.append("error = ?")
            args.append(error)
        if not sets:
            return
        with self._lock:
            self.conn.execute(f"UPDATE run SET {', '.join(sets)} WHERE id = ?",
                              (*args, run_id))

    def get_run(self, run_id: int) -> Optional[Run]:
        row = self.conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run(kind=row["kind"], source_version_id=row["source_version_id"],
                   config_hash=row["config_hash"] or "", status=row["status"],
                   cursor=_loads(row["cursor_json"], {}), id=row["id"],
                   started_at=row["started_at"], finished_at=row["finished_at"],
                   error=row["error"])

    def run_status(self, run_id: int) -> Optional[str]:
        row = self.conn.execute("SELECT status FROM run WHERE id = ?", (run_id,)).fetchone()
        return row["status"] if row else None

    # === Predictions (append-only) ==========================================

    def add_predictions(self, predictions: Sequence[Prediction]) -> List[int]:
        """Append predictions. Nothing is ever updated or replaced."""
        ids: List[int] = []
        for chunk in _chunks(list(predictions)):
            with self.transaction() as conn:
                for p in chunk:
                    cur = conn.execute(
                        "INSERT INTO prediction (item_id, schema_name, source_version_id,"
                        " run_id, value_json, status, raw_conf, conf_json, calibrated_conf,"
                        " calibrator_id, call_ids_json, reasoning, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(p.item_id), p.schema, p.source_version_id, p.run_id,
                         _dumps(p.value), p.status, p.raw_conf, _dumps(p.conf),
                         p.calibrated_conf, p.calibrator_id, canonical_json(p.call_ids),
                         p.reasoning, p.created_at))
                    p.id = cur.lastrowid
                    ids.append(p.id)
        return ids

    @staticmethod
    def _prediction(row: sqlite3.Row) -> Prediction:
        return Prediction(
            item_id=row["item_id"], schema=row["schema_name"],
            source_version_id=row["source_version_id"],
            value=_loads(row["value_json"]), status=row["status"],
            raw_conf=row["raw_conf"], conf=_loads(row["conf_json"]),
            calibrated_conf=row["calibrated_conf"], calibrator_id=row["calibrator_id"],
            call_ids=_loads(row["call_ids_json"], []), run_id=row["run_id"],
            reasoning=row["reasoning"], id=row["id"], created_at=row["created_at"])

    def current_predictions(self, schema: str, source_version_id: str,
                            item_ids: Optional[Sequence[str]] = None
                            ) -> Dict[str, Prediction]:
        """item_id -> latest prediction from one source version on one schema."""
        sql = ("SELECT p.* FROM prediction p JOIN ("
               " SELECT item_id, MAX(id) AS mid FROM prediction"
               " WHERE schema_name = ? AND source_version_id = ?")
        args: List[Any] = [schema, source_version_id]
        out: Dict[str, Prediction] = {}
        if item_ids is None:
            rows = self.conn.execute(
                sql + " GROUP BY item_id) m ON p.id = m.mid", args).fetchall()
            for row in rows:
                out[row["item_id"]] = self._prediction(row)
            return out
        for chunk in _chunks([str(i) for i in item_ids], 500):
            marks = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                sql + f" AND item_id IN ({marks}) GROUP BY item_id) m ON p.id = m.mid",
                [*args, *chunk]).fetchall()
            for row in rows:
                out[row["item_id"]] = self._prediction(row)
        return out

    #: Error answers after which an item is not asked again by this version.
    MAX_ERROR_ATTEMPTS = 3

    def predicted_item_ids(self, schema: str, source_version_id: str) -> set:
        """Items this version has answered, for resume: ok or abstain.

        An item whose only predictions are errors has not been answered (the
        call timed out, the server was down) and is retried by the next run,
        up to MAX_ERROR_ATTEMPTS. After that it counts as done: a wrong key,
        a dead server or a model that answers off the label list would
        otherwise be paid for on every planner pass. A changed source (a
        fixed key or prompt) is a new version and asks again.
        An abstention is an answer and is not retried.
        """
        answered = {r[0] for r in self.conn.execute(
            "SELECT DISTINCT item_id FROM prediction"
            " WHERE schema_name = ? AND source_version_id = ?"
            " AND status IN ('ok', 'abstain')",
            (schema, source_version_id))}
        given_up = {r[0] for r in self.conn.execute(
            "SELECT item_id FROM prediction WHERE schema_name = ? AND source_version_id = ?"
            " AND status = 'error' GROUP BY item_id HAVING COUNT(*) >= ?",
            (schema, source_version_id, self.MAX_ERROR_ATTEMPTS))}
        return answered | given_up

    def prediction_history(self, item_id: str, schema: str) -> List[Prediction]:
        rows = self.conn.execute(
            "SELECT * FROM prediction WHERE item_id = ? AND schema_name = ? ORDER BY id",
            (str(item_id), schema)).fetchall()
        return [self._prediction(r) for r in rows]

    def get_prediction(self, prediction_id: int) -> Optional[Prediction]:
        row = self.conn.execute(
            "SELECT * FROM prediction WHERE id = ?", (prediction_id,)).fetchone()
        return self._prediction(row) if row else None

    def prediction_count(self, source_version_id: Optional[str] = None) -> int:
        if source_version_id is None:
            return self.conn.execute("SELECT COUNT(*) FROM prediction").fetchone()[0]
        return self.conn.execute(
            "SELECT COUNT(*) FROM prediction WHERE source_version_id = ?",
            (source_version_id,)).fetchone()[0]

    # === Model calls (the audit log) ========================================

    def add_calls(self, calls: Sequence[ModelCall]) -> List[int]:
        ids: List[int] = []
        for chunk in _chunks(list(calls)):
            with self.transaction() as conn:
                for c in chunk:
                    cur = conn.execute(
                        "INSERT INTO model_call (run_id, source_version_id, endpoint_type,"
                        " model, revision, prompt_hash, input_hash, response_hash,"
                        " sample_idx, started_at, latency_ms, input_tokens, output_tokens,"
                        " cost_usd, estimated, cache_hit, redaction_json, error, payload_ref)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (c.run_id, c.source_version_id, c.endpoint_type, c.model,
                         c.revision, c.prompt_hash, c.input_hash, c.response_hash,
                         c.sample_idx, c.started_at, c.latency_ms, c.input_tokens,
                         c.output_tokens, c.cost_usd, int(bool(c.estimated)),
                         int(bool(c.cache_hit)), _dumps(c.redaction), c.error,
                         c.payload_ref))
                    c.id = cur.lastrowid
                    ids.append(c.id)
        return ids

    def calls(self, run_id: Optional[int] = None, limit: int = 100,
              offset: int = 0) -> List[ModelCall]:
        where, args = ("WHERE run_id = ?", [run_id]) if run_id is not None else ("", [])
        rows = self.conn.execute(
            f"SELECT * FROM model_call {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*args, limit, offset]).fetchall()
        return [ModelCall(
            source_version_id=r["source_version_id"], endpoint_type=r["endpoint_type"],
            model=r["model"], prompt_hash=r["prompt_hash"], input_hash=r["input_hash"],
            response_hash=r["response_hash"] or "", run_id=r["run_id"],
            revision=r["revision"] or "", sample_idx=r["sample_idx"],
            started_at=r["started_at"], latency_ms=r["latency_ms"],
            input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
            cost_usd=r["cost_usd"], estimated=bool(r["estimated"]),
            cache_hit=bool(r["cache_hit"]), redaction=_loads(r["redaction_json"]),
            error=r["error"], payload_ref=r["payload_ref"], id=r["id"]) for r in rows]

    def call_totals(self) -> Dict[str, Any]:
        """Totals over the whole call log, grouped by source version."""
        rows = self.conn.execute(
            "SELECT source_version_id, model, COUNT(*) AS n,"
            " SUM(cache_hit) AS cache_hits, SUM(COALESCE(input_tokens, 0)) AS tin,"
            " SUM(COALESCE(output_tokens, 0)) AS tout, SUM(cost_usd) AS cost,"
            " SUM(CASE WHEN cost_usd IS NULL AND cache_hit = 0 THEN 1 ELSE 0 END)"
            "   AS unpriced, SUM(estimated) AS n_estimated,"
            " SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors"
            " FROM model_call GROUP BY source_version_id, model").fetchall()
        by_source = [dict(r) for r in rows]
        return {
            "n_calls": sum(r["n"] for r in by_source),
            "cost_usd": sum(r["cost"] or 0.0 for r in by_source),
            "by_source": by_source,
        }

    # === Cache ===============================================================

    def cache_get(self, key: str) -> Optional[bytes]:
        row = self.conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def cache_put(self, key: str, value: bytes) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
                (key, value, time.time()))

    # === Sampling designs and the human request ledger ======================

    def add_design(self, design: SamplingDesign) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO sampling_design (kind, params_json, seed, created_at)"
                " VALUES (?, ?, ?, ?)",
                (design.kind, canonical_json(design.params), design.seed,
                 design.created_at))
            design.id = cur.lastrowid
        return design.id

    def get_design(self, design_id: int) -> Optional[SamplingDesign]:
        row = self.conn.execute(
            "SELECT * FROM sampling_design WHERE id = ?", (design_id,)).fetchone()
        if row is None:
            return None
        return SamplingDesign(kind=row["kind"], params=_loads(row["params_json"], {}),
                              seed=row["seed"], id=row["id"], created_at=row["created_at"])

    def add_requests(self, requests: Sequence[HumanRequest]) -> List[int]:
        ids: List[int] = []
        for chunk in _chunks(list(requests)):
            with self.transaction() as conn:
                for r in chunk:
                    cur = conn.execute(
                        "INSERT INTO human_request (item_id, schema_name, purpose,"
                        " design_id, inclusion_prob, split, visibility,"
                        " shown_prediction_id, pool, eligible_group, assigned_user, status,"
                        " contract_id, priority, label_json, user_id, cost_usd,"
                        " created_at, completed_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(r.item_id), r.schema, r.purpose, r.design_id,
                         r.inclusion_prob, r.split, r.visibility, r.shown_prediction_id,
                         r.pool, r.eligible_group, r.assigned_user, r.status,
                         r.contract_id, r.priority, _dumps(r.label), r.user_id,
                         r.cost_usd, r.created_at, r.completed_at))
                    r.id = cur.lastrowid
                    ids.append(r.id)
        return ids

    @staticmethod
    def _request(row: sqlite3.Row) -> HumanRequest:
        return HumanRequest(
            item_id=row["item_id"], schema=row["schema_name"], purpose=row["purpose"],
            inclusion_prob=row["inclusion_prob"], visibility=row["visibility"],
            split=row["split"], pool=row["pool"], design_id=row["design_id"],
            shown_prediction_id=row["shown_prediction_id"],
            eligible_group=row["eligible_group"], assigned_user=row["assigned_user"],
            status=row["status"], contract_id=row["contract_id"],
            priority=row["priority"], label=_loads(row["label_json"]),
            user_id=row["user_id"], cost_usd=row["cost_usd"], id=row["id"],
            created_at=row["created_at"], completed_at=row["completed_at"],
            assigned_at=row["assigned_at"])

    def get_request(self, request_id: int) -> Optional[HumanRequest]:
        row = self.conn.execute(
            "SELECT * FROM human_request WHERE id = ?", (request_id,)).fetchone()
        return self._request(row) if row else None

    def requests(self, *, status: Optional[Sequence[str]] = None,
                 purpose: Optional[Sequence[str]] = None,
                 schema: Optional[str] = None, item_id: Optional[str] = None,
                 user: Optional[str] = None, pool: Optional[str] = None,
                 split: Optional[str] = None, limit: Optional[int] = None
                 ) -> List[HumanRequest]:
        where, args = [], []
        for col, val in (("status", status), ("purpose", purpose)):
            if val:
                where.append(f"{col} IN ({','.join('?' * len(val))})")
                args.extend(val)
        for col, val in (("schema_name", schema), ("item_id", item_id),
                         ("assigned_user", user), ("pool", pool), ("split", split)):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT * FROM human_request"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY priority DESC, id"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        return [self._request(r) for r in self.conn.execute(sql, args).fetchall()]

    def count_opened_requests(self) -> int:
        """Requests the engine opened (what ``budgets.human_labels`` counts):
        every purpose but organic labels, which nobody asked for, and not
        requests that were cancelled."""
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM human_request"
            " WHERE purpose != 'organic' AND status != 'cancelled'").fetchone()[0])

    def update_request(self, request_id: int, **fields: Any) -> None:
        allowed = {"status", "assigned_user", "label", "user_id", "cost_usd",
                   "completed_at", "priority", "visibility", "shown_prediction_id",
                   "assigned_at"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Cannot update request fields {sorted(bad)}")
        sets, args = [], []
        for k, v in fields.items():
            col = "label_json" if k == "label" else k
            sets.append(f"{col} = ?")
            args.append(_dumps(v) if k == "label" else v)
        with self._lock:
            self.conn.execute(
                f"UPDATE human_request SET {', '.join(sets)} WHERE id = ?",
                (*args, request_id))

    def request_counts(self) -> Dict[str, Dict[str, int]]:
        """purpose -> status -> count."""
        out: Dict[str, Dict[str, int]] = {}
        for r in self.conn.execute(
                "SELECT purpose, status, COUNT(*) AS n FROM human_request"
                " GROUP BY purpose, status"):
            out.setdefault(r["purpose"], {})[r["status"]] = r["n"]
        return out

    # === Resolved labels =====================================================

    def set_resolved(self, labels: Sequence[ResolvedLabel]) -> None:
        """Write the current resolved label and append it to the history."""
        for chunk in _chunks(list(labels)):
            with self.transaction() as conn:
                for lab in chunk:
                    row = (str(lab.item_id), lab.schema, _dumps(lab.value), lab.origin,
                           lab.status, lab.source_version_id,
                           canonical_json(lab.request_ids), lab.contract_version_id,
                           lab.certificate_id, lab.updated_at)
                    conn.execute(
                        "INSERT OR REPLACE INTO resolved_label (item_id, schema_name,"
                        " value_json, origin, status, source_version_id, request_ids_json,"
                        " contract_version_id, certificate_id, updated_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
                    conn.execute(
                        "INSERT INTO resolved_label_history (item_id, schema_name,"
                        " value_json, origin, status, source_version_id, request_ids_json,"
                        " contract_version_id, certificate_id, updated_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)

    @staticmethod
    def _resolved(row: sqlite3.Row) -> ResolvedLabel:
        return ResolvedLabel(
            item_id=row["item_id"], schema=row["schema_name"],
            value=_loads(row["value_json"]), origin=row["origin"], status=row["status"],
            source_version_id=row["source_version_id"],
            request_ids=_loads(row["request_ids_json"], []),
            contract_version_id=row["contract_version_id"],
            certificate_id=row["certificate_id"], updated_at=row["updated_at"])

    def resolved(self, schema: Optional[str] = None,
                 status: Optional[Sequence[str]] = None) -> List[ResolvedLabel]:
        where, args = [], []
        if schema is not None:
            where.append("schema_name = ?")
            args.append(schema)
        if status:
            where.append(f"status IN ({','.join('?' * len(status))})")
            args.extend(status)
        sql = "SELECT * FROM resolved_label"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [self._resolved(r) for r in self.conn.execute(sql, args).fetchall()]

    def resolved_history(self, item_id: str, schema: str) -> List[ResolvedLabel]:
        rows = self.conn.execute(
            "SELECT * FROM resolved_label_history WHERE item_id = ? AND schema_name = ?"
            " ORDER BY id", (str(item_id), schema)).fetchall()
        return [self._resolved(r) for r in rows]

    def mark_resolved_status(self, schema: str, from_status: Sequence[str],
                             to_status: str, origin: Optional[str] = None) -> int:
        """Move labels between statuses (e.g. accepted -> pending_recert)."""
        labels = [lab for lab in self.resolved(schema=schema, status=from_status)
                  if origin is None or lab.origin == origin]
        now = time.time()
        for lab in labels:
            lab.status = to_status
            lab.updated_at = now
        self.set_resolved(labels)
        return len(labels)

    # === Contracts, certificates, budgets ===================================

    def add_contract_version(self, cv: ContractVersion) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO contract_version (contract_id, kind, params_json,"
                " cascade_hash, looks, status, result_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cv.contract_id, cv.kind, canonical_json(cv.params), cv.cascade_hash,
                 cv.looks, cv.status, canonical_json(cv.result), cv.created_at))
            cv.id = cur.lastrowid
        return cv.id

    def latest_contract_version(self, contract_id: str) -> Optional[ContractVersion]:
        row = self.conn.execute(
            "SELECT * FROM contract_version WHERE contract_id = ? ORDER BY id DESC LIMIT 1",
            (contract_id,)).fetchone()
        if row is None:
            return None
        return ContractVersion(
            contract_id=row["contract_id"], kind=row["kind"],
            params=_loads(row["params_json"], {}), cascade_hash=row["cascade_hash"],
            status=row["status"], looks=row["looks"], result=_loads(row["result_json"], {}),
            id=row["id"], created_at=row["created_at"])

    def source_health(self, scheme: str, version_id: str) -> Dict[str, Any]:
        """Prediction counts by status for one source version on one scheme,
        and its latest run's status and message."""
        counts = {row[0]: row[1] for row in self.conn.execute(
            "SELECT status, COUNT(*) FROM prediction WHERE schema_name = ?"
            " AND source_version_id = ? GROUP BY status", (scheme, version_id))}
        run = self.conn.execute(
            "SELECT status, error FROM run WHERE source_version_id = ? AND kind = 'predict'"
            " ORDER BY id DESC LIMIT 1", (version_id,)).fetchone()
        last_error = self.conn.execute(
            "SELECT reasoning FROM prediction WHERE schema_name = ? AND source_version_id = ?"
            " AND status = 'error' ORDER BY id DESC LIMIT 1", (scheme, version_id)).fetchone()
        return {"ok": counts.get("ok", 0), "abstain": counts.get("abstain", 0),
                "error": counts.get("error", 0),
                "last_error": last_error[0] if last_error else None,
                "last_run": ({"status": run[0], "message": run[1]} if run else None)}

    def contract_versions(self, contract_id: str, cascade_hash: str) -> List[ContractVersion]:
        """Every stored result for this contract on this cascade, newest first."""
        rows = self.conn.execute(
            "SELECT * FROM contract_version WHERE contract_id = ? AND cascade_hash = ?"
            " ORDER BY id DESC", (contract_id, cascade_hash)).fetchall()
        return [ContractVersion(
            contract_id=r["contract_id"], kind=r["kind"], params=_loads(r["params_json"], {}),
            cascade_hash=r["cascade_hash"], status=r["status"], looks=r["looks"],
            result=_loads(r["result_json"], {}), id=r["id"], created_at=r["created_at"])
            for r in rows]

    def looks_used(self, contract_id: str, cascade_hash: Optional[str] = None) -> int:
        """Certification looks already spent on this contract.

        Counted across every cascade: a changed prompt or temperature tested
        on the same cert labels is another test of them, so trying versions
        until one passes must not get each one the first look's level.
        ``cascade_hash`` narrows the count (reporting only).
        """
        sql = "SELECT COALESCE(MAX(looks), 0) FROM contract_version WHERE contract_id = ?"
        args: list = [contract_id]
        if cascade_hash is not None:
            sql += " AND cascade_hash = ?"
            args.append(cascade_hash)
        return int(self.conn.execute(sql, args).fetchone()[0])

    def looks_used_by_others(self, kind: str, scheme: str, exclude_ids: Sequence[str]) -> int:
        """Looks spent by contracts of ``kind`` on ``scheme`` whose ids are not
        in ``exclude_ids`` (the ids the config still has).

        A renamed contract is the same claim on the same cert labels. Counting
        only its new id would give it the first look's level again, so renaming
        and retrying would undo the look count."""
        rows = self.conn.execute(
            "SELECT contract_id, MAX(looks), result_json FROM contract_version"
            " WHERE kind = ? GROUP BY contract_id", (kind,)).fetchall()
        used = 0
        for cid, looks, result_json in rows:
            if cid in exclude_ids:
                continue
            try:
                if (json.loads(result_json or "{}") or {}).get("scheme") != scheme:
                    continue
            except ValueError:
                continue
            used = max(used, int(looks or 0))
        return used

    def add_certificate(self, cert: Certificate) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO certificate (cascade_hash, dataset_hash,"
                " contract_version_ids_json, sections_json, budget_json, content_sha256,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cert.cascade_hash, cert.dataset_hash,
                 canonical_json(cert.contract_version_ids), canonical_json(cert.sections),
                 canonical_json(cert.budget), cert.content_sha256, cert.created_at))
            cert.id = cur.lastrowid
        return cert.id

    def latest_certificate(self) -> Optional[Certificate]:
        row = self.conn.execute(
            "SELECT * FROM certificate ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return Certificate(
            cascade_hash=row["cascade_hash"], dataset_hash=row["dataset_hash"],
            contract_version_ids=_loads(row["contract_version_ids_json"], []),
            sections=_loads(row["sections_json"], {}),
            budget=_loads(row["budget_json"], {}), content_sha256=row["content_sha256"],
            id=row["id"], created_at=row["created_at"])

    def set_budget(self, budget: Budget) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO budget (kind, scope, limit_val, spent) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(kind, scope) DO UPDATE SET limit_val = excluded.limit_val",
                (budget.kind, budget.scope, budget.limit, budget.spent))

    def add_spend(self, kind: str, amount: float, scope: str = "study") -> float:
        """Add to a budget's spent total and return the new total."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO budget (kind, scope, limit_val, spent) VALUES (?, ?, NULL, 0)"
                " ON CONFLICT(kind, scope) DO NOTHING", (kind, scope))
            conn.execute("UPDATE budget SET spent = spent + ? WHERE kind = ? AND scope = ?",
                         (float(amount), kind, scope))
            return conn.execute(
                "SELECT spent FROM budget WHERE kind = ? AND scope = ?",
                (kind, scope)).fetchone()[0]

    def get_budget(self, kind: str, scope: str = "study") -> Optional[Budget]:
        row = self.conn.execute(
            "SELECT * FROM budget WHERE kind = ? AND scope = ?", (kind, scope)).fetchone()
        if row is None:
            return None
        return Budget(kind=row["kind"], scope=row["scope"], limit=row["limit_val"],
                      spent=row["spent"])

    # === Key-value state ====================================================

    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value_json FROM engine_kv WHERE key = ?",
                                (key,)).fetchone()
        return _loads(row["value_json"]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO engine_kv (key, value_json, updated_at)"
                " VALUES (?, ?, ?)", (key, canonical_json(value), time.time()))

    # === Writer lock =========================================================

    @staticmethod
    def writer_name(kind: str) -> str:
        """A lock holder name that says where it runs: ``kind:host:pid:n``.
        acquire_writer reads host and pid back to take over from a holder
        that was killed without releasing the lock."""
        import os
        import socket
        n = next(EngineStore._writer_seq)
        return f"{kind}:{socket.gethostname()}:{os.getpid()}:{n}"

    @staticmethod
    def _holder_is_dead(holder: str) -> bool:
        """True when the holder ran on this host in a process that is gone."""
        import os
        import socket
        parts = str(holder).split(":")
        if len(parts) < 4 or parts[1] != socket.gethostname():
            return False
        try:
            pid = int(parts[2])
        except ValueError:
            return False
        if pid == os.getpid():
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def acquire_writer(self, holder: str, stale_after: float = 120.0,
                       name: str = "runner") -> bool:
        """Take the single-writer lock unless a live holder has it.

        A holder that has not heartbeated within ``stale_after`` seconds is
        taken over, so a crashed CLI run does not lock a study forever; so is
        one whose process on this host has exited (a killed server), at once.
        """
        now = time.time()
        with self.transaction() as conn:
            row = conn.execute("SELECT holder, heartbeat FROM writer_lock WHERE name = ?",
                               (name,)).fetchone()
            if row is not None and row["holder"] != holder \
                    and now - row["heartbeat"] < stale_after \
                    and not self._holder_is_dead(row["holder"]):
                return False
            conn.execute(
                "INSERT OR REPLACE INTO writer_lock (name, holder, acquired_at, heartbeat)"
                " VALUES (?, ?, ?, ?)", (name, holder, now, now))
            return True

    def heartbeat_writer(self, holder: str, name: str = "runner") -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE writer_lock SET heartbeat = ? WHERE name = ? AND holder = ?",
                (time.time(), name, holder))

    def release_writer(self, holder: str, name: str = "runner") -> None:
        with self._lock:
            self.conn.execute("DELETE FROM writer_lock WHERE name = ? AND holder = ?",
                              (name, holder))

    @contextmanager
    def holding_writer(self, holder: str, every: float = 20.0, name: str = "runner"):
        """Heartbeat the lock from a thread while the body runs. A tick
        longer than the takeover time otherwise lost the lock to a second
        driver halfway through, and both made the same paid calls."""
        stop = threading.Event()

        def beat():
            while not stop.wait(every):
                try:
                    self.heartbeat_writer(holder, name)
                except Exception:
                    pass
        t = threading.Thread(target=beat, name="engine-writer-heartbeat", daemon=True)
        self.heartbeat_writer(holder, name)
        t.start()
        try:
            yield
        finally:
            stop.set()

    def live_writer(self, stale_after: float = 120.0, name: str = "runner") -> Optional[str]:
        """The holder of the lock if it is alive, else None."""
        row = self.conn.execute("SELECT holder, heartbeat FROM writer_lock WHERE name = ?",
                                (name,)).fetchone()
        if row is None or time.time() - row["heartbeat"] >= stale_after \
                or self._holder_is_dead(row["holder"]):
            return None
        return row["holder"]

    def writer_holder(self, name: str = "runner") -> Optional[str]:
        row = self.conn.execute("SELECT holder FROM writer_lock WHERE name = ?",
                                (name,)).fetchone()
        return row["holder"] if row else None
