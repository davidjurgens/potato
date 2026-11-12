"""
Send Potato's judgement of an ingested trace back to Langfuse or LangSmith.

A trace that came in through the webhook receiver or the Langfuse poller keeps
where it came from in its item data (``metadata.source`` and
``metadata.original_id``). Once enough people have annotated it, or an
adjudicator has decided it, each scheme's merged answer goes back to that
trace: a Langfuse score or a LangSmith feedback, with the annotator count and
how far they agreed in the comment and metadata.

Delivery is a small SQLite queue in the task directory, one row per (target,
item, scheme), worked by a background thread with exponential backoff, so a
tracing service that is down for an hour loses nothing and an annotator's save
never waits on it. A payload identical to the one already delivered is not
sent again.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sqlite3
import statistics
import threading
import time
import uuid
from collections import Counter
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TARGETS = ("langfuse", "langsmith")
QUEUE_FILE = "trace_writeback.sqlite"
MAX_ATTEMPTS = 8
#: Not values: what the page stores beside an answer.
_NOT_ANSWERS = {"free_response", "bad_text", "text_box"}
_NAMESPACE = uuid.UUID("6f0f2b0e-6f6a-4b9b-9a51-7a3b8f1c2d40")


# ---------------------------------------------------------------------------
# What to send
# ---------------------------------------------------------------------------

def trace_target(item_data: Any) -> Optional[Tuple[str, str]]:
    """``(target, trace id)`` for an ingested trace, else None."""
    if not isinstance(item_data, dict):
        return None
    meta = item_data.get("metadata") or {}
    source = str(meta.get("source") or "").lower()
    original = meta.get("original_id")
    if source in TARGETS and original:
        return source, str(original)
    return None


def _answer(kind: str, labels: Dict[str, Any]) -> Any:
    """One annotator's stored labels for one scheme -> a comparable answer."""
    chosen = {n: v for n, v in labels.items()
              if n not in _NOT_ANSWERS and v not in (None, False, "", "false")}
    if not chosen:
        return None
    if kind == "multiselect":
        return tuple(sorted(chosen))
    if kind in ("slider", "number"):
        try:
            return float(next(iter(chosen.values())))
        except (TypeError, ValueError):
            return None
    return sorted(chosen)[-1]


def summarize(scheme: dict, answers: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The value to send for one scheme, or None when there is nothing to send.

    ``answers`` is ``{annotator: answer}`` as built by :func:`_answer`.
    """
    kind = scheme.get("annotation_type")
    answers = {u: a for u, a in answers.items() if a is not None}
    if not answers:
        return None
    n = len(answers)
    values = list(answers.values())
    pairs = list(combinations(values, 2))
    agreement = (sum(a == b for a, b in pairs) / len(pairs)) if pairs else None

    if kind in ("slider", "number") or (kind == "likert" and not scheme.get("labels")
                                         and all(_is_number(v) for v in values)):
        numbers = [float(v) for v in values]
        value = statistics.median(numbers) if kind == "likert" else statistics.fmean(numbers)
        spread = statistics.pstdev(numbers) if n > 1 else 0.0
        how = "median" if kind == "likert" else "mean"
        return {"data_type": "NUMERIC", "value": round(value, 4), "n": n,
                "comment": f"Potato: {how} of {n} annotator(s), spread (SD) {spread:.2f}",
                "metadata": {"annotators": n, "statistic": how, "sd": round(spread, 4),
                             "values": sorted(numbers)}}

    if kind == "multiselect":
        votes = Counter(c for classes in values for c in classes)
        merged = sorted(c for c, k in votes.items() if k * 2 > n)
        value = ", ".join(merged) if merged else "none"
        return {"data_type": "CATEGORICAL", "value": value, "n": n,
                "comment": f"Potato: classes chosen by more than half of {n} annotator(s)",
                "metadata": {"annotators": n, "votes": dict(votes),
                             "pairwise_agreement": agreement}}

    if kind in ("radio", "select", "likert"):
        counts = Counter(str(v) for v in values).most_common()
        if len(counts) > 1 and counts[0][1] == counts[1][1]:
            return None  # a tie is not an answer; adjudication can settle it
        label, k = counts[0]
        return {"data_type": "CATEGORICAL", "value": label, "n": n,
                "comment": f"Potato: {k} of {n} annotator(s) chose {label}",
                "metadata": {"annotators": n, "distribution": dict(counts),
                             "pairwise_agreement": agreement}}
    return None


def held_reason(scheme: dict, answers: Dict[str, Any]) -> Optional[str]:
    """Why a scheme with answers produced nothing to send, if it is a tie."""
    if scheme.get("annotation_type") not in ("radio", "select", "likert"):
        return None
    values = [str(a) for a in answers.values() if a is not None]
    counts = Counter(values).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        spread = ", ".join(f"{label} {k}" for label, k in sorted(counts))
        return f"tie: {spread}; adjudicate to send"
    return None


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def item_answers(instance_id: str, schemes: List[dict]) -> Dict[str, Dict[str, Any]]:
    """``{scheme name: {annotator: answer}}`` from every annotator's saved state."""
    from potato.item_state_management import get_item_state_manager
    from potato.user_state_management import get_user_state_manager

    usm = get_user_state_manager()
    kinds = {s["name"]: s.get("annotation_type") for s in schemes}
    out: Dict[str, Dict[str, Any]] = {name: {} for name in kinds}
    for user in sorted(get_item_state_manager().get_annotators_for_item(instance_id) or []):
        state = usm.get_user_state(user)
        if state is None:
            continue
        per_scheme: Dict[str, Dict[str, Any]] = {}
        for label, value in (state.get_label_annotations(instance_id) or {}).items():
            schema = label.get_schema() if hasattr(label, "get_schema") else None
            if schema in kinds:
                per_scheme.setdefault(schema, {})[label.get_name()] = value
        for schema, labels in per_scheme.items():
            answer = _answer(kinds[schema], labels)
            if answer is not None:
                out[schema][user] = answer
    return out


def _step_types():
    from potato.server_utils.iaa.structured import TRACE_TYPES
    return TRACE_TYPES


#: process_reward stores a step's reward as a number; Langfuse shows the word.
_REWARD_NAMES = {"1": "correct", "-1": "incorrect", "0": "neutral"}


def step_answers(instance_id: str, scheme: dict) -> Dict[str, Dict[str, str]]:
    """``{annotator: {step index: label}}`` for a step-level trace scheme."""
    from potato.item_state_management import get_item_state_manager
    from potato.step_agreement import steps_from_stored
    from potato.user_state_management import get_user_state_manager

    usm = get_user_state_manager()
    out: Dict[str, Dict[str, str]] = {}
    for user in sorted(get_item_state_manager().get_annotators_for_item(instance_id) or []):
        state = usm.get_user_state(user)
        if state is None:
            continue
        for label, value in (state.get_label_annotations(instance_id) or {}).items():
            if (label.get_schema() if hasattr(label, "get_schema") else None) != scheme["name"]:
                continue
            steps = steps_from_stored(value)
            if steps:
                names = _REWARD_NAMES if scheme.get("annotation_type") == "process_reward" else {}
                out[user] = {str(k): names.get(str(v), str(v)) for k, v in steps.items()}
                break
    return out


def summarize_steps(answers: Dict[str, Dict[str, str]], min_annotators: int) -> Dict[str, Dict[str, Any]]:
    """``{step index: summary}`` for the steps ``min_annotators`` people labelled.

    The majority label per step, like a radio scheme; a tied step is not sent.
    """
    by_step: Dict[str, List[str]] = {}
    for steps in answers.values():
        for index, label in steps.items():
            by_step.setdefault(index, []).append(label)
    out = {}
    for index, labels in by_step.items():
        n = len(labels)
        if n < min_annotators:
            continue
        counts = Counter(labels).most_common()
        if len(counts) > 1 and counts[0][1] == counts[1][1]:
            continue
        pairs = list(combinations(labels, 2))
        label, k = counts[0]
        out[index] = {"data_type": "CATEGORICAL", "value": label, "n": n,
                      "comment": f"Potato: {k} of {n} annotator(s) chose {label} for this step",
                      "metadata": {"annotators": n, "distribution": dict(counts), "step_index": int(index),
                                   "pairwise_agreement": sum(a == b for a, b in pairs) / len(pairs)}}
    return out


def _observation_ids(item_data: Any, scheme: dict) -> Dict[str, str]:
    """``{step index: Langfuse observation id}`` from an ingested trace's steps."""
    steps = (item_data or {}).get(scheme.get("steps_key") or "steps") if isinstance(item_data, dict) else None
    out = {}
    for position, step in enumerate(steps or []):
        if isinstance(step, dict):
            obs = (step.get("metadata") or {}).get("observation_id")
            if obs:
                out[str(step.get("step_index", position))] = str(obs)
    return out


def adjudicated_value(scheme: dict, decided: Any) -> Optional[Dict[str, Any]]:
    """An adjudicator's decision for one scheme, in the shape :func:`summarize` returns."""
    kind = scheme.get("annotation_type")
    if isinstance(decided, dict):
        chosen = sorted(str(k) for k, v in decided.items() if v not in (False, None, "", 0, "false"))
    elif isinstance(decided, (list, tuple, set)):
        chosen = sorted(str(v) for v in decided)
    elif decided in (None, ""):
        chosen = []
    else:
        chosen = [str(decided)]
    if not chosen:
        return None
    if kind in ("slider", "number") and _is_number(chosen[0]):
        return {"data_type": "NUMERIC", "value": float(chosen[0]), "n": None,
                "comment": "Potato: adjudicated", "metadata": {"adjudicated": True}}
    value = ", ".join(chosen) if kind == "multiselect" else chosen[0]
    return {"data_type": "CATEGORICAL", "value": value, "n": None,
            "comment": "Potato: adjudicated", "metadata": {"adjudicated": True}}


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

def score_id(target: str, instance_id: str, scheme: str) -> str:
    """The same id every time for one trace and scheme, so a re-send updates."""
    return str(uuid.uuid5(_NAMESPACE, f"{target}:{instance_id}:{scheme}"))


def langfuse_score(trace_id: str, name: str, summary: Dict[str, Any], *,
                   instance_id: str, score_uuid: str) -> Dict[str, Any]:
    return {"id": score_uuid, "traceId": trace_id, "name": name,
            "value": summary["value"], "dataType": summary["data_type"],
            "comment": summary["comment"],
            "metadata": {"source": "potato", "potato_item_id": instance_id,
                         **summary["metadata"]}}


def langsmith_feedback(run_id: str, key: str, summary: Dict[str, Any], *,
                       instance_id: str, score_uuid: str) -> Dict[str, Any]:
    body = {"id": score_uuid, "run_id": run_id, "trace_id": run_id, "key": key,
            "comment": summary["comment"],
            "feedback_source": {"type": "api", "metadata": {
                "source": "potato", "potato_item_id": instance_id, **summary["metadata"]}}}
    if summary["data_type"] == "NUMERIC":
        body["score"] = summary["value"]
    else:
        body["value"] = summary["value"]
    return body


def _label_names(scheme: dict) -> List[str]:
    names = []
    for label in scheme.get("labels") or []:
        name = label if isinstance(label, str) else (label or {}).get("name")
        if name is not None:
            names.append(str(name))
    return names


def score_config_spec(scheme: dict, step: bool = False) -> Optional[Dict[str, Any]]:
    """The Langfuse score config a scheme's scores fit, or None.

    Langfuse accepts a score carrying a ``configId`` and then, in its worker,
    drops it if the value is not one of the config's categories -- the client
    gets 202 either way. So a config is only described for schemes whose every
    possible value is a category (or a number within bounds). A multiselect
    sends a comma-joined set, which no category list can hold.
    """
    kind = scheme.get("annotation_type")
    if step:
        if kind != "process_reward":
            return None
        labels = ["correct", "incorrect"] + (["neutral"] if scheme.get("allow_neutral") else [])
        return {"dataType": "CATEGORICAL",
                "categories": [{"label": n, "value": i} for i, n in enumerate(labels)]}
    if kind in ("radio", "select") or (kind == "likert" and scheme.get("labels")):
        labels = _label_names(scheme)
        if not labels:
            return None
        return {"dataType": "CATEGORICAL",
                "categories": [{"label": n, "value": i} for i, n in enumerate(labels)]}
    if kind == "likert":
        return {"dataType": "NUMERIC", "minValue": 1, "maxValue": int(scheme.get("size") or 5)}
    if kind in ("slider", "number"):
        spec: Dict[str, Any] = {"dataType": "NUMERIC"}
        for key, out in (("min_value", "minValue"), ("min", "minValue"),
                         ("max_value", "maxValue"), ("max", "maxValue")):
            if out not in spec and _is_number(scheme.get(key)):
                spec[out] = float(scheme[key])
        return spec
    return None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The resolved write-back settings, or None when write-back is off."""
    ingestion = config.get("trace_ingestion") or {}
    block = ingestion.get("writeback")
    if not ingestion.get("enabled") or not isinstance(block, dict):
        return None
    # `trigger`, not `on`: YAML reads a bare `on:` key as the boolean True.
    trigger = str(block.get("trigger") or "fully_annotated")
    if trigger not in ("fully_annotated", "adjudicated"):
        raise ValueError(f"trace_ingestion.writeback.trigger must be fully_annotated or "
                         f"adjudicated, not {trigger!r}")
    source = next((s for s in ingestion.get("sources") or []
                   if isinstance(s, dict) and s.get("type") == "langfuse"), {})
    lf = block.get("langfuse") or {}
    ls = block.get("langsmith") or {}
    from potato.server_utils.config_module import resolve_num_annotators_per_item
    try:
        cap = resolve_num_annotators_per_item(config)
    except Exception:  # noqa: BLE001 - a bad cap is reported by validation, not here
        cap = -1
    return {
        "trigger": trigger,
        "prefix": str(block.get("score_prefix") or "potato"),
        "min_annotators": int(block.get("min_annotators") or (cap if cap and cap > 0 else 2)),
        "langfuse": {
            "score_configs": bool(lf.get("score_configs", False)),
            "host": str(lf.get("host") or source.get("api_url") or "https://cloud.langfuse.com").rstrip("/"),
            "public_key": os.environ.get(str(lf.get("public_key_env") or "LANGFUSE_PUBLIC_KEY"))
                          or source.get("public_key") or "",
            "secret_key": os.environ.get(str(lf.get("secret_key_env") or "LANGFUSE_SECRET_KEY"))
                          or source.get("secret_key") or source.get("api_key") or "",
        },
        "langsmith": {
            "api_url": str(ls.get("api_url") or "https://api.smith.langchain.com").rstrip("/"),
            "api_key": os.environ.get(str(ls.get("api_key_env") or "LANGSMITH_API_KEY")) or "",
        },
    }


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

class WritebackQueue:
    """One row per (target, item, scheme): the latest payload and its delivery."""

    def __init__(self, db_path: str, cfg: Dict[str, Any], session=None):
        self.db_path = db_path
        self.cfg = cfg
        self._session = session
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        #: Langfuse score config ids by score name (None: not usable).
        self._score_configs: Dict[str, Optional[str]] = {}
        #: Score names whose existing Langfuse config does not match the scheme.
        self.config_mismatches: List[str] = []
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS writeback (
                key TEXT PRIMARY KEY, target TEXT NOT NULL, item_id TEXT NOT NULL,
                scheme TEXT NOT NULL, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0, last_error TEXT DEFAULT '',
                sent_hash TEXT DEFAULT '', updated_at REAL NOT NULL)""")

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    # -- enqueue --------------------------------------------------------------

    def enqueue(self, target: str, item_id: str, scheme: str, payload: Dict[str, Any]) -> bool:
        """Queue a payload. False when it equals what was already delivered."""
        text = json.dumps(payload, sort_keys=True)
        digest = hashlib.sha256(text.encode()).hexdigest()
        key = f"{target}|{item_id}|{scheme}"
        with self._lock, self._connect() as db:
            row = db.execute("SELECT status, sent_hash, payload_hash FROM writeback WHERE key=?",
                             (key,)).fetchone()
            if row and row[0] == "held" and row[1] == digest:
                # Held, and the answer is back to what was already delivered.
                db.execute("UPDATE writeback SET status='sent', last_error='', updated_at=? "
                           "WHERE key=?", (time.time(), key))
                return False
            if row and (row[1] == digest or (row[0] == "pending" and row[2] == digest)):
                return False
            db.execute("""INSERT INTO writeback (key, target, item_id, scheme, payload,
                payload_hash, status, attempts, next_attempt_at, last_error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 0, '', ?)
                ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,
                payload_hash=excluded.payload_hash, status='pending', attempts=0,
                next_attempt_at=0, last_error='', updated_at=excluded.updated_at""",
                       (key, target, item_id, scheme, text, digest, time.time()))
        self._wake.set()
        return True

    def hold(self, target: str, item_id: str, scheme: str, reason: str) -> None:
        """Record that a trace is waiting (a tie, say) so the admin can see why.

        Nothing is sent. A score delivered earlier stays as it is in the
        service; the next answer that settles the vote is queued as usual.
        """
        key = f"{target}|{item_id}|{scheme}"
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO writeback (key, target, item_id, scheme, payload,
                payload_hash, status, attempts, next_attempt_at, last_error, updated_at)
                VALUES (?, ?, ?, ?, '{}', '', 'held', 0, 0, ?, ?)
                ON CONFLICT(key) DO UPDATE SET status='held', payload='{}', payload_hash='',
                last_error=excluded.last_error, updated_at=excluded.updated_at""",
                       (key, target, item_id, scheme, reason, time.time()))

    # -- deliver --------------------------------------------------------------

    def deliver_due(self, now: Optional[float] = None) -> int:
        """Try every pending row whose time has come. Returns how many were sent."""
        now = time.time() if now is None else now
        with self._lock, self._connect() as db:
            rows = db.execute("""SELECT key, target, payload, attempts, sent_hash
                FROM writeback WHERE status='pending' AND next_attempt_at<=?""",
                              (now,)).fetchall()
        sent = 0
        for key, target, text, attempts, sent_hash in rows:
            ok, retry, error = self._send(target, json.loads(text), already_sent=bool(sent_hash))
            with self._lock, self._connect() as db:
                if ok:
                    digest = hashlib.sha256(text.encode()).hexdigest()
                    db.execute("""UPDATE writeback SET status='sent', sent_hash=?,
                        last_error='', updated_at=? WHERE key=? AND payload=?""",
                               (digest, time.time(), key, text))
                    sent += 1
                else:
                    attempts += 1
                    failed = (not retry) or attempts >= MAX_ATTEMPTS
                    db.execute("""UPDATE writeback SET status=?, attempts=?, next_attempt_at=?,
                        last_error=?, updated_at=? WHERE key=? AND payload=?""",
                               ("failed" if failed else "pending", attempts,
                                now + min(3600, 10 * 2 ** attempts), error[:500],
                                time.time(), key, text))
                    logger.warning("Trace write-back to %s failed (%s)%s", target, error,
                                   "" if not failed else "; giving up")
        return sent

    def _send(self, target: str, payload: Dict[str, Any], already_sent: bool) -> Tuple[bool, bool, str]:
        """``(delivered, worth retrying, error)``."""
        try:
            if target == "langfuse":
                return self._send_langfuse(payload)
            return self._send_langsmith(payload, already_sent)
        except Exception as exc:  # noqa: BLE001 - network errors are retried
            return False, True, f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _verdict(response) -> Tuple[bool, bool, str]:
        code = response.status_code
        if 200 <= code < 300:
            return True, False, ""
        retry = code in (408, 429) or code >= 500
        return False, retry, f"HTTP {code}: {response.text[:300]}"

    def _send_langfuse(self, score: Dict[str, Any]) -> Tuple[bool, bool, str]:
        lf = self.cfg["langfuse"]
        if not (lf["public_key"] and lf["secret_key"]):
            return False, False, "no Langfuse keys (set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)"
        token = base64.b64encode(f"{lf['public_key']}:{lf['secret_key']}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
        score = dict(score)
        spec = score.pop("_score_config", None)
        if spec:
            config_id = self._score_config_id(score["name"], spec, headers)
            if config_id:
                score["configId"] = config_id
        url = f"{lf['host']}/api/public/scores"
        response = self.session.post(url, json=[score], headers=headers, timeout=20)
        if response.status_code in (400, 422):
            # Langfuse servers before the batch API take one object.
            response = self.session.post(url, json=score, headers=headers, timeout=20)
        if response.status_code == 207:
            # Partly accepted: Langfuse says not to retry a 207 automatically.
            return False, False, f"HTTP 207: {response.text[:300]}"
        return self._verdict(response)

    def _score_config_id(self, name: str, spec: Dict[str, Any], headers) -> Optional[str]:
        """The id of the Langfuse score config called ``name``, created if missing.

        An existing config whose type or categories differ from ``spec`` is not
        used: Langfuse would silently drop any value outside its categories.
        """
        cache = self._score_configs
        if name in cache:
            return cache[name]
        host = self.cfg["langfuse"]["host"]
        found, page = None, 1
        while found is None:
            response = self.session.get(f"{host}/api/public/score-configs",
                                        params={"page": page, "limit": 100}, headers=headers, timeout=20)
            if response.status_code != 200:
                return None  # not cached: retried with the next score
            body = response.json()
            found = next((c for c in body.get("data") or []
                          if c.get("name") == name and not c.get("isArchived")), None)
            if page >= int((body.get("meta") or {}).get("totalPages") or 1):
                break
            page += 1
        if found is None:
            response = self.session.post(f"{host}/api/public/score-configs", headers=headers, timeout=20,
                                         json={"name": name, "description": "Created by Potato", **spec})
            if response.status_code not in (200, 201):
                return None
            found = response.json()
        if found.get("dataType") != spec["dataType"] or (
                spec.get("categories") is not None
                and sorted(c.get("label") for c in found.get("categories") or [])
                != sorted(c["label"] for c in spec["categories"])):
            logger.warning("Langfuse score config %r does not match the scheme's labels; "
                           "sending %r without a config", name, name)
            self.config_mismatches = sorted(set(self.config_mismatches) | {name})
            cache[name] = None
            return None
        cache[name] = found.get("id")
        return cache[name]

    def _send_langsmith(self, feedback: Dict[str, Any], already_sent: bool) -> Tuple[bool, bool, str]:
        ls = self.cfg["langsmith"]
        if not ls["api_key"]:
            return False, False, "no LangSmith key (set LANGSMITH_API_KEY)"
        headers = {"x-api-key": ls["api_key"], "Content-Type": "application/json"}
        if already_sent:
            update = {k: feedback[k] for k in ("score", "value", "comment") if k in feedback}
            response = self.session.patch(f"{ls['api_url']}/api/v1/feedback/{feedback['id']}",
                                          json=update, headers=headers, timeout=20)
            if response.status_code != 404:
                return self._verdict(response)
        response = self.session.post(f"{ls['api_url']}/api/v1/feedback", json=feedback,
                                     headers=headers, timeout=20)
        return self._verdict(response)

    # -- worker ---------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="trace-writeback")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.deliver_due()
            except Exception:  # noqa: BLE001 - the worker must outlive one bad row
                logger.exception("Trace write-back worker error")
            self._wake.wait(timeout=15)
            self._wake.clear()

    def status(self) -> Dict[str, Any]:
        with self._lock, self._connect() as db:
            counts = dict(db.execute("SELECT status, COUNT(*) FROM writeback GROUP BY status").fetchall())
            failures = db.execute("""SELECT target, item_id, scheme, attempts, last_error, updated_at
                FROM writeback WHERE last_error != '' AND status != 'held'
                ORDER BY updated_at DESC LIMIT 20""").fetchall()
            held = db.execute("""SELECT target, item_id, scheme, last_error, updated_at
                FROM writeback WHERE status = 'held' ORDER BY updated_at DESC LIMIT 50""").fetchall()
        return {"counts": {s: counts.get(s, 0) for s in ("pending", "sent", "failed", "held")},
                "recent_errors": [dict(zip(("target", "item_id", "scheme", "attempts",
                                            "error", "updated_at"), row)) for row in failures],
                "held": [dict(zip(("target", "item_id", "scheme", "reason", "updated_at"), row))
                         for row in held],
                "score_config_mismatches": list(self.config_mismatches)}


# ---------------------------------------------------------------------------
# The process-wide queue and the two hooks
# ---------------------------------------------------------------------------

_QUEUE: Optional[WritebackQueue] = None
_QUEUE_LOCK = threading.Lock()


def get_queue(config: Optional[Dict[str, Any]] = None, start: bool = True) -> Optional[WritebackQueue]:
    """The queue for this study, created on first use; None when write-back is off."""
    global _QUEUE
    if config is None:
        from potato.server_utils.config_module import config as config_
        config = config_
    cfg = settings(config)
    if cfg is None:
        return None
    with _QUEUE_LOCK:
        if _QUEUE is None:
            task_dir = config.get("task_dir") or "."
            _QUEUE = WritebackQueue(os.path.join(task_dir, QUEUE_FILE), cfg)
        if start:
            _QUEUE.start()
        return _QUEUE


def clear_queue() -> None:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is not None:
            _QUEUE.stop()
        _QUEUE = None


def _item_data(instance_id: str) -> Any:
    from potato.item_state_management import get_item_state_manager
    item = get_item_state_manager().get_item(instance_id)
    return item.get_data() if item is not None and hasattr(item, "get_data") else None


def _queue_item(config, queue, cfg, instance_id: str, summaries: Dict[str, Optional[dict]],
                held: Optional[Dict[str, str]] = None,
                step_summaries: Optional[Dict[str, Dict[str, dict]]] = None) -> int:
    item_data = _item_data(instance_id)
    target = trace_target(item_data)
    if target is None:
        return 0
    service, trace_id = target
    schemes_by_name = {s["name"]: s for s in _schemes(config)}
    for scheme, reason in (held or {}).items():
        queue.hold(service, instance_id, scheme, reason)
        logger.info("Trace write-back for %s/%s held: %s", instance_id, scheme, reason)
    queued = 0
    for scheme, summary in summaries.items():
        if summary is None:
            continue
        name = f"{cfg['prefix']}.{scheme}"
        uid = score_id(service, instance_id, scheme)
        payload = (langfuse_score(trace_id, name, summary, instance_id=instance_id, score_uuid=uid)
                   if service == "langfuse" else
                   langsmith_feedback(trace_id, name, summary, instance_id=instance_id, score_uuid=uid))
        if service == "langfuse" and cfg["langfuse"].get("score_configs"):
            spec = score_config_spec(schemes_by_name.get(scheme, {}))
            if spec:
                payload["_score_config"] = spec
        queued += queue.enqueue(service, instance_id, scheme, payload)
    if service == "langfuse":
        # Step scores go on the step's own observation. LangSmith items carry
        # no child run ids, so they get trace-level feedback only.
        for scheme, per_step in (step_summaries or {}).items():
            observations = _observation_ids(item_data, schemes_by_name.get(scheme, {}))
            spec = (score_config_spec(schemes_by_name.get(scheme, {}), step=True)
                    if cfg["langfuse"].get("score_configs") else None)
            for index, summary in sorted(per_step.items(), key=lambda kv: int(kv[0])):
                observation = observations.get(index)
                if observation is None:
                    continue
                key = f"{scheme}#step{index}"
                payload = langfuse_score(trace_id, f"{cfg['prefix']}.{scheme}", summary,
                                         instance_id=instance_id,
                                         score_uuid=score_id(service, instance_id, key))
                payload["observationId"] = observation
                if spec:
                    payload["_score_config"] = spec
                queued += queue.enqueue(service, instance_id, key, payload)
    return queued


def _schemes(config) -> List[dict]:
    return [s for s in config.get("annotation_schemes") or [] if isinstance(s, dict) and s.get("name")]


def on_save(instance_id: str, config: Optional[Dict[str, Any]] = None) -> int:
    """After a save: queue the item's answers if it is a trace with enough annotators."""
    try:
        if config is None:
            from potato.server_utils.config_module import config as config_
            config = config_
        cfg = settings(config)
        if cfg is None or cfg["trigger"] != "fully_annotated":
            return 0
        if trace_target(_item_data(instance_id)) is None:
            return 0
        schemes = _schemes(config)
        answers = item_answers(instance_id, schemes)
        most = max((len(a) for a in answers.values()), default=0)
        if most < cfg["min_annotators"]:
            logger.debug("Trace write-back for %s waits: %d of %d annotators",
                         instance_id, most, cfg["min_annotators"])
            return 0
        decided = _adjudicated(config, instance_id)
        summaries, held, step_summaries = {}, {}, {}
        for scheme in schemes:
            name = scheme["name"]
            if scheme.get("annotation_type") in _step_types():
                per_step = summarize_steps(step_answers(instance_id, scheme), cfg["min_annotators"])
                if per_step:
                    step_summaries[name] = per_step
                continue
            if name in decided:
                summaries[name] = decided[name]
            elif len(answers.get(name, {})) >= cfg["min_annotators"]:
                summaries[name] = summarize(scheme, answers[name])
                if summaries[name] is None:
                    reason = held_reason(scheme, answers[name])
                    if reason:
                        held[name] = reason
        queue = get_queue(config)
        return (_queue_item(config, queue, cfg, instance_id, summaries, held, step_summaries)
                if queue else 0)
    except Exception:  # noqa: BLE001 - a save must never fail because of this
        logger.exception("Could not queue trace write-back for %s", instance_id)
        return 0


def _adjudicated(config, instance_id: str) -> Dict[str, dict]:
    try:
        from potato.adjudication import get_adjudication_manager
        manager = get_adjudication_manager()
        decision = manager.decisions.get(str(instance_id)) if manager else None
    except Exception:  # noqa: BLE001 - adjudication is optional
        return {}
    if decision is None:
        return {}
    schemes = {s["name"]: s for s in _schemes(config)}
    out = {}
    for name, value in (decision.label_decisions or {}).items():
        if name in schemes:
            summary = adjudicated_value(schemes[name], value)
            if summary:
                # No adjudicator name: the payload goes to a third party, and
                # nothing in it identifies a person.
                out[name] = summary
    return out


def on_adjudication(decision, config: Optional[Dict[str, Any]] = None) -> int:
    """After an adjudication decision: send the decided values (either mode)."""
    try:
        if config is None:
            from potato.server_utils.config_module import config as config_
            config = config_
        cfg = settings(config)
        if cfg is None:
            return 0
        summaries = _adjudicated(config, str(decision.instance_id))
        queue = get_queue(config)
        return _queue_item(config, queue, cfg, str(decision.instance_id), summaries) if queue else 0
    except Exception:  # noqa: BLE001 - the decision is already saved
        logger.exception("Could not queue trace write-back for an adjudication")
        return 0
