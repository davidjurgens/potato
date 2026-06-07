"""
SQLite FTS5 lexical search backend (universal).

Stores a standalone `instance_fts` virtual table in the shared
`<task_dir>/project.sqlite` (same DB as memos; different table). The
table is created lazily so a SQLite build without FTS5 simply reports
``available() == False`` instead of erroring at import/migration time.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, List, Tuple

from potato.persistence import get_db

from .backend import Hit, SearchBackend

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)

# Snippet match delimiters. We use the STX/ETX control characters as
# sentinels instead of visible punctuation ('[' / ']'): they never occur
# in real instance text, survive JSON transport, and let the frontend
# escape the snippet first (XSS-safe) and only then swap the sentinels for
# a <mark> highlight. Visible brackets would read as literal typos.
SNIPPET_OPEN = "\x02"
SNIPPET_CLOSE = "\x03"


def _to_match_query(q: str) -> str:
    """Turn arbitrary user input into a safe FTS5 MATCH expression.

    FTS5 MATCH has its own syntax; raw punctuation/quotes raise errors.
    We tokenize, drop empties, and AND the tokens as quoted prefix terms
    so partial words still match and nothing is interpreted as syntax.
    """
    tokens = [t for t in _TOKEN_RE.split(q or "") if t]
    if not tokens:
        return ""
    return " ".join(f'"{t}"*' for t in tokens)


class FTS5Backend(SearchBackend):
    name = "fts5"

    def __init__(self, task_dir: str):
        self.task_dir = task_dir
        self._available = None  # lazy-detected, then cached

    # -- internals ---------------------------------------------------------

    def _conn(self):
        return get_db(self.task_dir)

    def _ensure_table(self, conn) -> bool:
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS instance_fts "
                "USING fts5(instance_id UNINDEXED, body)"
            )
            return True
        except Exception as e:
            logger.warning(f"FTS5 unavailable, search disabled: {e}")
            return False

    # -- SearchBackend -----------------------------------------------------

    def available(self) -> bool:
        if self._available is None:
            self._available = self._ensure_table(self._conn())
        return self._available

    def index(self, rows: Iterable[Tuple[str, str]]) -> int:
        conn = self._conn()
        if not self._ensure_table(conn):
            return 0
        conn.execute("DELETE FROM instance_fts")
        n = 0
        for instance_id, text in rows:
            conn.execute(
                "INSERT INTO instance_fts (instance_id, body) VALUES (?, ?)",
                (str(instance_id), text or ""),
            )
            n += 1
        conn.commit()
        logger.info(f"FTS5 indexed {n} instances for {self.task_dir}")
        return n

    def query(self, q: str, limit: int = 50) -> List[Hit]:
        match = _to_match_query(q)
        if not match:
            return []
        conn = self._conn()
        if not self._ensure_table(conn):
            return []
        try:
            cur = conn.execute(
                """SELECT instance_id,
                          snippet(instance_fts, 1, ?, ?, '…', 12) AS snip,
                          rank AS r
                   FROM instance_fts
                   WHERE instance_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (SNIPPET_OPEN, SNIPPET_CLOSE, match, int(limit)),
            )
            return [Hit(instance_id=row["instance_id"],
                        snippet=row["snip"] or "",
                        score=float(row["r"])) for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"FTS5 query failed for {q!r}: {e}")
            return []
