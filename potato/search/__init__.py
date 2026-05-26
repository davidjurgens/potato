"""
Universal full-text search.

SQLite FTS5 lexical search over instance text, behind a pluggable
`SearchBackend` interface (a `VectorBackend` stub documents the contract
for future semantic search). Not gated to QDA Mode — admins/adjudicators
can search any project; annotator search-and-claim is a separate, guarded
opt-in.
"""

from .backend import Hit, SearchBackend, VectorBackend
from .fts5 import FTS5Backend
from .service import (
    clear_search,
    get_search,
    init_search,
    init_search_from_item_state,
    search_settings,
)

__all__ = [
    "Hit",
    "SearchBackend",
    "VectorBackend",
    "FTS5Backend",
    "init_search",
    "init_search_from_item_state",
    "get_search",
    "clear_search",
    "search_settings",
]
