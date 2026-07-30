"""
Live ingestion for data sources.

A data source is normally read on demand: once at startup, and again when an
admin presses "load more". This module adds the missing third mode -- a
background worker that polls a source on an interval so rows created *after*
the server started become annotatable without a restart.

The design is cursor-based rather than offset-based. OFFSET pagination is
wrong for a table that is being written to: insert a row near the front and
every subsequent page shifts, silently skipping or repeating items. A cursor
("give me everything after this point") stays correct under concurrent writes.

Thread safety
-------------
The poll thread acquires **at most one lock at a time, and never nests them**:

===========================================  ================================
Lock                                         Protects
===========================================  ================================
``ItemStateManager._lock``                   item dicts, ``remaining_instance_ids``
``LiveIngestionWorker._metrics_lock``        the metrics dataclass
``LiveCursorStore._lock``                    the JSON state file
===========================================  ================================

Conspicuously absent: ``DataSourceManager._lock``. The poll thread must never
hold it, because ``list_sources()`` takes it and is on the request path via
``GET /admin/api/data_sources``, and ``check_auto_load()`` takes it and is
reachable from the annotation flow. A 30-second database timeout held inside
that lock would block annotation requests. The worker therefore captures a
direct reference to its ``DataSource`` at registration and never asks the
manager for it again.

Configuration (nested under a ``data_sources`` entry)::

    data_sources:
      - id: live_instances
        type: database
        connection_string: "${DATABASE_URL}"
        query: "SELECT id, text, created_at FROM instances"
        live_ingestion:
          enabled: true
          poll_interval_seconds: 5
          cursor_column: created_at
          tiebreaker_column: id
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from potato.data_sources.base import DataSource

logger = logging.getLogger(__name__)

# Cap on the stored error string. SQLAlchemy DBAPI errors embed the full
# statement and its parameters; an admin JSON payload is the wrong place for
# that, and it is never useful past the first few lines anyway.
MAX_ERROR_LENGTH = 500


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class LiveIngestionConfig:
    """
    Parsed ``live_ingestion`` block for a single source.

    Attributes:
        enabled: Whether to run a background poller for this source
        poll_interval_seconds: Seconds between polls when healthy
        cursor_column: Column whose ascending order defines "newer"
        tiebreaker_column: Second sort key, so rows sharing a cursor value are
            not skipped. Defaults to the source's id column.
        initial_cursor: Cursor to start from on a first run. Required when the
            admin's query embeds its own ``:cursor`` placeholder, because
            ``x > NULL`` matches nothing and the source would appear empty
            forever.
        batch_size: Maximum rows fetched per poll
        overlap_seconds: Rewind the persisted cursor by this much before
            binding it. Re-fetched rows are dropped by the ID dedupe, so this
            costs bandwidth and buys tolerance for transactions that commit
            out of timestamp order. Recommended for any wall-clock cursor.
        safety_lag_seconds: Refuse to read rows newer than ``now - lag``,
            keeping the cursor behind the write frontier. Adds latency.
        backoff_initial_seconds: First retry delay after a failure
        backoff_max_seconds: Ceiling on the exponential backoff
        max_consecutive_failures: Stop the worker after this many failures in
            a row. 0 means retry forever.
        stop_after_items: Stop ingesting once this many items have been added.
            0 means unlimited. Guards against an unbounded item pool, which
            turns per-request scans of ``remaining_instance_ids`` into an
            ever-growing cost.
        replay_on_start: Re-read the source from the beginning at startup,
            ignoring the stored cursor for that one read. On by default so a
            restart rebuilds the full item pool, matching what a non-live
            database source does -- otherwise admin views, exports and
            adjudication would only see rows that arrived after the last
            restart. Deduplication makes the re-read harmless. Turn it off for
            a table too large to rescan on every boot; the pool will then
            contain only rows newer than the stored cursor.
    """

    enabled: bool = False
    poll_interval_seconds: float = 5.0
    cursor_column: str = ""
    tiebreaker_column: str = ""
    initial_cursor: Any = None
    batch_size: int = 500
    overlap_seconds: float = 0.0
    safety_lag_seconds: float = 0.0
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 300.0
    max_consecutive_failures: int = 0
    stop_after_items: int = 0
    replay_on_start: bool = True

    #: Single source of truth for the recognized keys. The config validator
    #: imports this rather than keeping its own copy -- this codebase already
    #: has three independent copies of the source-type list, and that is
    #: exactly how they drift.
    VALID_KEYS = frozenset({
        "enabled",
        "poll_interval_seconds",
        "cursor_column",
        "tiebreaker_column",
        "initial_cursor",
        "batch_size",
        "overlap_seconds",
        "safety_lag_seconds",
        "backoff_initial_seconds",
        "backoff_max_seconds",
        "max_consecutive_failures",
        "stop_after_items",
        "replay_on_start",
    })

    @classmethod
    def from_dict(cls, block: Optional[Dict[str, Any]]) -> "LiveIngestionConfig":
        """Build a config from the raw ``live_ingestion`` mapping."""
        block = block or {}
        return cls(
            enabled=bool(block.get("enabled", False)),
            poll_interval_seconds=float(block.get("poll_interval_seconds", 5.0)),
            cursor_column=str(block.get("cursor_column", "") or ""),
            tiebreaker_column=str(block.get("tiebreaker_column", "") or ""),
            initial_cursor=block.get("initial_cursor"),
            batch_size=int(block.get("batch_size", 500)),
            overlap_seconds=float(block.get("overlap_seconds", 0.0)),
            safety_lag_seconds=float(block.get("safety_lag_seconds", 0.0)),
            backoff_initial_seconds=float(block.get("backoff_initial_seconds", 1.0)),
            backoff_max_seconds=float(block.get("backoff_max_seconds", 300.0)),
            max_consecutive_failures=int(block.get("max_consecutive_failures", 0)),
            stop_after_items=int(block.get("stop_after_items", 0)),
            replay_on_start=bool(block.get("replay_on_start", True)),
        )

    def validate(self) -> List[str]:
        """Return a list of human-readable problems (empty when valid)."""
        errors = []

        if not self.enabled:
            return errors

        if self.poll_interval_seconds < 0.5:
            errors.append("poll_interval_seconds must be at least 0.5 seconds")
        if self.poll_interval_seconds > 3600:
            errors.append("poll_interval_seconds cannot exceed 3600 seconds (1 hour)")
        if self.batch_size < 1:
            errors.append("batch_size must be a positive integer")
        if self.overlap_seconds < 0:
            errors.append("overlap_seconds must be a non-negative number")
        if self.safety_lag_seconds < 0:
            errors.append("safety_lag_seconds must be a non-negative number")
        if self.backoff_initial_seconds <= 0:
            errors.append("backoff_initial_seconds must be a positive number")
        if self.backoff_max_seconds < self.backoff_initial_seconds:
            errors.append("backoff_max_seconds must be >= backoff_initial_seconds")
        if self.max_consecutive_failures < 0:
            errors.append("max_consecutive_failures must be a non-negative integer")
        if self.stop_after_items < 0:
            errors.append("stop_after_items must be a non-negative integer")

        return errors


# =============================================================================
# Cursor serialization
# =============================================================================


class CursorCodec:
    """
    Type-tagged JSON serialization for cursor values.

    A cursor is whatever the cursor column holds -- a ``datetime``, a bigint,
    a string. Storing it bare in JSON loses that distinction: a datetime comes
    back as a string, and re-binding a string against a typed column relies on
    implicit casts that differ by backend. So every value is stored alongside
    its kind and restored to the original type.
    """

    _WARNED_KINDS: set = set()

    @staticmethod
    def encode(value: Any) -> Dict[str, Any]:
        """Convert a cursor value into a JSON-safe tagged envelope."""
        if value is None:
            return {"kind": "none", "raw": None}
        if isinstance(value, bool):
            # Must precede the int check -- bool is a subclass of int.
            return {"kind": "bool", "raw": value}
        if isinstance(value, datetime):
            return {"kind": "datetime", "raw": value.isoformat()}
        if isinstance(value, date):
            return {"kind": "date", "raw": value.isoformat()}
        if isinstance(value, int):
            return {"kind": "int", "raw": value}
        if isinstance(value, float):
            return {"kind": "float", "raw": value}
        if isinstance(value, str):
            return {"kind": "str", "raw": value}

        # Decimal, UUID and friends: str() round-trips well enough to compare
        # against most columns, but not always, so say so once.
        type_name = type(value).__name__
        if type_name not in CursorCodec._WARNED_KINDS:
            CursorCodec._WARNED_KINDS.add(type_name)
            logger.warning(
                "Cursor value of type '%s' is not natively serializable; "
                "storing as a string. If ingestion re-reads or skips rows "
                "after a restart, use a cursor column of a simpler type.",
                type_name,
            )
        return {"kind": "str", "raw": str(value)}

    @staticmethod
    def decode(payload: Optional[Dict[str, Any]]) -> Any:
        """Restore a cursor value from its tagged envelope."""
        if not payload or not isinstance(payload, dict):
            return None

        kind = payload.get("kind")
        raw = payload.get("raw")

        if kind == "none" or raw is None:
            return None
        if kind == "datetime":
            try:
                return datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                logger.warning("Could not decode datetime cursor %r; using it as text", raw)
                return raw
        if kind == "date":
            try:
                return date.fromisoformat(raw)
            except (TypeError, ValueError):
                logger.warning("Could not decode date cursor %r; using it as text", raw)
                return raw
        if kind == "int":
            return int(raw)
        if kind == "float":
            return float(raw)
        if kind == "bool":
            return bool(raw)
        return raw


# =============================================================================
# Cursor persistence
# =============================================================================


class LiveCursorStore:
    """
    Durable ``source_id -> (cursor, tiebreaker)`` map.

    Written atomically (temp file + ``os.replace``) because the poll thread
    rewrites it every few seconds. A plain truncate-then-write that is
    interrupted leaves a half-written file, and the recovery path for corrupt
    JSON is "start over from nothing" -- i.e. re-ingest the entire table.

    This deliberately does not reuse ``PartialReader``: that object only exists
    when ``partial_loading.enabled`` is set, so a live source without that
    unrelated flag would silently lose its cursor on every restart. Its state
    also carries an ``is_complete`` flag that makes ``_load_from_source`` skip
    a source outright, and a live source is never complete.
    """

    STATE_FILENAME = "live_ingestion_state.json"

    def __init__(self, output_dir: str):
        """
        Args:
            output_dir: Directory to hold the state file (normally
                ``output_annotation_dir``)
        """
        self._output_dir = output_dir
        self._path = os.path.join(output_dir, self.STATE_FILENAME)
        self._lock = threading.Lock()
        self._state: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Read the state file, tolerating absence and corruption."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "rt", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._state = data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "Could not read live ingestion state at %s (%s). "
                "Starting from an empty cursor; rows already annotated are "
                "still protected by ID deduplication.",
                self._path, e,
            )
            self._state = {}

    def _save_locked(self) -> None:
        """Write the state file atomically. Caller must hold ``_lock``."""
        try:
            os.makedirs(self._output_dir, exist_ok=True)
            tmp_path = f"{self._path}.tmp"
            with open(tmp_path, "wt", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp_path, self._path)
        except OSError as e:
            # Losing a cursor write costs a re-fetch, not correctness. Never
            # let it kill the poll thread.
            logger.error("Failed to persist live ingestion state: %s", e)

    def get(self, source_id: str) -> Tuple[Any, Optional[str]]:
        """
        Get the stored ``(cursor_value, tiebreaker)`` for a source.

        Returns ``(None, None)`` when nothing has been stored yet.
        """
        with self._lock:
            entry = self._state.get(source_id)
        if not entry:
            return None, None
        return CursorCodec.decode(entry.get("cursor")), entry.get("tiebreaker")

    def set(self, source_id: str, value: Any, tiebreaker: Optional[str]) -> None:
        """Persist the cursor position for a source."""
        with self._lock:
            self._state[source_id] = {
                "cursor": CursorCodec.encode(value),
                "tiebreaker": tiebreaker,
                "updated_at": time.time(),
            }
            self._save_locked()

    def clear(self, source_id: str) -> None:
        """Forget a source's cursor, so the next read starts from the top."""
        with self._lock:
            if source_id in self._state:
                del self._state[source_id]
                self._save_locked()

    def all(self) -> Dict[str, Dict[str, Any]]:
        """Snapshot of the whole state map."""
        with self._lock:
            return dict(self._state)


# =============================================================================
# Metrics
# =============================================================================


@dataclass
class IngestionMetrics:
    """Counters and status for one live worker, reported by the admin API."""

    is_running: bool = False
    polls_total: int = 0
    polls_failed: int = 0
    rows_fetched: int = 0
    items_added: int = 0
    duplicates_skipped: int = 0
    invalid_rows_skipped: int = 0
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None
    last_poll_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_cursor: Optional[str] = None
    last_cursor_tiebreak: Optional[str] = None
    current_backoff_seconds: float = 0.0
    started_at: Optional[float] = None
    stopped_reason: Optional[str] = None

    def snapshot(self) -> Dict[str, Any]:
        """Plain-dict copy for JSON serialization."""
        return {
            "is_running": self.is_running,
            "polls_total": self.polls_total,
            "polls_failed": self.polls_failed,
            "rows_fetched": self.rows_fetched,
            "items_added": self.items_added,
            "duplicates_skipped": self.duplicates_skipped,
            "invalid_rows_skipped": self.invalid_rows_skipped,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "last_poll_at": self.last_poll_at,
            "last_success_at": self.last_success_at,
            "last_cursor": self.last_cursor,
            "last_cursor_tiebreak": self.last_cursor_tiebreak,
            "current_backoff_seconds": self.current_backoff_seconds,
            "started_at": self.started_at,
            "stopped_reason": self.stopped_reason,
        }


# =============================================================================
# Worker
# =============================================================================


class LiveIngestionWorker:
    """
    Polls one data source on an interval and feeds new rows into the item pool.

    Lifecycle: ``prime()`` at startup for the catch-up read, then ``start()``
    for the background loop, then ``stop()`` at shutdown.

    Every failure is contained. ``poll_once()`` raises; ``_poll_loop`` catches,
    records, backs off, and tries again. Nothing reaches a request thread.
    """

    def __init__(
        self,
        source: "DataSource",
        config: LiveIngestionConfig,
        cursor_store: LiveCursorStore,
        ingest_fn,
    ):
        """
        Args:
            source: The data source to poll. Held directly so the hot loop
                never has to ask the manager for it (and so never touches
                ``DataSourceManager._lock``).
            config: Parsed ``live_ingestion`` block
            cursor_store: Where the cursor is persisted between polls
            ingest_fn: ``fn(item: dict) -> str`` returning one of ``"added"``,
                ``"duplicate"`` or ``"invalid"``. Supplied by the manager so
                live and startup inserts share one code path -- including id
                stringification, without which the two paths would dedupe
                against each other incorrectly.
        """
        self._source = source
        self._config = config
        self._cursor_store = cursor_store
        self._ingest = ingest_fn
        self.source_id = source.source_id

        self._cursor, self._tiebreaker = cursor_store.get(self.source_id)
        if self._cursor is None and config.initial_cursor is not None:
            self._cursor = config.initial_cursor

        self._metrics = IngestionMetrics()
        self._metrics_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """
        Start the background poll thread.

        Idempotent: calling it while the thread is alive is a no-op.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Live ingestion worker for %s is already running", self.source_id)
            return

        self._stop_event.clear()
        with self._metrics_lock:
            self._metrics.is_running = True
            self._metrics.started_at = time.time()
            self._metrics.stopped_reason = None

        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"LiveIngestion-{self.source_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Live ingestion started for %s (poll interval: %.1fs)",
            self.source_id, self._config.poll_interval_seconds,
        )

    def stop(self) -> None:
        """
        Signal the poll thread to stop and wait briefly for it.

        Safe to call when never started. The join budget accounts for a poll
        that is currently blocked on the database: the default SQLAlchemy
        ``pool_timeout`` is 30s, so a fixed 5s join would warn on any shutdown
        that lands mid-query. The thread is a daemon, so a slow one never
        blocks process exit.
        """
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(5.0, self._config.poll_interval_seconds))
            if thread.is_alive():
                logger.warning(
                    "Live ingestion worker for %s did not stop within the join "
                    "budget; it is a daemon thread and will not block exit.",
                    self.source_id,
                )
            else:
                logger.info("Live ingestion stopped for %s", self.source_id)

        self._thread = None
        with self._metrics_lock:
            self._metrics.is_running = False

    def is_running(self) -> bool:
        """True while the poll thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    # -- reading -----------------------------------------------------------

    def prime(self) -> int:
        """
        Startup read, in place of the ordinary bulk load.

        By default this replays the source from the beginning, exactly as a
        non-live database source would. That matters on a restart: resuming
        from the stored cursor alone would leave the item pool holding only
        rows that arrived after the last shutdown, and admin views, exports
        and adjudication all read that pool. Deduplication makes the replay
        cheap in effect, if not in I/O.

        With ``replay_on_start: false`` it resumes from the stored cursor
        instead -- cheaper for a very large table, at the cost of a partial
        pool after a restart.

        The persisted cursor is never moved backwards by a replay: the poll
        loop must not re-deliver rows it has already passed.

        Returns:
            Number of items added
        """
        resume_cursor, resume_tiebreak = self._cursor, self._tiebreaker

        if self._config.replay_on_start and resume_cursor is not None:
            logger.info(
                "Live source %s: replaying from the beginning to rebuild the "
                "item pool (set live_ingestion.replay_on_start: false to resume "
                "from the stored cursor instead)",
                self.source_id,
            )
            self._cursor, self._tiebreaker = None, None

        total_added = 0
        try:
            while True:
                added, fetched = self._fetch_and_ingest(persist_cursor=False)
                total_added += added
                if fetched < self._config.batch_size:
                    break
                if self._reached_item_limit():
                    logger.warning(
                        "Live ingestion for %s hit stop_after_items=%d during the "
                        "initial read; remaining rows were not loaded.",
                        self.source_id, self._config.stop_after_items,
                    )
                    break
        finally:
            # Never let a replay rewind a cursor the poller has already passed.
            if resume_cursor is not None and self._cursor_is_before(resume_cursor):
                self._cursor, self._tiebreaker = resume_cursor, resume_tiebreak
            if self._cursor is not None:
                self._cursor_store.set(self.source_id, self._cursor, self._tiebreaker)
                with self._metrics_lock:
                    self._metrics.last_cursor = str(self._cursor)
                    self._metrics.last_cursor_tiebreak = self._tiebreaker

        return total_added

    def _cursor_is_before(self, other: Any) -> bool:
        """True when the live cursor sorts before ``other`` (or is unset)."""
        if self._cursor is None:
            return True
        try:
            return self._cursor < other
        except TypeError:
            # Mixed types cannot be ordered; keep the stored value, which is
            # the conservative choice (re-fetch rather than skip).
            return True

    def poll_once(self) -> Dict[str, int]:
        """
        Run exactly one poll.

        Used by the background loop and by the admin force-poll endpoint.
        Raises on failure -- the loop handles it, and the endpoint turns it
        into a 500.

        Returns:
            ``{"rows_fetched": n, "items_added": n, "duplicates_skipped": n}``
        """
        before = self._snapshot_counters()
        self._fetch_and_ingest()
        after = self._snapshot_counters()
        return {
            "rows_fetched": after["rows_fetched"] - before["rows_fetched"],
            "items_added": after["items_added"] - before["items_added"],
            "duplicates_skipped": after["duplicates_skipped"] - before["duplicates_skipped"],
        }

    def _snapshot_counters(self) -> Dict[str, int]:
        with self._metrics_lock:
            return {
                "rows_fetched": self._metrics.rows_fetched,
                "items_added": self._metrics.items_added,
                "duplicates_skipped": self._metrics.duplicates_skipped,
            }

    def _reached_item_limit(self) -> bool:
        if self._config.stop_after_items <= 0:
            return False
        with self._metrics_lock:
            return self._metrics.items_added >= self._config.stop_after_items

    def _effective_cursor(self) -> Any:
        """
        The cursor to bind, after applying ``overlap_seconds``.

        Rewinding slightly re-fetches rows near the boundary. They are dropped
        by the ID dedupe, which is what makes this safe: a transaction that
        started before the last poll but committed after it has an earlier
        timestamp and would otherwise be stepped over permanently.
        """
        cursor = self._cursor
        overlap = self._config.overlap_seconds
        if not overlap or cursor is None:
            return cursor

        from datetime import timedelta

        if isinstance(cursor, datetime):
            return cursor - timedelta(seconds=overlap)
        if isinstance(cursor, (int, float)) and not isinstance(cursor, bool):
            return type(cursor)(cursor - overlap)

        if isinstance(cursor, str):
            # SQLite (and plenty of schemas elsewhere) store timestamps as
            # ISO-8601 text. Without this branch overlap_seconds would be
            # silently inert for exactly the setups most likely to need it.
            try:
                parsed = datetime.fromisoformat(cursor)
            except ValueError:
                return cursor
            return (parsed - timedelta(seconds=overlap)).isoformat()

        # An opaque cursor cannot be rewound arithmetically.
        return cursor

    def _fetch_and_ingest(self, persist_cursor: bool = True) -> Tuple[int, int]:
        """
        Fetch one batch and feed it to the item pool.

        Args:
            persist_cursor: Write the advanced cursor to disk. ``prime()``
                passes False and flushes once at the end, so a mid-replay
                crash cannot leave a cursor behind the rows already ingested.

        Returns:
            ``(items_added, rows_fetched)``
        """
        rows_fetched = 0
        items_added = 0
        duplicates = 0
        invalid = 0
        last_cursor = None
        last_tiebreak = None

        # No lock is held here -- this is the network I/O.
        rows = self._source.read_since(
            cursor=self._effective_cursor(),
            tiebreaker=self._tiebreaker,
            limit=self._config.batch_size,
        )

        for row in rows:
            rows_fetched += 1
            outcome = self._ingest(row.item)
            if outcome == "added":
                items_added += 1
            elif outcome == "duplicate":
                duplicates += 1
            else:
                invalid += 1

            # Track the last row of the ordered batch. ORDER BY guarantees it
            # is the maximum, and when LIMIT truncated the batch it is exactly
            # where the next read must resume.
            last_cursor = row.cursor_value
            last_tiebreak = row.row_id

            if self._reached_item_limit():
                break

        now = time.time()
        with self._metrics_lock:
            self._metrics.polls_total += 1
            self._metrics.rows_fetched += rows_fetched
            self._metrics.items_added += items_added
            self._metrics.duplicates_skipped += duplicates
            self._metrics.invalid_rows_skipped += invalid
            self._metrics.last_poll_at = now
            self._metrics.last_success_at = now
            self._metrics.consecutive_failures = 0
            self._metrics.current_backoff_seconds = 0.0

        # Advance only after the whole batch has been ingested. Dying here
        # re-fetches and dedupes; advancing per row and dying loses data.
        if rows_fetched > 0:
            self._cursor = last_cursor
            self._tiebreaker = last_tiebreak
            if persist_cursor:
                self._cursor_store.set(self.source_id, last_cursor, last_tiebreak)
                with self._metrics_lock:
                    self._metrics.last_cursor = str(last_cursor)
                    self._metrics.last_cursor_tiebreak = last_tiebreak

        return items_added, rows_fetched

    # -- background loop ---------------------------------------------------

    def _poll_loop(self) -> None:
        """
        Poll until stopped, absorbing every failure.

        Backoff is exponential with jitter. Jitter matters when several
        workers share a database that has just come back: without it they all
        reconnect in lockstep and knock it over again.
        """
        logger.debug("Live ingestion loop started for %s", self.source_id)
        backoff = 0.0

        while not self._stop_event.is_set():
            try:
                added, fetched = self._fetch_and_ingest()
                if added:
                    logger.info(
                        "Live ingestion %s: %d rows fetched, %d items added",
                        self.source_id, fetched, added,
                    )
                elif fetched:
                    # With overlap_seconds set, every poll re-reads the boundary
                    # rows and discards them. Logging that at INFO would emit a
                    # line per interval, forever, saying nothing happened.
                    logger.debug(
                        "Live ingestion %s: %d rows fetched, all duplicates",
                        self.source_id, fetched,
                    )
                backoff = 0.0

                if self._reached_item_limit():
                    self._mark_stopped(
                        f"stop_after_items limit ({self._config.stop_after_items}) reached"
                    )
                    break

                wait_for = self._config.poll_interval_seconds

            except Exception as e:
                backoff = self._record_failure(e)
                if backoff is None:
                    break
                wait_for = backoff

            # Always wait on the event, never sleep(): a 300-second backoff
            # must not delay shutdown by 300 seconds.
            self._stop_event.wait(timeout=wait_for)

        logger.debug("Live ingestion loop ended for %s", self.source_id)

    def _record_failure(self, error: Exception) -> Optional[float]:
        """
        Record a poll failure and compute the next backoff.

        Returns the delay to wait, or None when the worker should stop.
        """
        message = f"{type(error).__name__}: {error}"
        if len(message) > MAX_ERROR_LENGTH:
            message = message[:MAX_ERROR_LENGTH] + "..."

        now = time.time()
        with self._metrics_lock:
            self._metrics.polls_total += 1
            self._metrics.polls_failed += 1
            self._metrics.consecutive_failures += 1
            self._metrics.last_error = message
            self._metrics.last_error_at = now
            self._metrics.last_poll_at = now
            failures = self._metrics.consecutive_failures

        logger.warning(
            "Live ingestion poll failed for %s (failure %d): %s",
            self.source_id, failures, message,
        )

        # Rebuild the connection pool. pool_pre_ping catches a stale
        # connection but cannot rescue a pool that is entirely dead.
        try:
            self._source.close()
        except Exception as close_error:
            logger.debug("Error closing source %s after failure: %s", self.source_id, close_error)

        limit = self._config.max_consecutive_failures
        if limit and failures >= limit:
            self._mark_stopped(
                f"stopped after {failures} consecutive failures; last error: {message}"
            )
            logger.error(
                "Live ingestion for %s stopped after %d consecutive failures. "
                "Fix the source and restart the server, or use the admin "
                "force-poll endpoint once it is reachable again.",
                self.source_id, failures,
            )
            return None

        next_backoff = min(
            self._config.backoff_max_seconds,
            self._config.backoff_initial_seconds * (2 ** (failures - 1)),
        )
        next_backoff *= random.uniform(0.8, 1.2)

        with self._metrics_lock:
            self._metrics.current_backoff_seconds = next_backoff

        return next_backoff

    def _mark_stopped(self, reason: str) -> None:
        with self._metrics_lock:
            self._metrics.is_running = False
            self._metrics.stopped_reason = reason

    # -- reporting ---------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """
        Status payload for the admin API.

        Deliberately excludes anything derived from the connection string --
        credentials must never reach an HTTP response.
        """
        with self._metrics_lock:
            status = self._metrics.snapshot()

        status.update({
            "source_id": self.source_id,
            "is_running": self.is_running(),
            "poll_interval_seconds": self._config.poll_interval_seconds,
            "cursor_column": self._config.cursor_column,
            "tiebreaker_column": self._config.tiebreaker_column,
            "batch_size": self._config.batch_size,
            "overlap_seconds": self._config.overlap_seconds,
        })
        return status


# =============================================================================
# Coordinator
# =============================================================================


class LiveIngestionCoordinator:
    """
    Owns the set of live workers for a ``DataSourceManager``.

    Held as an attribute of the manager rather than as its own module-level
    singleton, so that the existing ``clear_data_source_manager()`` teardown
    already stops every thread. A second singleton would be a second lifecycle
    for tests to forget.
    """

    def __init__(self, cursor_store: LiveCursorStore):
        self._cursor_store = cursor_store
        self._workers: Dict[str, LiveIngestionWorker] = {}
        self._lock = threading.Lock()

    def register(
        self,
        source: "DataSource",
        config: LiveIngestionConfig,
        ingest_fn,
    ) -> LiveIngestionWorker:
        """Create and remember a worker for a source."""
        worker = LiveIngestionWorker(source, config, self._cursor_store, ingest_fn)
        with self._lock:
            self._workers[source.source_id] = worker
        return worker

    def get_worker(self, source_id: str) -> Optional[LiveIngestionWorker]:
        """Look up a worker by source id, or None."""
        with self._lock:
            return self._workers.get(source_id)

    def has_workers(self) -> bool:
        """True when at least one live source is registered."""
        with self._lock:
            return bool(self._workers)

    def start_all(self) -> int:
        """Start every registered worker. Returns how many were started."""
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.start()
        return len(workers)

    def stop_all(self) -> None:
        """
        Stop every worker.

        Callers must not hold ``DataSourceManager._lock`` here: this joins
        threads that may be mid-``add_item``, and joining while holding a lock
        they might want is a deadlock.
        """
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            try:
                worker.stop()
            except Exception as e:
                logger.warning("Error stopping live worker %s: %s", worker.source_id, e)

    def get_status(self) -> List[Dict[str, Any]]:
        """Status for every registered worker."""
        with self._lock:
            workers = list(self._workers.values())
        return [w.get_status() for w in workers]
