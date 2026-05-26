"""
Search backend abstraction (universal).

A pluggable interface so lexical (FTS5, ships now) and future semantic
(vector) search are interchangeable behind one contract. Not gated to
QDA Mode — useful in any project for locating instances.

Contract:
    available() -> bool        Is this backend usable in this environment?
    index(rows) -> int         (Re)build the index from (id, text) pairs;
                               returns the number of documents indexed.
    query(q, limit) -> [Hit]   Ranked matches for a user query string.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Iterable, List, Tuple


@dataclass(frozen=True)
class Hit:
    """One search result."""
    instance_id: str
    snippet: str
    score: float  # lower rank value = better for FTS5; normalized per backend


class SearchBackend(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def available(self) -> bool:
        """Whether this backend can run here (e.g. FTS5 compiled in)."""

    @abc.abstractmethod
    def index(self, rows: Iterable[Tuple[str, str]]) -> int:
        """(Re)build the index from (instance_id, text) pairs."""

    @abc.abstractmethod
    def query(self, q: str, limit: int = 50) -> List[Hit]:
        """Return up to *limit* ranked hits for query string *q*."""


class VectorBackend(SearchBackend):
    """Placeholder for a future dense/semantic backend.

    Documents the contract a vector backend must satisfy so it can be
    dropped in without touching callers: it would embed instance text
    (reusing potato/ai embedding endpoints), persist vectors alongside
    project.sqlite, and implement ``query`` as nearest-neighbour search.
    Not implemented in this phase — ``available()`` is False so callers
    fall back to FTS5.
    """

    name = "vector"

    def available(self) -> bool:
        return False

    def index(self, rows: Iterable[Tuple[str, str]]) -> int:  # pragma: no cover
        raise NotImplementedError("Vector search backend not implemented yet")

    def query(self, q: str, limit: int = 50) -> List[Hit]:  # pragma: no cover
        raise NotImplementedError("Vector search backend not implemented yet")
