"""
SQLite storage for schedules, and a separate one for contact details.

Two files, kept apart on purpose:

``<output_annotation_dir>/scheduling/schedule.sqlite``
    Research data: who enrolled when and in which time zone, every session
    (wave, prompt, Delphi round) with its window and answers, and the log of
    every notification (when it was due, on which channel, sent or failed).
    No email address or phone number is ever written here. It lives in the
    output directory, so backups and ``potato deploy pull`` carry it, and the
    ``schedule`` export reads it.

``<task_dir>/.potato/scheduling/contacts.sqlite``
    Participant PII: email address and phone number, only for participants
    who gave contact consent. Outside the output directory, and inside a
    ``.potato`` folder that the archive and deploy bundles skip, so no export,
    archive, backup or bundle picks it up. Rows are deleted when a participant
    stops messages, when an admin deletes them, and (by default) when the
    participant has no sessions left.

Both use SQLite's default rollback journal rather than WAL, so the file on
disk is always a complete database (the archive copies the output directory
file by file). Connections are opened per operation, which keeps the
scheduler thread and request threads from sharing one.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS participants (
    participant      TEXT PRIMARY KEY,
    enrolled_at      REAL NOT NULL,
    timezone         TEXT NOT NULL,
    timezone_source  TEXT,
    contact_consent  INTEGER NOT NULL DEFAULT 0,
    channels         TEXT,
    crowd_provider   TEXT,
    crowd_worker_id  TEXT,
    crowd_study_id   TEXT,
    withdrawn_at     REAL,
    contact_deleted_at REAL,
    contact_deleted_reason TEXT,
    link_epoch       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    participant      TEXT NOT NULL,
    id               TEXT NOT NULL,
    kind             TEXT NOT NULL,
    name             TEXT NOT NULL,
    title            TEXT,
    seq              INTEGER NOT NULL DEFAULT 0,
    day              INTEGER,
    opens_at         REAL NOT NULL,
    closes_at        REAL NOT NULL,
    opened_at        REAL,
    first_answer_at  REAL,
    submitted_at     REAL,
    answers          TEXT,
    PRIMARY KEY (participant, id)
);
CREATE INDEX IF NOT EXISTS sessions_by_time ON sessions (opens_at);
CREATE TABLE IF NOT EXISTS notifications (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    key              TEXT NOT NULL UNIQUE,
    participant      TEXT NOT NULL,
    session_id       TEXT NOT NULL,
    rule             TEXT NOT NULL,
    template         TEXT NOT NULL,
    channel          TEXT NOT NULL,
    due_at           REAL NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  REAL,
    claimed_at       REAL,
    sent_at          REAL,
    detail           TEXT,
    preview          TEXT
);
CREATE INDEX IF NOT EXISTS notifications_due ON notifications (status, due_at);
CREATE TABLE IF NOT EXISTS delphi_rounds (
    round            INTEGER PRIMARY KEY,
    opens_at         REAL NOT NULL,
    closes_at        REAL NOT NULL,
    closed_at        REAL,
    status           TEXT NOT NULL DEFAULT 'scheduled',
    stop_reason      TEXT
);
CREATE TABLE IF NOT EXISTS delphi_stats (
    round            INTEGER NOT NULL,
    item             TEXT NOT NULL,
    n                INTEGER NOT NULL,
    median           REAL,
    q1               REAL,
    q3               REAL,
    iqr              REAL,
    mean             REAL,
    median_change    REAL,
    changed_share    REAL,
    settled          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (round, item)
);
"""

_CONTACT_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    participant  TEXT PRIMARY KEY,
    email        TEXT,
    phone        TEXT,
    consented_at REAL NOT NULL,
    updated_at   REAL NOT NULL
);
"""


class _Sqlite:
    def __init__(self, path: str, schema: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as db:
            db.executescript(schema)

    @contextmanager
    def connect(self):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def exists(self) -> bool:
        return os.path.isfile(self.path)


def _row(r) -> Dict[str, Any]:
    return dict(r) if r is not None else None


class ScheduleStore(_Sqlite):
    """Sessions, notifications and Delphi rounds. Never holds an address."""

    def __init__(self, path: str):
        super().__init__(path, _SCHEMA)

    # -- meta -------------------------------------------------------------
    def meta(self, key: str) -> Optional[str]:
        with self.connect() as db:
            r = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def set_meta(self, key: str, value: str, only_if_missing: bool = False) -> str:
        with self.connect() as db:
            if only_if_missing:
                db.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, value))
            else:
                db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
            r = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"]

    # -- participants -----------------------------------------------------
    def participant(self, participant: str) -> Optional[Dict[str, Any]]:
        with self.connect() as db:
            return _row(db.execute("SELECT * FROM participants WHERE participant=?",
                                   (participant,)).fetchone())

    def participants(self) -> List[Dict[str, Any]]:
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM participants ORDER BY enrolled_at, participant")]

    def add_participant(self, row: Dict[str, Any]) -> bool:
        """Insert once; False when the participant is already enrolled."""
        cols = list(row)
        with self.connect() as db:
            cur = db.execute(
                f"INSERT OR IGNORE INTO participants ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols])
            return cur.rowcount == 1

    def update_participant(self, participant: str, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.connect() as db:
            db.execute(f"UPDATE participants SET {sets} WHERE participant=?",
                       [*fields.values(), participant])

    # -- sessions ---------------------------------------------------------
    def add_sessions(self, rows: Iterable[Dict[str, Any]]) -> int:
        n = 0
        with self.connect() as db:
            for row in rows:
                cols = list(row)
                cur = db.execute(
                    f"INSERT OR IGNORE INTO sessions ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols])
                n += cur.rowcount
        return n

    def sessions(self, participant: Optional[str] = None, kind: Optional[str] = None,
                 session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        where, args = [], []
        if participant is not None:
            where.append("participant=?")
            args.append(participant)
        if kind is not None:
            where.append("kind=?")
            args.append(kind)
        if session_id is not None:
            where.append("id=?")
            args.append(session_id)
        sql = "SELECT * FROM sessions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY opens_at, seq, participant"
        with self.connect() as db:
            out = [dict(r) for r in db.execute(sql, args)]
        for r in out:
            r["answers"] = json.loads(r["answers"]) if r.get("answers") else None
        return out

    def session(self, participant: str, session_id: str) -> Optional[Dict[str, Any]]:
        rows = self.sessions(participant, session_id=session_id)
        return rows[0] if rows else None

    def mark_opened(self, participant: str, session_id: str, at: float) -> None:
        with self.connect() as db:
            db.execute("UPDATE sessions SET opened_at=? WHERE participant=? AND id=? "
                       "AND opened_at IS NULL", (at, participant, session_id))

    def mark_first_answer(self, participant: str, session_id: str, at: float) -> bool:
        with self.connect() as db:
            cur = db.execute(
                "UPDATE sessions SET first_answer_at=?, opened_at=COALESCE(opened_at, ?) "
                "WHERE participant=? AND id=? AND first_answer_at IS NULL "
                "AND submitted_at IS NULL AND opens_at<=? AND closes_at>?",
                (at, at, participant, session_id, at, at))
            return cur.rowcount == 1

    def submit(self, participant: str, session_id: str, answers: Dict[str, Any],
               at: float) -> bool:
        """Store answers once, and only while the window is open."""
        with self.connect() as db:
            cur = db.execute(
                "UPDATE sessions SET answers=?, submitted_at=?, "
                "first_answer_at=COALESCE(first_answer_at, ?), opened_at=COALESCE(opened_at, ?) "
                "WHERE participant=? AND id=? AND submitted_at IS NULL "
                "AND opens_at<=? AND closes_at>?",
                (json.dumps(answers, ensure_ascii=False), at, at, at, participant, session_id,
                 at, at))
            return cur.rowcount == 1

    # -- notifications ----------------------------------------------------
    def add_notifications(self, rows: Iterable[Dict[str, Any]]) -> int:
        n = 0
        with self.connect() as db:
            for row in rows:
                cols = list(row)
                cur = db.execute(
                    f"INSERT OR IGNORE INTO notifications ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols])
                n += cur.rowcount
        return n

    def due_notifications(self, now: float, limit: int = 200) -> List[Dict[str, Any]]:
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM notifications WHERE status='pending' AND due_at<=? "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
                "ORDER BY due_at, id LIMIT ?", (now, now, limit))]

    def claim(self, notification_id: int, now: float) -> bool:
        """Take a pending message for sending. Only one caller (thread or
        process) wins, which is what keeps a message from going out twice."""
        with self.connect() as db:
            cur = db.execute("UPDATE notifications SET status='sending', claimed_at=? "
                             "WHERE id=? AND status='pending'", (now, notification_id))
            return cur.rowcount == 1

    def finish(self, notification_id: int, status: str, now: float, detail: str = "",
               preview: Optional[str] = None, retry_at: Optional[float] = None) -> None:
        with self.connect() as db:
            if retry_at is not None:
                db.execute("UPDATE notifications SET status='pending', attempts=attempts+1, "
                           "next_attempt_at=?, detail=? WHERE id=?",
                           (retry_at, detail, notification_id))
            else:
                db.execute(
                    "UPDATE notifications SET status=?, attempts=attempts+?, sent_at=?, "
                    "detail=?, preview=COALESCE(?, preview) WHERE id=?",
                    (status, 1 if status in ("sent", "failed", "dry_run") else 0,
                     now if status in ("sent", "dry_run") else None, detail, preview,
                     notification_id))

    def release_stale_claims(self, older_than: float) -> int:
        """A claim left by a process that died mid-send. The message may or
        may not have gone out, so it is marked failed, never resent: a
        duplicate reminder is worse than a missing one."""
        with self.connect() as db:
            cur = db.execute(
                "UPDATE notifications SET status='failed', detail='interrupted while sending "
                "(server stopped); not resent' WHERE status='sending' AND claimed_at<?",
                (older_than,))
            return cur.rowcount

    def skip_pending(self, participant: str, reason: str) -> int:
        with self.connect() as db:
            cur = db.execute("UPDATE notifications SET status='skipped', detail=? "
                             "WHERE participant=? AND status='pending'", (reason, participant))
            return cur.rowcount

    def notifications(self, participant: Optional[str] = None, status: Optional[str] = None,
                      session_id: Optional[str] = None, limit: Optional[int] = None,
                      newest_first: bool = False) -> List[Dict[str, Any]]:
        where, args = [], []
        for col, val in (("participant", participant), ("status", status),
                         ("session_id", session_id)):
            if val is not None:
                where.append(f"{col}=?")
                args.append(val)
        sql = "SELECT * FROM notifications"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY due_at DESC, id DESC" if newest_first else " ORDER BY due_at, id"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def notification_counts(self) -> Dict[str, int]:
        with self.connect() as db:
            return {r["status"]: r["n"] for r in db.execute(
                "SELECT status, COUNT(*) AS n FROM notifications GROUP BY status")}

    # -- Delphi -----------------------------------------------------------
    def rounds(self) -> List[Dict[str, Any]]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM delphi_rounds ORDER BY round")]

    def add_round(self, number: int, opens_at: float, closes_at: float) -> bool:
        with self.connect() as db:
            cur = db.execute("INSERT OR IGNORE INTO delphi_rounds (round, opens_at, closes_at) "
                             "VALUES (?, ?, ?)", (number, opens_at, closes_at))
            return cur.rowcount == 1

    def update_round(self, number: int, **fields) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.connect() as db:
            db.execute(f"UPDATE delphi_rounds SET {sets} WHERE round=?", [*fields.values(), number])

    def close_round_sessions(self, number: int, at: float) -> None:
        """Bring the round's sessions' windows in line with an early close."""
        with self.connect() as db:
            db.execute("UPDATE sessions SET closes_at=? WHERE kind='round' AND id=? "
                       "AND closes_at>?", (at, f"round:{number}", at))

    def save_stats(self, number: int, rows: List[Dict[str, Any]]) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM delphi_stats WHERE round=?", (number,))
            for r in rows:
                db.execute(
                    "INSERT INTO delphi_stats (round, item, n, median, q1, q3, iqr, mean, "
                    "median_change, changed_share, settled) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (number, r["item"], r["n"], r.get("median"), r.get("q1"), r.get("q3"),
                     r.get("iqr"), r.get("mean"), r.get("median_change"),
                     r.get("changed_share"), 1 if r.get("settled") else 0))

    def stats(self, number: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.connect() as db:
            if number is None:
                rows = db.execute("SELECT * FROM delphi_stats ORDER BY round, item")
            else:
                rows = db.execute("SELECT * FROM delphi_stats WHERE round=? ORDER BY item",
                                  (number,))
            return [dict(r) for r in rows]


class ContactStore(_Sqlite):
    """Email addresses and phone numbers. Kept out of every export."""

    def __init__(self, path: str):
        super().__init__(path, _CONTACT_SCHEMA)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - filesystems without modes
            pass

    def set(self, participant: str, email: Optional[str], phone: Optional[str],
            now: Optional[float] = None) -> None:
        now = now or time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO contacts (participant, email, phone, consented_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(participant) DO UPDATE SET "
                "email=excluded.email, phone=excluded.phone, updated_at=excluded.updated_at",
                (participant, email or None, phone or None, now, now))

    def get(self, participant: str) -> Optional[Dict[str, Any]]:
        with self.connect() as db:
            return _row(db.execute("SELECT * FROM contacts WHERE participant=?",
                                   (participant,)).fetchone())

    def delete(self, participant: str) -> bool:
        with self.connect() as db:
            cur = db.execute("DELETE FROM contacts WHERE participant=?", (participant,))
            return cur.rowcount == 1

    def participants(self) -> Dict[str, Dict[str, bool]]:
        """``{participant: {"email": bool, "phone": bool}}``: which kinds of
        address are held, never the addresses."""
        with self.connect() as db:
            return {r["participant"]: {"email": bool(r["email"]), "phone": bool(r["phone"])}
                    for r in db.execute("SELECT participant, email, phone FROM contacts")}
